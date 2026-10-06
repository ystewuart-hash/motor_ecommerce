"""Autenticación del área administrativa."""
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import OAuth2PasswordRequestForm

from core.config import get_settings
from core.rate_limit import limitar_fallos, limite_login, limiter
from core.security import CredencialesInvalidas, autenticar_admin, crear_token_acceso
from dependencies import AdminActual
from schemas.auth import SesionResponse, TokenResponse

router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={
        401: {"description": "Credenciales incorrectas"},
        429: {"description": "Demasiadas solicitudes desde esta IP o demasiados fallos para este usuario"},
    },
)
@limiter.limit(limite_login)
def login(
    request: Request,  # requerido por slowapi
    response: Response,  # slowapi agrega aquí los headers X-RateLimit-*
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
):
    """
    Intercambia usuario y contraseña (form-data OAuth2) por un token Bearer.

    Protección contra ataques de diccionario: límite por IP (RATE_LIMIT_LOGIN)
    y bloqueo del usuario tras demasiados fallos (RATE_LIMIT_FALLOS_LOGIN).
    """
    with limitar_fallos(
        "login", form.username.lower(), get_settings().rate_limit_fallos_login,
        fallos=(CredencialesInvalidas,),
    ):
        usuario = autenticar_admin(form.username, form.password)
    emitido = crear_token_acceso(usuario)
    return TokenResponse(access_token=emitido.access_token, expires_in=emitido.expira_en_segundos)


@router.get("/sesion", response_model=SesionResponse)
def sesion_actual(admin: AdminActual):
    """Devuelve a quién representa el token enviado y cuándo vence."""
    return admin
