"""Schemas de autenticación."""
from datetime import datetime
from typing import Literal

from schemas.base import ResponseSchema


class TokenResponse(ResponseSchema):
    """Formato estándar OAuth2 (RFC 6749 §5.1) que entiende el botón Authorize de /docs."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class SesionResponse(ResponseSchema):
    usuario: str
    rol: str
    expira: datetime
