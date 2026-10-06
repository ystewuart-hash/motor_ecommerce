"""
Primitivas de bloqueo pesimista (SELECT ... FOR UPDATE).

Orden global de adquisición de locks, para evitar deadlocks entre transacciones:

    pedidos  ->  pagos_sinpe  ->  variantes_producto (siempre ordenadas por id)

Toda función de servicio que bloquee más de un tipo de fila debe respetar este
orden. Las variantes se bloquean en una sola consulta con ORDER BY id: PostgreSQL
toma los locks en el orden en que devuelve las filas, así que dos checkouts con
los mismos productos en distinto orden en el carrito nunca se bloquean en cruz.

Observabilidad: cada adquisición se cronometra. Las esperas por encima de
LOG_UMBRAL_LOCK_LENTO_MS emiten "lock_espera_lenta"; los timeouts, "lock_timeout";
los deadlocks, "lock_deadlock". Son las señales de contención en producción.
"""
import time
import uuid
from collections.abc import Iterable
from typing import Any

import structlog
from sqlalchemy import Select, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, contains_eager

from core.config import get_settings
from models import PagoSinpe, Pedido, VarianteProducto
from services.excepciones import RecursoNoEncontrado

logger = structlog.get_logger(__name__)

# Tiempo máximo que una transacción espera un lock antes de rendirse. Si se agota,
# PostgreSQL lanza lock_not_available (55P03) y errores.py responde 409 "reintente".
LOCK_TIMEOUT = "5s"

SQLSTATE_LOCK_TIMEOUT = "55P03"
SQLSTATE_DEADLOCK = "40P01"


def establecer_lock_timeout(db: Session) -> None:
    """Aplica LOCK_TIMEOUT solo a la transacción en curso (SET LOCAL)."""
    db.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))


def _sqlstate(exc: OperationalError) -> str | None:
    original = exc.orig
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def _ejecutar_con_lock(db: Session, stmt: Select[Any], recurso: str, cantidad: int) -> list[Any]:
    """Ejecuta un SELECT ... FOR UPDATE midiendo cuánto tardó en obtener los locks."""
    inicio = time.perf_counter()
    try:
        filas = list(db.scalars(stmt))
    except OperationalError as exc:
        espera_ms = round((time.perf_counter() - inicio) * 1000, 1)
        sqlstate = _sqlstate(exc)
        if sqlstate == SQLSTATE_LOCK_TIMEOUT:
            logger.warning("lock_timeout", recurso=recurso, filas=cantidad,
                           espera_ms=espera_ms, lock_timeout=LOCK_TIMEOUT)
        elif sqlstate == SQLSTATE_DEADLOCK:
            logger.error("lock_deadlock", recurso=recurso, filas=cantidad, espera_ms=espera_ms)
        raise

    espera_ms = round((time.perf_counter() - inicio) * 1000, 1)
    if espera_ms >= get_settings().log_umbral_lock_lento_ms:
        logger.info("lock_espera_lenta", recurso=recurso, filas=cantidad, espera_ms=espera_ms)
    return filas


def bloquear_pedido(db: Session, pedido_id: uuid.UUID) -> Pedido:
    stmt = (
        select(Pedido)
        .where(Pedido.id == pedido_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    filas = _ejecutar_con_lock(db, stmt, "pedidos", 1)
    if not filas:
        raise RecursoNoEncontrado("Pedido no encontrado")
    return filas[0]


def bloquear_pago(db: Session, pago_id: uuid.UUID) -> PagoSinpe:
    stmt = (
        select(PagoSinpe)
        .where(PagoSinpe.id == pago_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    filas = _ejecutar_con_lock(db, stmt, "pagos_sinpe", 1)
    if not filas:
        raise RecursoNoEncontrado("Pago no encontrado")
    return filas[0]


def bloquear_variantes(
    db: Session, ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, VarianteProducto]:
    """
    Bloquea las variantes indicadas (y carga su producto) en orden de id.

    Devuelve solo las que existen; el llamador decide qué hacer con las faltantes.
    populate_existing garantiza leer el stock recién bloqueado y no un valor
    cacheado en la sesión.
    """
    ids_unicos = set(ids)
    if not ids_unicos:
        return {}

    stmt = (
        select(VarianteProducto)
        .join(VarianteProducto.producto)
        .options(contains_eager(VarianteProducto.producto))
        .where(VarianteProducto.id.in_(ids_unicos))
        .order_by(VarianteProducto.id)
        .with_for_update(of=VarianteProducto)
        .execution_options(populate_existing=True)
    )
    variantes = _ejecutar_con_lock(db, stmt, "variantes_producto", len(ids_unicos))
    return {variante.id: variante for variante in variantes}
