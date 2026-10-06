"""Utilidades compartidas por los tests (no son fixtures: se importan directamente)."""
import base64
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from schemas import PedidoCreate
from services import checkout
from services.excepciones import StockInsuficiente

WHATSAPP_PRUEBA = "+50688887777"
ULTIMOS4_PRUEBA = "7777"


def carrito(*lineas: tuple[uuid.UUID, int], whatsapp: str = WHATSAPP_PRUEBA) -> PedidoCreate:
    return PedidoCreate(
        cliente_nombre="Cliente Prueba",
        cliente_whatsapp=whatsapp,
        direccion_envio={"provincia": "San José", "canton": "Escazú", "distrito": "San Rafael",
                         "senas_exactas": "Casa 1"},
        items=[{"variante_id": str(v), "cantidad": c} for v, c in lineas],
    )


def comprar(sesion: sessionmaker[Session], datos: PedidoCreate, clave: str | None = None) -> str:
    """Ejecuta un checkout y devuelve 'vendido:<id>', 'repetido:<id>', 'sin_stock' o 'error_bd:<sqlstate>'."""
    with sesion() as db:
        try:
            resultado = checkout.crear_pedido(db, datos, clave_idempotencia=clave)
        except StockInsuficiente:
            return "sin_stock"
        except OperationalError as exc:
            return f"error_bd:{getattr(exc.orig, 'sqlstate', '?')}"
        tipo = "repetido" if resultado.es_repeticion else "vendido"
        return f"{tipo}:{resultado.pedido.id}"


def tipo(resultado: str) -> str:
    return resultado.split(":")[0]


def en_paralelo[T](n: int, tarea: Callable[[int], T]) -> list[T]:
    """Ejecuta tarea(i) en n hilos que arrancan exactamente a la vez (barrera)."""
    barrera = threading.Barrier(n)

    def envoltura(i: int) -> T:
        barrera.wait()
        return tarea(i)

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(envoltura, range(n)))


def b64url(obj: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


@dataclass
class Respuesta:
    status: int
    json: Any
    headers: Any


class ClienteHttp:
    """Cliente HTTP mínimo (urllib) contra el uvicorn real levantado por la fixture `api`."""

    def __init__(self, base: str) -> None:
        self.base = base

    def solicitar(
        self,
        metodo: str,
        ruta: str,
        cuerpo: Any = None,
        *,
        token: str | None = None,
        cabeceras: dict[str, str] | None = None,
        form: dict[str, str] | None = None,
    ) -> Respuesta:
        h = dict(cabeceras or {})
        if form is not None:
            datos = urllib.parse.urlencode(form).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
            h["Content-Type"] = "application/json"
        if token:
            h["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(self.base + ruta, data=datos, headers=h, method=metodo)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                contenido = resp.read()
                return Respuesta(resp.status, json.loads(contenido) if contenido else None, resp.headers)
        except urllib.error.HTTPError as err:
            contenido = err.read()
            return Respuesta(err.code, json.loads(contenido) if contenido else None, err.headers)

    def get(self, ruta: str, **kw: Any) -> Respuesta:
        return self.solicitar("GET", ruta, **kw)

    def post(self, ruta: str, cuerpo: Any = None, **kw: Any) -> Respuesta:
        return self.solicitar("POST", ruta, cuerpo, **kw)

    def patch(self, ruta: str, cuerpo: Any = None, **kw: Any) -> Respuesta:
        return self.solicitar("PATCH", ruta, cuerpo, **kw)

    def login(self, usuario: str, password: str) -> Respuesta:
        return self.post("/auth/login", form={"username": usuario, "password": password})
