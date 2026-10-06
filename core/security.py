"""
Seguridad: hashing de contraseñas (Argon2id) y tokens de acceso JWT (HS256).

Flujo:
    1. POST /auth/login recibe usuario + contraseña (formulario OAuth2).
    2. autenticar_admin() compara contra las credenciales del .env.
    3. crear_token_acceso() firma un JWT con JWT_SECRET_KEY y vencimiento corto.
    4. El cliente envía `Authorization: Bearer <token>` en cada request a /admin.
    5. decodificar_token() verifica firma, algoritmo, emisor, vencimiento y rol.

Este módulo no conoce HTTP: señala problemas con excepciones que errores.py
traduce a 401 / 503.

Utilidades de línea de comandos:
    python -m core.security hash      -> genera ADMIN_PASSWORD_HASH (pide la contraseña)
    python -m core.security secreto   -> genera un JWT_SECRET_KEY aleatorio
"""
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
import structlog
from pwdlib import PasswordHash

from core.config import Settings, get_settings

logger = structlog.get_logger(__name__)

ROL_ADMIN = "admin"
LONGITUD_MINIMA_SECRETO = 32  # HS256 requiere una clave de al menos 256 bits

# Argon2id con los parámetros recomendados por pwdlib (resistente a GPU/ASIC).
_hasher = PasswordHash.recommended()
# Hash de referencia para gastar el mismo tiempo cuando el usuario no existe.
_HASH_SEÑUELO = _hasher.hash(secrets.token_urlsafe(16))


# ============================================================================
# Excepciones
# ============================================================================
class ErrorSeguridad(Exception):
    def __init__(self, mensaje: str) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje


class ConfiguracionIncompleta(ErrorSeguridad):
    """Faltan variables de seguridad en el entorno. -> 503"""


class CredencialesInvalidas(ErrorSeguridad):
    """Usuario o contraseña incorrectos. -> 401"""


class TokenInvalido(ErrorSeguridad):
    """Token ausente, mal firmado, vencido o sin permisos. -> 401"""


# ============================================================================
# Contraseñas
# ============================================================================
def hashear_password(password: str) -> str:
    return _hasher.hash(password)


def verificar_password(password: str, hash_: str) -> bool:
    try:
        return _hasher.verify(password, hash_)
    except Exception:  # noqa: BLE001 - hash corrupto o de un algoritmo desconocido: se rechaza
        logger.error("admin_password_hash_invalido")
        return False


@lru_cache
def _hash_de_texto_plano(password: str) -> str:
    # Argon2 es lento a propósito: se hashea una sola vez por proceso.
    logger.warning(
        "admin_password_texto_plano",
        recomendacion="En producción define ADMIN_PASSWORD_HASH (python -m core.security hash)",
    )
    return hashear_password(password)


def _credenciales_admin(cfg: Settings) -> tuple[str, str]:
    if not cfg.admin_user:
        raise ConfiguracionIncompleta("Falta ADMIN_USER")
    if cfg.admin_password_hash:
        return cfg.admin_user, cfg.admin_password_hash
    if cfg.admin_password:
        return cfg.admin_user, _hash_de_texto_plano(cfg.admin_password.get_secret_value())
    raise ConfiguracionIncompleta("Falta ADMIN_PASSWORD_HASH o ADMIN_PASSWORD")


def autenticar_admin(usuario: str, password: str) -> str:
    """Devuelve el nombre de usuario si las credenciales son correctas."""
    cfg = get_settings()
    usuario_esperado, hash_esperado = _credenciales_admin(cfg)

    usuario_ok = secrets.compare_digest(usuario.encode(), usuario_esperado.encode())
    # Se verifica la contraseña aunque el usuario no coincida: así el tiempo de
    # respuesta no revela si el nombre de usuario existe.
    password_ok = verificar_password(password, hash_esperado if usuario_ok else _HASH_SEÑUELO)

    if not (usuario_ok and password_ok):
        logger.warning("login_fallido", usuario=usuario[:64])
        raise CredencialesInvalidas("Usuario o contraseña incorrectos")
    logger.info("login_exitoso", usuario=usuario_esperado)
    return usuario_esperado


# ============================================================================
# Tokens JWT
# ============================================================================
@dataclass(frozen=True)
class TokenEmitido:
    access_token: str
    expira_en_segundos: int


@dataclass(frozen=True)
class SesionAdmin:
    usuario: str
    rol: str
    expira: datetime
    jti: str


def _secreto(cfg: Settings) -> str:
    if cfg.jwt_secret_key is None:
        raise ConfiguracionIncompleta("Falta JWT_SECRET_KEY")
    secreto = cfg.jwt_secret_key.get_secret_value()
    if len(secreto) < LONGITUD_MINIMA_SECRETO:
        raise ConfiguracionIncompleta(
            f"JWT_SECRET_KEY debe tener al menos {LONGITUD_MINIMA_SECRETO} caracteres"
        )
    return secreto


def crear_token_acceso(usuario: str, rol: str = ROL_ADMIN) -> TokenEmitido:
    cfg = get_settings()
    ahora = datetime.now(UTC)
    duracion = timedelta(minutes=cfg.jwt_expiracion_minutos)
    payload = {
        "sub": usuario,               # sujeto: a quién representa el token
        "rol": rol,                   # autorización
        "iss": cfg.jwt_emisor,        # emisor: rechaza tokens de otros sistemas
        "iat": ahora,                 # emitido en
        "exp": ahora + duracion,      # vence en
        "jti": uuid.uuid4().hex,      # id único: base para una futura lista de revocación
    }
    token = jwt.encode(payload, _secreto(cfg), algorithm=cfg.jwt_algoritmo)
    return TokenEmitido(access_token=token, expira_en_segundos=int(duracion.total_seconds()))


def decodificar_token(token: str, rol_requerido: str = ROL_ADMIN) -> SesionAdmin:
    cfg = get_settings()
    try:
        payload = jwt.decode(
            token,
            _secreto(cfg),
            # Lista explícita de algoritmos: impide ataques de "alg: none" o de
            # confusión de algoritmo con un token fabricado por el atacante.
            algorithms=[cfg.jwt_algoritmo],
            issuer=cfg.jwt_emisor,
            options={"require": ["sub", "rol", "iss", "iat", "exp", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenInvalido("El token expiró; inicie sesión de nuevo") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalido("Token inválido") from exc

    if payload["rol"] != rol_requerido:
        raise TokenInvalido("El token no tiene permisos para esta operación")

    return SesionAdmin(
        usuario=payload["sub"],
        rol=payload["rol"],
        expira=datetime.fromtimestamp(payload["exp"], UTC),
        jti=payload["jti"],
    )


# ============================================================================
# CLI
# ============================================================================
if __name__ == "__main__":
    import getpass
    import sys

    comando = sys.argv[1] if len(sys.argv) > 1 else ""
    if comando == "hash":
        password = getpass.getpass("Contraseña del administrador: ")
        if password != getpass.getpass("Repítala: "):
            sys.exit("Las contraseñas no coinciden")
        # Comillas simples: el hash contiene '$' y así .env no intenta interpolarlo.
        print(f"ADMIN_PASSWORD_HASH='{hashear_password(password)}'")
    elif comando == "secreto":
        print(f"JWT_SECRET_KEY={secrets.token_urlsafe(64)}")
    else:
        sys.exit("Uso: python -m core.security [hash | secreto]")
