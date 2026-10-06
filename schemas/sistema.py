"""Schemas de observabilidad del sistema."""
from datetime import datetime
from typing import Literal

from schemas.base import ResponseSchema


class JobEstadoResponse(ResponseSchema):
    id: str
    nombre: str
    activo: bool
    intervalo: str
    proxima_ejecucion: datetime | None
    ejecuciones: int
    ultimo_inicio: datetime | None
    ultimo_fin: datetime | None
    ultimo_resultado: Literal["ok", "omitido", "error"] | None
    ultima_duracion_ms: float | None
    ultimos_cancelados: int
    total_cancelados: int
    ultimo_error: str | None


class SaludResponse(ResponseSchema):
    status: Literal["ok", "degradado"]
    base_de_datos: Literal["ok", "error"]
    scheduler: Literal["activo", "detenido", "deshabilitado"]
