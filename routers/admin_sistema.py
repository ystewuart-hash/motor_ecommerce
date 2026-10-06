"""Observabilidad y operación de tareas programadas. Exige un token JWT Bearer de administrador."""
from datetime import UTC, datetime

from apscheduler.schedulers.base import BaseScheduler
from fastapi import APIRouter, Depends, HTTPException, Request, status

from core.scheduler import ESTADOS
from dependencies import verificar_admin
from schemas.sistema import JobEstadoResponse

router = APIRouter(
    prefix="/admin/sistema",
    tags=["Admin · Sistema"],
    dependencies=[Depends(verificar_admin)],
)


def _scheduler(request: Request) -> BaseScheduler:
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "El scheduler está deshabilitado")
    return scheduler


@router.get("/jobs", response_model=list[JobEstadoResponse])
def listar_jobs(request: Request):
    """Estado de cada job: próxima ejecución y resultado de la última (de ESTE proceso)."""
    scheduler = _scheduler(request)
    return [
        JobEstadoResponse(
            id=job.id,
            nombre=job.name,
            activo=job.next_run_time is not None,
            intervalo=str(job.trigger),
            proxima_ejecucion=job.next_run_time,
            **ESTADOS[job.id].instantanea(),
        )
        for job in scheduler.get_jobs()
    ]


@router.post("/jobs/{job_id}/ejecutar", status_code=status.HTTP_202_ACCEPTED)
def ejecutar_job_ahora(job_id: str, request: Request) -> dict[str, str]:
    """Adelanta la próxima ejecución a "ahora" (corre en segundo plano; ver GET /jobs)."""
    scheduler = _scheduler(request)
    if scheduler.get_job(job_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job no encontrado")
    scheduler.modify_job(job_id, next_run_time=datetime.now(UTC))
    return {"detail": f"Job '{job_id}' programado para ejecutarse ahora"}
