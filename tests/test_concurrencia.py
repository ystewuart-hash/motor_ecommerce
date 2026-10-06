"""Concurrencia del checkout: SELECT ... FOR UPDATE, orden de locks y lock_timeout."""
import threading
import time
from collections import Counter
from decimal import Decimal

import psycopg
import pytest
from structlog.testing import capture_logs

from models import ItemPedido, Pedido, VarianteProducto
from schemas import PedidoUpdate
from services import checkout, pedidos
from tests.ayudantes import carrito, comprar, en_paralelo, tipo
from tests.conftest import RETARDO_SECCION_CRITICA, a_psycopg

pytestmark = pytest.mark.usefixtures("retardo_en_lock")


@pytest.mark.demostracion
def test_control_sin_bloqueo_sobrevende(fabrica, Sesion):  # noqa: N803
    """Sin FOR UPDATE, 20 compradores simultáneos venden más unidades de las que hay."""
    vid = fabrica.variante(stock=1)

    def checkout_ingenuo(_: int) -> str:
        with Sesion() as db:
            variante = db.get(VarianteProducto, vid)  # lectura SIN lock
            if variante.stock_disponible < 1:
                return "sin_stock"
            time.sleep(RETARDO_SECCION_CRITICA)
            variante.stock_disponible = variante.stock_disponible - 1  # escritura absoluta
            db.add(Pedido(
                cliente_nombre="X", cliente_whatsapp="88887777", direccion_envio={"provincia": "San José"},
                subtotal_productos=variante.precio, costo_envio=Decimal("0"), monto_total=variante.precio,
                items=[ItemPedido(variante_id=vid, cantidad=1, precio_unitario_historico=variante.precio)],
            ))
            db.commit()
            return "vendido"

    resultado = Counter(en_paralelo(20, checkout_ingenuo))
    assert resultado["vendido"] > 1, "se esperaba sobreventa (actualización perdida)"
    assert fabrica.stock(vid) == 0  # el CHECK (stock >= 0) no lo detecta


def test_ultima_unidad_se_vende_una_sola_vez(fabrica, Sesion):  # noqa: N803
    vid = fabrica.variante(stock=1)
    resultado = Counter(tipo(r) for r in en_paralelo(20, lambda _: comprar(Sesion, carrito((vid, 1)))))
    assert resultado == Counter(vendido=1, sin_stock=19)
    assert fabrica.stock(vid) == 0
    assert fabrica.vendidas(vid) == 1


def test_stock_limitado_nunca_negativo(fabrica, Sesion):  # noqa: N803
    vid = fabrica.variante(stock=10)
    resultado = Counter(tipo(r) for r in en_paralelo(40, lambda _: comprar(Sesion, carrito((vid, 1)))))
    assert resultado["vendido"] == 10
    assert fabrica.stock(vid) == 0
    assert fabrica.vendidas(vid) == 10


def test_carritos_cruzados_sin_deadlock(fabrica, Sesion):  # noqa: N803
    """Mitad compra [X, Y] y mitad [Y, X]: el ORDER BY id de los locks evita el abrazo mortal."""
    x, y = fabrica.variante(stock=1000), fabrica.variante(stock=1000)

    def tarea(i: int) -> str:
        lineas = [(x, 1), (y, 1)] if i % 2 == 0 else [(y, 1), (x, 1)]
        return comprar(Sesion, carrito(*lineas))

    resultado = Counter(tipo(r) for r in en_paralelo(40, tarea))
    assert resultado == Counter(vendido=40), resultado  # ningún error_bd:40P01
    assert (fabrica.stock(x), fabrica.stock(y)) == (960, 960)


def test_cancelaciones_concurrentes_conservan_inventario(fabrica, Sesion):  # noqa: N803
    vid = fabrica.variante(stock=20)
    previos = []
    for _ in range(10):
        with Sesion() as db:
            previos.append(checkout.crear_pedido(db, carrito((vid, 1))).pedido.id)

    def tarea(i: int) -> str:
        if i < 10:
            with Sesion() as db:
                pedidos.actualizar_pedido(db, previos[i], PedidoUpdate(estado_pedido="cancelado"))
            return "cancelado"
        return tipo(comprar(Sesion, carrito((vid, 1))))

    resultado = Counter(en_paralelo(30, tarea))
    assert resultado["cancelado"] == 10
    final = fabrica.stock(vid)
    assert final >= 0
    assert final + fabrica.vendidas(vid) == 20  # invariante: nada se crea ni se pierde


@pytest.mark.lento
def test_lock_timeout_se_rinde_y_queda_registrado(fabrica, Sesion, url_bd):  # noqa: N803
    """Con la fila retenida por otra transacción, el checkout aborta a los 5 s y emite 'lock_timeout'."""
    vid = fabrica.variante(stock=5)
    retenida, liberar = threading.Event(), threading.Event()

    def retener() -> None:
        with psycopg.connect(a_psycopg(url_bd)) as conn:
            conn.execute("SELECT 1 FROM variantes_producto WHERE id = %s FOR UPDATE", (vid,))
            retenida.set()
            liberar.wait(10)

    hilo = threading.Thread(target=retener)
    hilo.start()
    retenida.wait()
    try:
        with capture_logs() as logs:
            inicio = time.perf_counter()
            resultado = comprar(Sesion, carrito((vid, 1)))
            espera = time.perf_counter() - inicio
    finally:
        liberar.set()
        hilo.join()

    assert resultado == "error_bd:55P03"
    assert 4.5 <= espera <= 7
    assert fabrica.stock(vid) == 5  # rollback: nada se descontó

    evento = next(log for log in logs if log["event"] == "lock_timeout")
    assert evento["recurso"] == "variantes_producto"
    assert evento["log_level"] == "warning"
    assert evento["espera_ms"] >= 4500


def test_espera_por_lock_lenta_se_registra(fabrica, Sesion, config):  # noqa: N803
    """Los compradores encolados detrás de otro superan el umbral y emiten 'lock_espera_lenta'."""
    config(log_umbral_lock_lento_ms=20)
    vid = fabrica.variante(stock=100)
    with capture_logs() as logs:
        en_paralelo(5, lambda _: comprar(Sesion, carrito((vid, 1))))
    lentas = [log for log in logs if log["event"] == "lock_espera_lenta"]
    assert lentas, "al menos un comprador debió esperar más de 20 ms"
    assert all(log["recurso"] == "variantes_producto" and log["espera_ms"] >= 20 for log in lentas)
