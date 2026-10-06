"""
Traducción de errores de dominio y de base de datos a respuestas HTTP.

Nunca se expone el mensaje crudo de PostgreSQL al cliente: se usa un mensaje
legible por nombre de restricción y el detalle técnico queda en el log
(como evento estructurado, ver core/logs.py).
"""
import structlog
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import IntegrityError, OperationalError

from core.rate_limit import DemasiadosIntentos
from core.security import ConfiguracionIncompleta, ErrorSeguridad, TokenInvalido
from services.excepciones import (
    AccesoDenegado,
    ConflictoNegocio,
    ErrorDominio,
    RecursoNoEncontrado,
    ReglaNegocioInvalida,
    restriccion_violada,
)

logger = structlog.get_logger(__name__)

# SQLSTATE de PostgreSQL
UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"
CHECK_VIOLATION = "23514"
LOCK_NOT_AVAILABLE = "55P03"
DEADLOCK_DETECTED = "40P01"
SERIALIZATION_FAILURE = "40001"

MENSAJES_RESTRICCION = {
    "uq_categorias_slug": "Ya existe una categoría con ese slug",
    "uq_marcas_slug": "Ya existe una marca con ese slug",
    "uq_productos_slug": "Ya existe un producto con ese slug",
    "uq_variantes_sku": "Ya existe una variante con ese SKU",
    "uq_pagos_sinpe_numero_referencia": "Este número de referencia SINPE ya fue registrado",
    "fk_productos_categoria": "La categoría indicada no existe",
    "fk_productos_marca": "La marca indicada no existe",
    "fk_variantes_producto": "El producto indicado no existe",
    "fk_imagenes_producto": "El producto indicado no existe",
    "fk_imagenes_variante": "La variante indicada no existe",
    "fk_pagos_sinpe_pedido": "El pedido indicado no existe",
    "chk_variantes_stock_no_negativo": "El stock no puede quedar en negativo",
    "uq_imagenes_principal_por_producto": "El producto ya tiene una imagen principal; reintente",
    "uq_pedidos_clave_idempotencia": "La clave de idempotencia ya fue utilizada",
}

STATUS_POR_ERROR_DOMINIO: list[tuple[type[ErrorDominio], int]] = [
    (RecursoNoEncontrado, status.HTTP_404_NOT_FOUND),
    (AccesoDenegado, status.HTTP_403_FORBIDDEN),
    (ReglaNegocioInvalida, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (ConflictoNegocio, status.HTTP_409_CONFLICT),
]


def _respuesta(codigo: int, mensaje: str, detalle: list | None = None) -> JSONResponse:
    contenido: dict = {"detail": mensaje}
    if detalle:
        contenido["errores"] = detalle
    return JSONResponse(status_code=codigo, content=contenido)


def _sqlstate(exc: Exception) -> str | None:
    original = getattr(exc, "orig", None)
    # psycopg 3 expone .sqlstate; psycopg2 expone .pgcode
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


async def _manejar_error_dominio(request: Request, exc: ErrorDominio) -> JSONResponse:
    codigo = next(
        (cod for tipo, cod in STATUS_POR_ERROR_DOMINIO if isinstance(exc, tipo)),
        status.HTTP_400_BAD_REQUEST,
    )
    return _respuesta(codigo, exc.mensaje, exc.detalle)


async def _manejar_integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
    sqlstate = _sqlstate(exc)
    restriccion = restriccion_violada(exc)
    logger.info("bd_restriccion_violada", sqlstate=sqlstate, restriccion=restriccion)

    mensaje = MENSAJES_RESTRICCION.get(restriccion or "", "Los datos violan una restricción")
    if sqlstate == UNIQUE_VIOLATION:
        return _respuesta(status.HTTP_409_CONFLICT, mensaje)
    if sqlstate == FOREIGN_KEY_VIOLATION:
        # "is not present" -> referencia inexistente; si no, el registro está en uso.
        if "is not present" in str(exc.orig):
            return _respuesta(status.HTTP_422_UNPROCESSABLE_CONTENT, mensaje)
        return _respuesta(status.HTTP_409_CONFLICT, "El registro está en uso por otros datos")
    if sqlstate == CHECK_VIOLATION:
        return _respuesta(status.HTTP_422_UNPROCESSABLE_CONTENT, mensaje)
    return _respuesta(status.HTTP_409_CONFLICT, mensaje)


async def _manejar_operational_error(request: Request, exc: OperationalError) -> JSONResponse:
    sqlstate = _sqlstate(exc)
    if sqlstate in {LOCK_NOT_AVAILABLE, DEADLOCK_DETECTED, SERIALIZATION_FAILURE}:
        # El detalle (recurso, espera_ms) ya lo registró services/bloqueos.py.
        logger.info("bd_contencion_respondida_409", sqlstate=sqlstate)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "Recurso ocupado por otra operación, intente de nuevo"},
            headers={"Retry-After": "1"},
        )
    logger.exception("bd_error_operacional", sqlstate=sqlstate)
    return _respuesta(status.HTTP_503_SERVICE_UNAVAILABLE, "Base de datos no disponible")


async def _manejar_error_seguridad(request: Request, exc: ErrorSeguridad) -> JSONResponse:
    if isinstance(exc, ConfiguracionIncompleta):
        # Fallar cerrado: sin configuración de seguridad, nadie entra al área admin.
        logger.error("seguridad_sin_configurar", detalle=exc.mensaje)
        return _respuesta(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Área administrativa deshabilitada: configuración de seguridad incompleta",
        )
    if isinstance(exc, TokenInvalido):
        logger.info("token_rechazado", motivo=exc.mensaje)
    # RFC 6750: un 401 de un recurso protegido por Bearer debe anunciar el esquema.
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": exc.mensaje},
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _manejar_rate_limit(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Límite por IP de slowapi superado."""
    logger.warning("rate_limit_excedido", limite=str(exc.detail),
                   ip=request.client.host if request.client else None)
    respuesta = JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": f"Demasiadas solicitudes ({exc.detail}); intente más tarde"},
    )
    # Agrega Retry-After y X-RateLimit-* calculados por slowapi.
    return request.app.state.limiter._inject_headers(respuesta, request.state.view_rate_limit)


async def _manejar_demasiados_intentos(request: Request, exc: DemasiadosIntentos) -> JSONResponse:
    """Recurso bloqueado por exceso de intentos fallidos (ya registrado en core/rate_limit.py)."""
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": exc.mensaje},
        headers={"Retry-After": str(exc.reintentar_en)},
    )


def registrar_manejadores(app: FastAPI) -> None:
    app.add_exception_handler(RateLimitExceeded, _manejar_rate_limit)
    app.add_exception_handler(DemasiadosIntentos, _manejar_demasiados_intentos)
    app.add_exception_handler(ErrorSeguridad, _manejar_error_seguridad)
    app.add_exception_handler(ErrorDominio, _manejar_error_dominio)
    app.add_exception_handler(IntegrityError, _manejar_integrity_error)
    app.add_exception_handler(OperationalError, _manejar_operational_error)
