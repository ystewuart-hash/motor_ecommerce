"""
Logging estructurado con structlog.

Cada línea es un objeto JSON con campos fijos (timestamp, level, logger, event)
más el contexto del evento, por ejemplo:

    {"event": "lock_timeout", "recurso": "variantes_producto", "espera_ms": 5003.1,
     "request_id": "9f2c…", "level": "warning", "logger": "services.bloqueos",
     "timestamp": "2026-10-06T15:42:10.118Z"}

Así los logs se pueden filtrar y agregar en herramientas como Loki, Datadog,
CloudWatch o simplemente con `jq`. Los logs de librerías que usan el módulo
estándar `logging` (uvicorn, APScheduler, SQLAlchemy) pasan por el mismo
formateador y también salen en JSON.

Convención: el `event` es un identificador estable en snake_case (no una frase),
para poder buscarlo y contarlo. Nunca se registran datos personales (nombre,
WhatsApp, dirección) ni secretos (contraseñas, tokens, query strings).
"""
import logging
import sys
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.requests import Request
from starlette.responses import Response

LOGGERS_SILENCIADOS = {
    "uvicorn.access": logging.WARNING,     # reemplazado por el evento "request"
    "apscheduler": logging.WARNING,        # el job emite sus propios eventos
    "sqlalchemy.engine": logging.WARNING,
    "slowapi": logging.ERROR,              # rate_limit_excedido lo emite errores.py
}


def _quitar_campos_de_color(
    _logger: object, _metodo: str, evento: structlog.typing.EventDict
) -> structlog.typing.EventDict:
    """uvicorn adjunta `color_message` (con códigos ANSI) para su consola: en JSON es ruido."""
    evento.pop("color_message", None)
    return evento


def configurar_logging(nivel: str = "INFO", formato: str = "json") -> None:
    procesadores_comunes: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,      # request_id, método, ruta
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.stdlib.ExtraAdder(),
        _quitar_campos_de_color,
    ]
    if formato == "json":
        renderizador: structlog.typing.Processor = structlog.processors.JSONRenderer(ensure_ascii=False)
        excepciones: structlog.typing.Processor = structlog.processors.dict_tracebacks
    else:  # consola: legible y con colores, para desarrollo local
        renderizador = structlog.dev.ConsoleRenderer()
        excepciones = structlog.processors.StackInfoRenderer()

    structlog.configure(
        processors=[*procesadores_comunes, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        # False permite que structlog.testing.capture_logs intercepte los eventos en los tests.
        cache_logger_on_first_use=False,
    )

    formateador = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=procesadores_comunes,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            excepciones,
            renderizador,
        ],
    )
    manejador = logging.StreamHandler(sys.stdout)
    manejador.setFormatter(formateador)

    raiz = logging.getLogger()
    raiz.handlers = [manejador]
    raiz.setLevel(nivel)

    # uvicorn instala sus propios handlers al arrancar: se redirigen a la raíz
    # para que también salgan en JSON.
    for nombre in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger_uvicorn = logging.getLogger(nombre)
        logger_uvicorn.handlers.clear()
        logger_uvicorn.propagate = True
    for nombre, nivel_minimo in LOGGERS_SILENCIADOS.items():
        logging.getLogger(nombre).setLevel(nivel_minimo)


# ============================================================================
# Middleware: contexto por request + evento de acceso
# ============================================================================
logger_acceso = structlog.get_logger("api.acceso")


def _request_id(request: Request) -> str:
    # Se respeta el X-Request-ID del proxy/balanceador para correlacionar logs
    # entre servicios; si no viene (o es sospechoso), se genera uno.
    entrante = request.headers.get("x-request-id", "")
    if 8 <= len(entrante) <= 64 and entrante.replace("-", "").isalnum():
        return entrante
    return uuid.uuid4().hex


async def middleware_logging(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """
    Vincula request_id/método/ruta a todos los logs emitidos durante la request
    (contextvars, que FastAPI propaga también a los endpoints síncronos) y
    registra un evento "request" con el status y la duración.
    La query string NO se registra: puede contener datos como ?ultimos4=.
    """
    structlog.contextvars.clear_contextvars()
    request_id = _request_id(request)
    structlog.contextvars.bind_contextvars(
        request_id=request_id, metodo=request.method, ruta=request.url.path
    )
    inicio = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger_acceso.exception("request_error_no_manejado",
                                duracion_ms=round((time.perf_counter() - inicio) * 1000, 1))
        raise

    duracion_ms = round((time.perf_counter() - inicio) * 1000, 1)
    nivel = logging.ERROR if response.status_code >= 500 else logging.INFO
    logger_acceso.log(nivel, "request", status=response.status_code, duracion_ms=duracion_ms,
                      ip=request.client.host if request.client else None)
    response.headers["X-Request-ID"] = request_id
    return response
