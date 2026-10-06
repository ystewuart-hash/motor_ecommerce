"""
Configuración tipada leída de variables de entorno / .env (pydantic-settings).

Cada campo se puede sobrescribir con la variable de entorno del mismo nombre en
mayúsculas (ej. rate_limit_login -> RATE_LIMIT_LOGIN). Los campos de seguridad
son opcionales a propósito: la app arranca aunque falten, pero el área
administrativa queda cerrada (503) hasta configurarlos.
"""
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Credenciales del administrador (provisionales, hasta tener tabla de usuarios) ---
    admin_user: str | None = None
    # Preferido: hash Argon2 generado con `python -m core.security hash`.
    admin_password_hash: str | None = None
    # Alternativa de desarrollo: contraseña en texto plano (se hashea en memoria al arrancar).
    admin_password: SecretStr | None = None

    # --- JWT ---
    jwt_secret_key: SecretStr | None = None
    jwt_algoritmo: str = "HS256"
    jwt_expiracion_minutos: int = 30
    jwt_emisor: str = "motor-ecommerce"

    # --- Rate limiting (sintaxis de `limits`: "5/minute", "100/hour", "10/day") ---
    rate_limit_habilitado: bool = True
    # memory:// sirve para un solo proceso. Con varios workers o servidores usar
    # Redis para que compartan contadores: redis://host:6379/0
    rate_limit_storage_uri: str = "memory://"
    # Límites por IP (cuentan todas las peticiones).
    rate_limit_login: str = "5/minute"
    rate_limit_seguimiento: str = "30/minute"
    # Límites por recurso (cuentan solo los intentos FALLIDOS).
    rate_limit_fallos_login: str = "10/hour"         # por nombre de usuario
    rate_limit_fallos_seguimiento: str = "10/day"     # por pedido

    # --- Tareas programadas ---
    scheduler_habilitado: bool = True
    job_vencidos_intervalo_minutos: int = 60
    pedidos_vencen_horas: int = 48

    # --- Logging ---
    log_nivel: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_formato: Literal["json", "consola"] = "json"
    # Una espera por lock por encima de este umbral se registra como evento.
    log_umbral_lock_lento_ms: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()
