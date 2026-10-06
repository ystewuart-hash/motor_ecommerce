"""
Servicio de checkout: convierte un carrito (variante_id + cantidad) en un pedido.

El backend es la única fuente de verdad: precios, subtotales, costo de envío y
total se calculan aquí a partir de la base de datos; el cliente nunca los envía.

Concurrencia (pesimista):
    1. SET LOCAL lock_timeout: nadie espera indefinidamente un lock.
    2. SELECT ... FOR UPDATE sobre las variantes del carrito, ordenadas por id.
       Mientras esta transacción las tenga bloqueadas, cualquier otro checkout
       que incluya alguna de ellas espera; al continuar lee el stock ya
       descontado, por lo que dos compradores nunca venden la misma unidad.
    3. Validar, descontar stock, congelar precios e insertar el pedido.
    4. COMMIT: libera los locks.

Idempotencia (header Idempotency-Key):
    - Si la clave ya existe, se devuelve el pedido original sin tocar stock.
    - Si dos peticiones gemelas llegan a la vez, la segunda espera los locks de
      la primera y, al obtenerlos, vuelve a buscar la clave: encuentra el pedido
      ya confirmado y lo devuelve.
    - Red de seguridad: si aun así dos inserts compiten (carritos sin variantes
      en común), UNIQUE(clave_idempotencia) rechaza el segundo; su ROLLBACK
      deshace la reserva de stock y se responde con el pedido ganador.
    - Reutilizar una clave con un carrito distinto es un error del cliente (422).
"""
import uuid
from collections import Counter
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import EstadoPedido, ItemPedido, Pedido, VarianteProducto
from schemas.transacciones import ItemPedidoCreate, PedidoCreate
from services.bloqueos import bloquear_variantes, establecer_lock_timeout
from services.envio import calcular_costo_envio
from services.excepciones import ReglaNegocioInvalida, StockInsuficiente, restriccion_violada
from services.pedidos import obtener_pedido

logger = structlog.get_logger(__name__)

CENTIMOS = Decimal("0.01")
RESTRICCION_IDEMPOTENCIA = "uq_pedidos_clave_idempotencia"


@dataclass(frozen=True)
class ResultadoCheckout:
    pedido: Pedido
    es_repeticion: bool  # True si se devolvió un pedido creado por una petición anterior


def crear_pedido(
    db: Session, datos: PedidoCreate, clave_idempotencia: str | None = None
) -> ResultadoCheckout:
    cantidades = _consolidar_lineas(datos.items)

    if clave_idempotencia is not None:
        existente = _pedido_por_clave(db, clave_idempotencia)
        if existente is not None:
            return _repetir(existente, datos, cantidades, fase="previa")

    establecer_lock_timeout(db)
    variantes = bloquear_variantes(db, cantidades)

    if clave_idempotencia is not None:
        # Si esperamos los locks detrás de una petición gemela, su pedido ya está
        # confirmado y es visible ahora (READ COMMITTED). Se revisa ANTES del stock:
        # si no, el doble clic sobre las últimas unidades respondería "sin stock".
        existente = _pedido_por_clave(db, clave_idempotencia)
        if existente is not None:
            db.rollback()  # libera los locks sin haber tocado nada
            return _repetir(existente, datos, cantidades, fase="tras_espera_de_lock")

    _validar_disponibilidad(cantidades, variantes)

    items: list[ItemPedido] = []
    subtotal = Decimal("0")
    for variante_id, cantidad in cantidades.items():
        variante = variantes[variante_id]
        variante.stock_disponible -= cantidad
        subtotal += variante.precio * cantidad
        items.append(
            ItemPedido(
                variante_id=variante.id,
                cantidad=cantidad,
                precio_unitario_historico=variante.precio,
            )
        )

    subtotal = _redondear(subtotal)
    costo_envio = _redondear(calcular_costo_envio(datos.direccion_envio))

    pedido = Pedido(
        cliente_nombre=datos.cliente_nombre,
        cliente_whatsapp=datos.cliente_whatsapp,
        cliente_email=datos.cliente_email,
        direccion_envio=datos.direccion_envio.a_jsonb(),
        subtotal_productos=subtotal,
        costo_envio=costo_envio,
        monto_total=subtotal + costo_envio,
        estado_pedido=EstadoPedido.PENDIENTE_PAGO,
        clave_idempotencia=clave_idempotencia,
        items=items,
    )
    db.add(pedido)
    try:
        db.flush()
    except IntegrityError as exc:
        if restriccion_violada(exc) != RESTRICCION_IDEMPOTENCIA:
            raise
        # Otra petición con la misma clave ganó la carrera. El rollback devuelve
        # al inventario las unidades que esta transacción alcanzó a descontar.
        db.rollback()
        existente = _pedido_por_clave(db, clave_idempotencia)
        return _repetir(existente, datos, cantidades, fase="colision_unique")

    pedido_id = pedido.id
    db.commit()
    logger.info(
        "pedido_creado",
        pedido_id=str(pedido_id),
        lineas=len(cantidades),
        unidades=sum(cantidades.values()),
        monto_total=str(pedido.monto_total),
        provincia=str(datos.direccion_envio.provincia),
        con_clave_idempotencia=clave_idempotencia is not None,
    )

    return ResultadoCheckout(pedido=obtener_pedido(db, pedido_id), es_repeticion=False)


def _pedido_por_clave(db: Session, clave: str) -> Pedido | None:
    pedido_id = db.scalar(select(Pedido.id).where(Pedido.clave_idempotencia == clave))
    return obtener_pedido(db, pedido_id) if pedido_id is not None else None


def _repetir(
    existente: Pedido, datos: PedidoCreate, cantidades: Counter[uuid.UUID], *, fase: str
) -> ResultadoCheckout:
    """
    Devuelve el pedido original si la petición repetida es la misma compra.

    `fase` indica dónde se detectó la repetición (útil para leer los logs):
        previa               -> reintento después de que el original terminó
        tras_espera_de_lock  -> gemelo simultáneo que esperó los locks del original
        colision_unique      -> red de seguridad: chocó con UNIQUE al insertar
    """
    cantidades_originales = _consolidar_lineas(existente.items)
    if (
        cantidades_originales != cantidades
        or existente.cliente_whatsapp != datos.cliente_whatsapp
    ):
        logger.warning("idempotencia_clave_reutilizada", pedido_id=str(existente.id),
                       clave_prefijo=existente.clave_idempotencia[:8], fase=fase)
        raise ReglaNegocioInvalida(
            "La clave de idempotencia ya se usó para un pedido distinto; genere una clave nueva"
        )
    logger.info("idempotencia_colision", pedido_id=str(existente.id),
                clave_prefijo=existente.clave_idempotencia[:8], fase=fase)
    return ResultadoCheckout(pedido=existente, es_repeticion=True)


def _consolidar_lineas(items: list[ItemPedidoCreate] | list[ItemPedido]) -> Counter[uuid.UUID]:
    """Suma líneas repetidas de la misma variante en una sola."""
    cantidades: Counter[uuid.UUID] = Counter()
    for item in items:
        cantidades[item.variante_id] += item.cantidad
    return cantidades


def _validar_disponibilidad(
    cantidades: Counter[uuid.UUID],
    variantes: dict[uuid.UUID, VarianteProducto],
) -> None:
    """Reporta todos los problemas del carrito de una vez, no solo el primero."""
    no_disponibles = [
        str(variante_id)
        for variante_id in cantidades
        if (variante := variantes.get(variante_id)) is None
        or not variante.is_active
        or not variante.producto.is_active
    ]
    if no_disponibles:
        raise ReglaNegocioInvalida(
            "Algunas variantes no existen o ya no están a la venta",
            detalle=[{"variante_id": vid} for vid in no_disponibles],
        )

    faltantes = [
        {
            "variante_id": str(variante_id),
            "sku": variantes[variante_id].sku,
            "solicitado": cantidad,
            "disponible": variantes[variante_id].stock_disponible,
        }
        for variante_id, cantidad in cantidades.items()
        if variantes[variante_id].stock_disponible < cantidad
    ]
    if faltantes:
        logger.info("checkout_stock_insuficiente", skus=[f["sku"] for f in faltantes])
        raise StockInsuficiente("Stock insuficiente para completar el pedido", detalle=faltantes)


def _redondear(monto: Decimal) -> Decimal:
    return monto.quantize(CENTIMOS, rounding=ROUND_HALF_UP)
