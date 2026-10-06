"""
Servicio de pedidos: consulta, máquina de estados y devolución de stock.

El stock se reserva (descuenta) en el checkout. Por eso cancelar un pedido debe
devolverlo, y los pedidos impagos deben vencer: si no, un carrito abandonado
retiene inventario para siempre.
"""
import secrets
import uuid
from collections import Counter
from collections.abc import Iterable
from datetime import timedelta

import structlog
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, selectinload

from models import EstadoPedido, EstadoValidacionPago, ItemPedido, PagoSinpe, Pedido
from schemas.transacciones import PedidoUpdate
from services.bloqueos import bloquear_pedido, bloquear_variantes, establecer_lock_timeout
from services.envio import calcular_costo_envio
from services.excepciones import AccesoDenegado, ConflictoNegocio, RecursoNoEncontrado
from services.pagos import total_aprobado

logger = structlog.get_logger(__name__)

E = EstadoPedido

TRANSICIONES_PERMITIDAS: dict[EstadoPedido, frozenset[EstadoPedido]] = {
    E.PENDIENTE_PAGO: frozenset({E.EN_PREPARACION, E.CANCELADO}),
    E.EN_PREPARACION: frozenset({E.ENVIADO, E.CANCELADO}),
    E.ENVIADO: frozenset({E.ENTREGADO, E.REEMBOLSADO}),
    E.ENTREGADO: frozenset({E.REEMBOLSADO}),
    E.CANCELADO: frozenset({E.REEMBOLSADO}),
    E.REEMBOLSADO: frozenset(),
}

# Datos de contacto editables mientras el paquete no haya salido.
ESTADOS_CONTACTO_EDITABLE = frozenset({E.PENDIENTE_PAGO, E.EN_PREPARACION})
# La dirección define el costo de envío: solo editable antes de pagar.
ESTADOS_DIRECCION_EDITABLE = frozenset({E.PENDIENTE_PAGO})

TAMANO_LOTE_VENCIDOS = 200


def obtener_pedido(db: Session, pedido_id: uuid.UUID) -> Pedido:
    stmt = (
        select(Pedido)
        .where(Pedido.id == pedido_id)
        .options(selectinload(Pedido.items), selectinload(Pedido.pagos))
    )
    pedido = db.scalars(stmt).one_or_none()
    if pedido is None:
        raise RecursoNoEncontrado("Pedido no encontrado")
    return pedido


def obtener_pedido_para_cliente(db: Session, pedido_id: uuid.UUID, ultimos4: str) -> Pedido:
    """
    Seguimiento público: además del UUID, exige los últimos 4 dígitos del
    WhatsApp del pedido como segundo factor de "posesión" (lo que el cliente sabe).

    compare_digest evita filtrar por tiempo de respuesta cuántos dígitos acertó.
    10.000 combinaciones son pocas frente a fuerza bruta: este endpoint debe
    llevar rate limiting en el proxy/API gateway.
    """
    pedido = obtener_pedido(db, pedido_id)
    digitos = "".join(c for c in pedido.cliente_whatsapp if c.isdigit())
    if not secrets.compare_digest(digitos[-4:], ultimos4):
        raise AccesoDenegado("Los datos de verificación no coinciden con el pedido")
    return pedido


def listar_pedidos(
    db: Session,
    *,
    estado: EstadoPedido | None,
    limit: int,
    offset: int,
) -> list[Pedido]:
    # Usa idx_pedidos_estado_fecha (estado_pedido, fecha_creacion DESC).
    stmt = select(Pedido).order_by(Pedido.fecha_creacion.desc()).limit(limit).offset(offset)
    if estado is not None:
        stmt = stmt.where(Pedido.estado_pedido == estado)
    return list(db.scalars(stmt))


def actualizar_pedido(db: Session, pedido_id: uuid.UUID, datos: PedidoUpdate) -> Pedido:
    establecer_lock_timeout(db)
    pedido = bloquear_pedido(db, pedido_id)
    cambios = datos.model_dump(exclude_unset=True, exclude={"estado_pedido", "direccion_envio"})

    if cambios:
        if pedido.estado_pedido not in ESTADOS_CONTACTO_EDITABLE:
            raise ConflictoNegocio(
                f"Los datos del cliente no se pueden editar en estado '{pedido.estado_pedido}'"
            )
        for campo, valor in cambios.items():
            setattr(pedido, campo, valor)

    if datos.direccion_envio is not None:
        if pedido.estado_pedido not in ESTADOS_DIRECCION_EDITABLE:
            raise ConflictoNegocio("La dirección solo se puede cambiar antes del pago")
        pedido.direccion_envio = datos.direccion_envio.a_jsonb()
        pedido.costo_envio = calcular_costo_envio(datos.direccion_envio)
        pedido.monto_total = pedido.subtotal_productos + pedido.costo_envio

    if datos.estado_pedido is not None:
        _transicionar(db, pedido, datos.estado_pedido)

    db.commit()
    return obtener_pedido(db, pedido_id)


def cancelar_pedidos_vencidos(db: Session, *, horas: int) -> int:
    """
    Cancela pedidos impagos más antiguos que `horas` y devuelve su stock.

    Respeta pedidos con algún comprobante pendiente o aprobado (hay dinero en
    juego). SKIP LOCKED permite correrlo en paralelo con el tráfico normal sin
    esperar por pedidos que otra transacción está modificando.
    Pensado para ejecutarse periódicamente (cron / scheduler).
    """
    establecer_lock_timeout(db)
    pago_vigente = exists().where(
        PagoSinpe.pedido_id == Pedido.id,
        PagoSinpe.estado_validacion != EstadoValidacionPago.RECHAZADO,
    )
    stmt = (
        select(Pedido)
        .where(
            Pedido.estado_pedido == E.PENDIENTE_PAGO,
            Pedido.fecha_creacion < func.now() - timedelta(hours=horas),
            ~pago_vigente,
        )
        .order_by(Pedido.fecha_creacion)
        .limit(TAMANO_LOTE_VENCIDOS)
        .with_for_update(skip_locked=True)
        .options(selectinload(Pedido.items))
        .execution_options(populate_existing=True)
    )
    pedidos = list(db.scalars(stmt))
    if not pedidos:
        return 0

    # Un único bloqueo ordenado de todas las variantes del lote (evita deadlocks).
    reponer_stock(db, (item for pedido in pedidos for item in pedido.items))
    for pedido in pedidos:
        pedido.estado_pedido = E.CANCELADO

    db.commit()
    logger.info("pedidos_vencidos_cancelados", cantidad=len(pedidos), horas=horas)
    return len(pedidos)


def reponer_stock(db: Session, items: Iterable[ItemPedido]) -> None:
    """Devuelve al inventario las unidades de los ítems (requiere transacción abierta)."""
    cantidades: Counter[uuid.UUID] = Counter()
    for item in items:
        cantidades[item.variante_id] += item.cantidad

    variantes = bloquear_variantes(db, cantidades)
    for variante_id, cantidad in cantidades.items():
        # La FK con ON DELETE RESTRICT garantiza que la variante sigue existiendo.
        variantes[variante_id].stock_disponible += cantidad
    logger.info("stock_repuesto", variantes=len(cantidades), unidades=sum(cantidades.values()))


def _transicionar(db: Session, pedido: Pedido, nuevo: EstadoPedido) -> None:
    actual = pedido.estado_pedido
    if nuevo == actual:
        return
    if nuevo not in TRANSICIONES_PERMITIDAS[actual]:
        raise ConflictoNegocio(f"Transición no permitida: '{actual}' -> '{nuevo}'")

    if nuevo == E.EN_PREPARACION and total_aprobado(db, pedido.id) < pedido.monto_total:
        raise ConflictoNegocio("El pedido no tiene pagos aprobados que cubran el monto total")

    if nuevo == E.REEMBOLSADO and total_aprobado(db, pedido.id) == 0:
        raise ConflictoNegocio("No hay pagos aprobados que reembolsar")

    if nuevo == E.CANCELADO:
        # Cancelar solo es posible antes del envío: la mercadería sigue en bodega.
        # Un reembolso tras el envío NO repone stock automáticamente; si el
        # producto vuelve en buen estado se registra con un ajuste de stock.
        reponer_stock(db, pedido.items)

    pedido.estado_pedido = nuevo
    logger.info("pedido_estado_cambiado", pedido_id=str(pedido.id), desde=str(actual), hacia=str(nuevo))
