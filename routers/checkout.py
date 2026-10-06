"""Flujo público de compra: checkout de invitado y reporte de pago SINPE."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response, status

from core.config import get_settings
from core.rate_limit import limitar_fallos, limite_seguimiento, limiter
from dependencies import DbSession
from schemas import PagoSinpeCreate, PagoSinpeResponse, PedidoCreate, PedidoDetalleResponse
from services import checkout, pagos, pedidos
from services.excepciones import AccesoDenegado

router = APIRouter(tags=["Checkout"])

IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=100,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Clave única por intento de compra (ej. un UUID v4 generado por el frontend). "
        "Reintentar con la misma clave devuelve el pedido original sin duplicarlo.",
    ),
]


@router.post(
    "/pedidos",
    response_model=PedidoDetalleResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"description": "Stock insuficiente o inventario ocupado"},
        422: {"description": "Datos inválidos o Idempotency-Key reutilizada con otro carrito"},
    },
)
def crear_pedido(
    datos: PedidoCreate,
    db: DbSession,
    response: Response,
    idempotency_key: IdempotencyKey = None,
):
    """Crea el pedido y reserva el stock. Precios y totales los calcula el servidor."""
    resultado = checkout.crear_pedido(db, datos, clave_idempotencia=idempotency_key)
    if resultado.es_repeticion:
        response.headers["Idempotent-Replayed"] = "true"
    return resultado.pedido


@router.get(
    "/pedidos/{pedido_id}",
    response_model=PedidoDetalleResponse,
    responses={
        403: {"description": "Los dígitos de verificación no coinciden"},
        429: {"description": "Demasiadas solicitudes o demasiados intentos fallidos para este pedido"},
    },
)
@limiter.limit(limite_seguimiento)
def obtener_pedido(
    request: Request,  # requerido por slowapi
    response: Response,  # slowapi agrega aquí los headers X-RateLimit-*
    pedido_id: uuid.UUID,
    db: DbSession,
    ultimos4: Annotated[
        str,
        Query(pattern=r"^\d{4}$", description="Últimos 4 dígitos del WhatsApp del pedido"),
    ],
):
    """
    Seguimiento del pedido: requiere el UUID y los últimos 4 dígitos del WhatsApp.

    Anti-enumeración: los 4 dígitos son solo 10.000 combinaciones, así que el
    pedido se bloquea tras RATE_LIMIT_FALLOS_SEGUIMIENTO intentos fallidos,
    vengan de la IP que vengan.
    """
    with limitar_fallos(
        "seguimiento", str(pedido_id), get_settings().rate_limit_fallos_seguimiento,
        fallos=(AccesoDenegado,),
    ):
        return pedidos.obtener_pedido_para_cliente(db, pedido_id, ultimos4)


@router.post(
    "/pagos",
    response_model=PagoSinpeResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "Referencia SINPE repetida o pedido no pagable"}},
)
def registrar_pago(datos: PagoSinpeCreate, db: DbSession):
    """El cliente reporta su comprobante SINPE Móvil para conciliación."""
    return pagos.registrar_pago(db, datos)
