"""Idempotencia del checkout (Idempotency-Key) y sus eventos de log."""
import uuid
from collections import Counter

import pytest
from sqlalchemy import func, select
from structlog.testing import capture_logs

from models import Pedido
from services import checkout
from services.excepciones import ReglaNegocioInvalida
from tests.ayudantes import carrito, comprar, en_paralelo, tipo

pytestmark = pytest.mark.usefixtures("retardo_en_lock")


def _pedidos_con_clave(Sesion, clave: str) -> int:  # noqa: N803
    with Sesion() as db:
        return db.scalar(select(func.count()).select_from(Pedido).where(Pedido.clave_idempotencia == clave))


def test_doble_clic_simultaneo_sobre_las_ultimas_unidades(fabrica, Sesion):  # noqa: N803
    """10 peticiones gemelas a la vez por las últimas 2 unidades: 1 venta + 9 repeticiones, ningún 'sin stock'."""
    vid = fabrica.variante(stock=2)
    clave = f"clave-{uuid.uuid4()}"
    with capture_logs() as logs:
        resultados = en_paralelo(10, lambda _: comprar(Sesion, carrito((vid, 2)), clave=clave))

    assert Counter(tipo(r) for r in resultados) == Counter(vendido=1, repetido=9)
    assert len({r.split(":")[1] for r in resultados}) == 1  # todos apuntan al mismo pedido
    assert _pedidos_con_clave(Sesion, clave) == 1
    assert fabrica.stock(vid) == 0  # descontado una sola vez

    colisiones = [log for log in logs if log["event"] == "idempotencia_colision"]
    assert len(colisiones) == 9
    assert {log["fase"] for log in colisiones} == {"tras_espera_de_lock"}
    assert all(log["clave_prefijo"] == clave[:8] for log in colisiones)


def test_reintento_posterior_devuelve_el_original(fabrica, Sesion):  # noqa: N803
    vid = fabrica.variante(stock=5)
    clave = str(uuid.uuid4())
    primero = comprar(Sesion, carrito((vid, 1)), clave=clave)
    with capture_logs() as logs:
        segundo = comprar(Sesion, carrito((vid, 1)), clave=clave)

    assert tipo(primero) == "vendido" and tipo(segundo) == "repetido"
    assert primero.split(":")[1] == segundo.split(":")[1]
    assert fabrica.stock(vid) == 4
    assert [log["fase"] for log in logs if log["event"] == "idempotencia_colision"] == ["previa"]


def test_clave_reutilizada_con_otro_carrito_es_rechazada(fabrica, Sesion):  # noqa: N803
    a, b = fabrica.variante(stock=5), fabrica.variante(stock=5)
    clave = str(uuid.uuid4())
    comprar(Sesion, carrito((a, 1)), clave=clave)

    with capture_logs() as logs, pytest.raises(ReglaNegocioInvalida):
        comprar(Sesion, carrito((b, 1)), clave=clave)

    assert fabrica.stock(b) == 5
    assert any(log["event"] == "idempotencia_clave_reutilizada" and log["log_level"] == "warning" for log in logs)


def test_red_de_seguridad_unique_entre_carritos_disjuntos(fabrica, Sesion):  # noqa: N803
    """
    Misma clave, carritos SIN variantes en común: no comparten locks, así que ambas
    llegan al INSERT. UNIQUE(clave_idempotencia) frena a la segunda; su rollback
    devuelve el stock que había descontado.
    """
    a, b = fabrica.variante(stock=5), fabrica.variante(stock=5)
    clave = str(uuid.uuid4())

    def tarea(i: int) -> str:
        try:
            return comprar(Sesion, carrito((a, 1) if i == 0 else (b, 1)), clave=clave)
        except ReglaNegocioInvalida:
            return "rechazado"

    with capture_logs() as logs:
        resultado = Counter(tipo(r) for r in en_paralelo(2, tarea))

    assert resultado == Counter(vendido=1, rechazado=1)
    assert sorted([fabrica.stock(a), fabrica.stock(b)]) == [4, 5]  # el perdedor no retuvo stock
    assert _pedidos_con_clave(Sesion, clave) == 1
    assert any(log["event"] == "idempotencia_clave_reutilizada" and log["fase"] == "colision_unique"
               for log in logs)


def test_sin_clave_cada_peticion_crea_su_pedido(fabrica, db):
    vid = fabrica.variante(stock=5)
    r1 = checkout.crear_pedido(db, carrito((vid, 1)))
    r2 = checkout.crear_pedido(db, carrito((vid, 1)))
    assert r1.pedido.id != r2.pedido.id
    assert not r1.es_repeticion and not r2.es_repeticion
