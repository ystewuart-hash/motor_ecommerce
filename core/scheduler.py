"""
Tareas programadas en segundo plano (APScheduler).

Job "liberar_stock_vencido": cada JOB_VENCIDOS_INTERVALO_MINUTOS cancela los
pedidos impagos con más de PEDIDOS_VENCEN_HORAS de antigüedad y devuelve su
stock al inventario, sin intervención humana.

Varios procesos, una sola ejecución:
    Con varios workers de uvicorn (o varias réplicas del contenedor) cada proceso
    arranca su propio scheduler. Para que el job no corra N veces a la vez, toma
    un *advisory lock* de PostgreSQL (pg_try_advisory_lock): el primero que lo
    obtiene trabaja y los demás registran "job_omitido" y salen. Aun sin el lock
    sería correcto (cancelar_pedidos_vencidos usa SKIP LOCKED), pero así se
    evita trabajo y ruido duplicado.

Monitoreo: GET /admin/sistema/jobs expone el estado en memoria (última
ejecución, resultado, cancelados, próxima ejecución) y cada corrida emite los
eventos estructurados job_inicio / job_fin / job_omitido / job_error.
"""
import threading
import time
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime, timedelta

import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

from core.config import get_settings
from database import SessionLocal, engine
from services import pedidos

logger = structlog.get_logger(__name__)

JOB_LIBERAR_STOCK = "liberar_stock_vencido"
# Identificador arbitrario (bigint) del advisory lock de este job. Debe ser único
# entre los jobs del sistema.
ADVISORY_LOCK_LIBERAR_STOCK = 7_302_001
# Tope de lotes por corrida: evita un bucle largo si algo inesperado ocurre.
MAX_LOTES_POR_EJECUCION = 50


@dataclass
class EstadoJob:
    """Estado observable de un job (en memoria del proceso)."""

    ejecuciones: int = 0
    ultimo_inicio: datetime | None = None
    ultimo_fin: datetime | None = None
    ultimo_resultado: str | None = None  # "ok" | "omitido" | "error"
    ultima_duracion_ms: float | None = None
    ultimos_cancelados: int = 0
    total_cancelados: int = 0
    ultimo_error: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def instantanea(self) -> dict:
        """Copia consistente de los campos públicos (sin el lock interno)."""
        with self._lock:
            return {f.name: getattr(self, f.name) for f in fields(self) if not f.name.startswith("_")}


ESTADOS: dict[str, EstadoJob] = {JOB_LIBERAR_STOCK: EstadoJob()}


def liberar_stock_vencido(horas: int | None = None) -> int:
    """
    Cuerpo del job. Devuelve cuántos pedidos canceló (0 si otra instancia lo
    estaba ejecutando). Nunca propaga excepciones: un fallo se registra y el
    scheduler reintenta en la próxima ventana.
    """
    horas = horas or get_settings().pedidos_vencen_horas
    estado = ESTADOS[JOB_LIBERAR_STOCK]
    inicio_reloj = time.perf_counter()
    with estado._lock:
        estado.ejecuciones += 1
        estado.ultimo_inicio = datetime.now(UTC)

    log = logger.bind(job=JOB_LIBERAR_STOCK, horas=horas)
    total = lotes = 0
    resultado, error = "ok", None
    try:
        # Conexión dedicada: el advisory lock de sesión vive mientras ella viva,
        # independiente de los commits que hace cada lote.
        with engine.connect() as conexion_lock:
            obtenido = conexion_lock.scalar(
                text("SELECT pg_try_advisory_lock(:clave)"), {"clave": ADVISORY_LOCK_LIBERAR_STOCK}
            )
            conexion_lock.commit()
            if not obtenido:
                resultado = "omitido"
                log.info("job_omitido", motivo="otra instancia lo está ejecutando")
                return 0
            try:
                log.info("job_inicio")
                while lotes < MAX_LOTES_POR_EJECUCION:
                    with SessionLocal() as db:
                        cancelados = pedidos.cancelar_pedidos_vencidos(db, horas=horas)
                    total += cancelados
                    lotes += 1
                    if cancelados < pedidos.TAMANO_LOTE_VENCIDOS:
                        break
            finally:
                conexion_lock.execute(
                    text("SELECT pg_advisory_unlock(:clave)"), {"clave": ADVISORY_LOCK_LIBERAR_STOCK}
                )
                conexion_lock.commit()
        return total
    except Exception as exc:  # noqa: BLE001 - el job no debe tumbar el scheduler
        resultado, error = "error", f"{type(exc).__name__}: {exc}"
        log.exception("job_error")
        return total
    finally:
        duracion_ms = round((time.perf_counter() - inicio_reloj) * 1000, 1)
        with estado._lock:
            estado.ultimo_fin = datetime.now(UTC)
            estado.ultimo_resultado = resultado
            estado.ultima_duracion_ms = duracion_ms
            estado.ultimo_error = error
            if resultado == "ok":
                estado.ultimos_cancelados = total
                estado.total_cancelados += total
        if resultado == "ok":
            log.info("job_fin", cancelados=total, lotes=lotes, duracion_ms=duracion_ms)


def crear_scheduler() -> BackgroundScheduler:
    """
    BackgroundScheduler corre los jobs en un hilo aparte del event loop de
    FastAPI: el servicio es síncrono (SQLAlchemy Session) y no debe bloquear
    las requests.
    """
    cfg = get_settings()
    scheduler = BackgroundScheduler(
        timezone="UTC",
        job_defaults={
            "coalesce": True,          # si se acumularon ventanas perdidas, ejecutar una sola vez
            "max_instances": 1,        # nunca dos ejecuciones simultáneas en el mismo proceso
            "misfire_grace_time": 300,  # tolera hasta 5 min de retraso (proceso ocupado/suspendido)
        },
    )
    scheduler.add_job(
        liberar_stock_vencido,
        trigger=IntervalTrigger(minutes=cfg.job_vencidos_intervalo_minutos, jitter=30, timezone="UTC"),
        id=JOB_LIBERAR_STOCK,
        name="Cancelar pedidos impagos vencidos y liberar su stock",
        # Primera corrida 1 minuto después del arranque: un reinicio no espera una hora entera.
        next_run_time=datetime.now(UTC) + timedelta(minutes=1),
        replace_existing=True,
    )
    return scheduler
