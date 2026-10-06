"""Dependencias compartidas por los routers."""
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query, Security
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from core.security import SesionAdmin, TokenInvalido, decodificar_token
from database import get_db

DbSession = Annotated[Session, Depends(get_db)]


# ----------------------------------------------------------------------------
# Autenticación administrativa (JWT Bearer)
# ----------------------------------------------------------------------------
# tokenUrl habilita el botón "Authorize" de /docs con el flujo usuario/contraseña.
# auto_error=False: la ausencia de token la reporta verificar_admin con un
# mensaje propio en vez del genérico de FastAPI.
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def verificar_admin(token: Annotated[str | None, Security(_oauth2_scheme)]) -> SesionAdmin:
    """
    Exige `Authorization: Bearer <jwt>` válido con rol admin.

    Los errores (TokenInvalido -> 401, ConfiguracionIncompleta -> 503) los
    traduce errores.py, igual que los de los servicios.
    """
    if token is None:
        raise TokenInvalido("Se requiere autenticación (Authorization: Bearer <token>)")
    return decodificar_token(token)


AdminActual = Annotated[SesionAdmin, Depends(verificar_admin)]


# ----------------------------------------------------------------------------
# Paginación
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Paginacion:
    limit: int
    offset: int


def _paginacion(
    limit: Annotated[int, Query(ge=1, le=100, description="Máximo de resultados")] = 50,
    offset: Annotated[int, Query(ge=0, description="Resultados a omitir")] = 0,
) -> Paginacion:
    return Paginacion(limit=limit, offset=offset)


PaginacionDep = Annotated[Paginacion, Depends(_paginacion)]
