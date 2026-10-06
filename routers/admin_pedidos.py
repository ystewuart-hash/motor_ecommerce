"""Operación de pedidos y conciliación de pagos. Exige un token JWT Bearer de administrador."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from dependencies import DbSession, PaginacionDep, verificar_admin
from models import EstadoPedido, EstadoValidacionPago
from schemas import (
    PagoSinpeResponse,
    PagoSinpeUpdate,
    PedidoDetalleResponse,
    PedidoResponse,
    PedidoUpdate,
)
from services import pagos, pedidos

router = APIRouter(
    prefix="/admin",
    tags=["Admin · Pedidos y Pagos"],
    dependencies=[Depends(verificar_admin)],
)


@router.get("/pedidos", response_model=list[PedidoResponse])
def listar_pedidos(db: DbSession, pag: PaginacionDep, estado: EstadoPedido | None = None):
    return pedidos.listar_pedidos(db, estado=estado, limit=pag.limit, offset=pag.offset)


@router.post("/pedidos/cancelar-vencidos")
def cancelar_pedidos_vencidos(
    db: DbSession,
    horas: Annotated[int, Query(ge=1, le=720, description="Antigüedad mínima del pedido impago")] = 48,
) -> dict[str, int]:
    """Cancela pedidos impagos vencidos y libera su stock. Apto para un cron."""
    return {"cancelados": pedidos.cancelar_pedidos_vencidos(db, horas=horas)}


@router.get("/pedidos/{pedido_id}", response_model=PedidoDetalleResponse)
def obtener_pedido(pedido_id: uuid.UUID, db: DbSession):
    return pedidos.obtener_pedido(db, pedido_id)


@router.patch("/pedidos/{pedido_id}", response_model=PedidoDetalleResponse)
def actualizar_pedido(pedido_id: uuid.UUID, datos: PedidoUpdate, db: DbSession):
    """Cambia el estado (validando la transición) o corrige datos de contacto/envío."""
    return pedidos.actualizar_pedido(db, pedido_id, datos)


@router.get("/pagos", response_model=list[PagoSinpeResponse])
def listar_pagos(
    db: DbSession,
    pag: PaginacionDep,
    estado: EstadoValidacionPago | None = EstadoValidacionPago.PENDIENTE,
):
    """Por defecto muestra la cola de comprobantes pendientes de conciliar."""
    return pagos.listar_pagos(db, estado=estado, limit=pag.limit, offset=pag.offset)


@router.patch("/pagos/{pago_id}", response_model=PagoSinpeResponse)
def conciliar_pago(pago_id: uuid.UUID, datos: PagoSinpeUpdate, db: DbSession):
    """Aprueba o rechaza un comprobante; si cubre el total, el pedido pasa a preparación."""
    return pagos.conciliar_pago(db, pago_id, datos)
