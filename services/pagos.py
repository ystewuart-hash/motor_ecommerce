"""
Servicio de pagos SINPE Móvil: registro de comprobantes y conciliación.

La barrera anti-fraude principal (número de referencia único) la impone la BD
con uq_pagos_sinpe_numero_referencia; errores.py la traduce a un 409 legible.
"""
import uuid
from decimal import Decimal

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import EstadoPedido, EstadoValidacionPago, PagoSinpe
from schemas.transacciones import PagoSinpeCreate, PagoSinpeUpdate
from services.bloqueos import bloquear_pago, bloquear_pedido, establecer_lock_timeout
from services.excepciones import ConflictoNegocio, RecursoNoEncontrado, ReglaNegocioInvalida

logger = structlog.get_logger(__name__)


def total_aprobado(db: Session, pedido_id: uuid.UUID) -> Decimal:
    stmt = select(func.coalesce(func.sum(PagoSinpe.monto_transferido), 0)).where(
        PagoSinpe.pedido_id == pedido_id,
        PagoSinpe.estado_validacion == EstadoValidacionPago.APROBADO,
    )
    return Decimal(db.scalar(stmt))


def registrar_pago(db: Session, datos: PagoSinpeCreate) -> PagoSinpe:
    """El cliente reporta su comprobante; queda pendiente de conciliación."""
    establecer_lock_timeout(db)
    # El lock serializa el registro frente a una cancelación simultánea del pedido.
    pedido = bloquear_pedido(db, datos.pedido_id)
    if pedido.estado_pedido != EstadoPedido.PENDIENTE_PAGO:
        raise ConflictoNegocio(
            f"El pedido no admite pagos en estado '{pedido.estado_pedido}'"
        )

    pago = PagoSinpe(**datos.model_dump())
    db.add(pago)
    db.commit()
    db.refresh(pago)
    logger.info("pago_registrado", pago_id=str(pago.id), pedido_id=str(pago.pedido_id),
                monto=str(pago.monto_transferido))
    return pago


def conciliar_pago(db: Session, pago_id: uuid.UUID, datos: PagoSinpeUpdate) -> PagoSinpe:
    """
    El administrador aprueba o rechaza un comprobante pendiente.

    Si con esta aprobación los pagos aprobados cubren el monto_total, el pedido
    avanza automáticamente a 'en_preparacion'.
    """
    nuevo_estado = datos.estado_validacion
    if nuevo_estado is None or nuevo_estado == EstadoValidacionPago.PENDIENTE:
        raise ReglaNegocioInvalida("Indique estado_validacion 'aprobado' o 'rechazado'")

    pago = db.get(PagoSinpe, pago_id)
    if pago is None:
        raise RecursoNoEncontrado("Pago no encontrado")

    establecer_lock_timeout(db)
    pedido = bloquear_pedido(db, pago.pedido_id)
    pago = bloquear_pago(db, pago_id)

    if pago.estado_validacion != EstadoValidacionPago.PENDIENTE:
        raise ConflictoNegocio(f"El pago ya fue conciliado como '{pago.estado_validacion}'")

    pago.estado_validacion = nuevo_estado
    db.flush()

    if (
        nuevo_estado == EstadoValidacionPago.APROBADO
        and pedido.estado_pedido == EstadoPedido.PENDIENTE_PAGO
        and total_aprobado(db, pedido.id) >= pedido.monto_total
    ):
        pedido.estado_pedido = EstadoPedido.EN_PREPARACION

    db.commit()
    db.refresh(pago)
    logger.info("pago_conciliado", pago_id=str(pago.id), pedido_id=str(pedido.id),
                resultado=str(nuevo_estado), estado_pedido=str(pedido.estado_pedido))
    return pago


def listar_pagos(
    db: Session,
    *,
    estado: EstadoValidacionPago | None,
    limit: int,
    offset: int,
) -> list[PagoSinpe]:
    stmt = select(PagoSinpe).order_by(PagoSinpe.fecha_registro.desc()).limit(limit).offset(offset)
    if estado is not None:
        stmt = stmt.where(PagoSinpe.estado_validacion == estado)
    return list(db.scalars(stmt))
