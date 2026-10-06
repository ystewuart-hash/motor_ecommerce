"""Excepciones de dominio, independientes de HTTP (ver errores.py)."""
from typing import Any


class ErrorDominio(Exception):
    def __init__(self, mensaje: str, detalle: list[dict[str, Any]] | None = None) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.detalle = detalle


class RecursoNoEncontrado(ErrorDominio):
    """El recurso solicitado no existe (o no es visible). -> 404"""


class AccesoDenegado(ErrorDominio):
    """El solicitante no demostró tener derecho a ver el recurso. -> 403"""


class ReglaNegocioInvalida(ErrorDominio):
    """La petición es inválida según las reglas del negocio. -> 422"""


class ConflictoNegocio(ErrorDominio):
    """La petición choca con el estado actual de los datos. -> 409"""


class StockInsuficiente(ConflictoNegocio):
    """Una o más variantes no tienen existencias suficientes. -> 409"""


def restriccion_violada(exc: Exception) -> str | None:
    """Nombre de la restricción de PostgreSQL que causó un IntegrityError, si se conoce."""
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    return getattr(diag, "constraint_name", None)
