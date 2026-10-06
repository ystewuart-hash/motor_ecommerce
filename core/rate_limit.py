"""
Rate limiting: defensa contra fuerza bruta y abuso.

Dos capas complementarias que comparten el mismo almacenamiento (memoria o Redis):

1. Límite por IP (slowapi, decorador @limiter.limit en el endpoint).
   Cuenta TODAS las peticiones de una IP. Frena ráfagas de un solo origen.

2. Límite de intentos FALLIDOS por recurso (context manager limitar_fallos).
   Cuenta solo los fallos, agrupados por usuario (login) o por pedido
   (seguimiento). Frena la fuerza bruta distribuida —un atacante con miles de
   IPs sigue chocando contra el mismo contador del pedido— y no castiga al
   cliente legítimo que refresca su seguimiento con los dígitos correctos.

Los valores se leen de core.config en cada petición, así que se ajustan con
variables de entorno (RATE_LIMIT_*) sin tocar código.
"""
import math
import time
from collections.abc import Iterator
from contextlib import contextmanager

import structlog
from limits import parse
from slowapi import Limiter
from slowapi.util import get_remote_address

from core.config import get_settings

logger = structlog.get_logger(__name__)

_cfg = get_settings()

# key_func=get_remote_address usa request.client.host. Detrás de un proxy
# (Nginx, balanceador) uvicorn debe arrancar con --proxy-headers y
# --forwarded-allow-ips para que esa IP sea la del cliente real y no la del proxy.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_cfg.rate_limit_storage_uri,
    strategy="moving-window",   # ventana deslizante: sin el "doble cupo" en el borde del minuto
    headers_enabled=True,       # X-RateLimit-Limit / -Remaining / -Reset en las respuestas
    enabled=_cfg.rate_limit_habilitado,
)


# Límites dinámicos: slowapi los evalúa en cada request.
def limite_login() -> str:
    return get_settings().rate_limit_login


def limite_seguimiento() -> str:
    return get_settings().rate_limit_seguimiento


class DemasiadosIntentos(Exception):
    """Se superó el máximo de intentos fallidos para un recurso. -> 429"""

    def __init__(self, mensaje: str, reintentar_en: int) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.reintentar_en = reintentar_en


@contextmanager
def limitar_fallos(
    ambito: str,
    clave: str,
    limite: str,
    fallos: tuple[type[Exception], ...],
) -> Iterator[None]:
    """
    Bloquea un recurso tras demasiados intentos fallidos.

        with limitar_fallos("seguimiento", str(pedido_id), "10/day", (AccesoDenegado,)):
            ...operación que lanza AccesoDenegado si el intento falla...

    - Si el recurso ya agotó su cupo de fallos: lanza DemasiadosIntentos (429)
      SIN ejecutar la operación (ni siquiera se verifica el intento).
    - Si la operación lanza una de las excepciones `fallos`: se cuenta el fallo
      y la excepción sigue su curso (403/401 normal).
    - Si tiene éxito: no se cuenta nada.
    """
    if not limiter.enabled:
        yield
        return

    item = parse(limite)
    estrategia = limiter.limiter  # misma estrategia y almacenamiento que slowapi
    identificadores = ("fallos", ambito, clave)

    if not estrategia.test(item, *identificadores):
        reinicio, _ = estrategia.get_window_stats(item, *identificadores)
        reintentar_en = max(1, math.ceil(reinicio - time.time()))
        logger.warning("rate_limit_bloqueo_por_fallos", ambito=ambito, clave=clave,
                       limite=limite, reintentar_en_s=reintentar_en)
        raise DemasiadosIntentos(
            "Demasiados intentos fallidos; espere antes de reintentar", reintentar_en
        )

    try:
        yield
    except fallos:
        estrategia.hit(item, *identificadores)
        restantes = estrategia.get_window_stats(item, *identificadores).remaining
        logger.info("rate_limit_fallo_registrado", ambito=ambito, clave=clave,
                    intentos_restantes=restantes)
        raise
