"""Logging estructurado: formato JSON y contexto por request."""
import json
import logging

import structlog
from structlog.testing import capture_logs

from core.logs import configurar_logging

# capture_logs reemplaza los procesadores; se reincorpora el contexto de la request.
CON_CONTEXTO = [structlog.contextvars.merge_contextvars]


def test_formato_json_incluye_campos_estandar(capsys):
    configurar_logging(nivel="INFO", formato="json")
    try:
        structlog.get_logger("servicio.prueba").warning("evento_de_prueba", pedido_id="abc", espera_ms=12.5)
        logging.getLogger("libreria.estandar").info("mensaje de una librería")
        salida = capsys.readouterr().out
    finally:
        with capsys.disabled():  # devolver el handler al stdout real, no al de capsys
            configurar_logging(nivel="INFO", formato="json")

    lineas = [json.loads(linea) for linea in salida.strip().splitlines()]
    propio, ajeno = lineas[-2], lineas[-1]
    assert propio["event"] == "evento_de_prueba"
    assert (propio["level"], propio["logger"]) == ("warning", "servicio.prueba")
    assert propio["pedido_id"] == "abc" and propio["espera_ms"] == 12.5
    assert propio["timestamp"].endswith("Z")
    # Los logs del módulo estándar también salen como JSON.
    assert ajeno["event"] == "mensaje de una librería" and ajeno["logger"] == "libreria.estandar"


def test_request_registra_request_id_y_omite_query_string(api, fabrica):
    with capture_logs(processors=CON_CONTEXTO) as logs:
        r = api.get("/categorias?limit=5", cabeceras={"X-Request-ID": "req-prueba-12345"})

    assert r.headers["X-Request-ID"] == "req-prueba-12345"
    evento = next(log for log in logs if log["event"] == "request" and log.get("ruta") == "/categorias")
    assert evento["request_id"] == "req-prueba-12345"
    assert evento["status"] == 200 and evento["metodo"] == "GET"
    assert "limit" not in json.dumps(evento)  # la query string nunca se registra


def test_request_id_se_genera_si_no_viene(api):
    r = api.get("/categorias")
    assert len(r.headers["X-Request-ID"]) == 32


def test_eventos_de_servicio_heredan_el_request_id(api, fabrica):
    """El pedido_creado emitido dentro del servicio lleva el request_id de la request HTTP."""
    vid = fabrica.variante(stock=1)
    from tests.ayudantes import carrito

    with capture_logs(processors=CON_CONTEXTO) as logs:
        api.post("/pedidos", json.loads(carrito((vid, 1)).model_dump_json()),
                 cabeceras={"X-Request-ID": "req-checkout-777"})

    creado = next(log for log in logs if log["event"] == "pedido_creado")
    assert creado["request_id"] == "req-checkout-777"
    assert "cliente_whatsapp" not in creado and "cliente_nombre" not in creado  # sin datos personales
