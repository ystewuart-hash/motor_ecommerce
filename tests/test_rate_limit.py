"""Rate limiting: límite por IP (slowapi) y bloqueo por intentos fallidos por recurso."""
import json

from structlog.testing import capture_logs

from tests.ayudantes import ULTIMOS4_PRUEBA, carrito
from tests.conftest import ADMIN_PASSWORD, ADMIN_USER


def _crear_pedido(api, fabrica) -> str:
    vid = fabrica.variante(stock=1)
    return api.post("/pedidos", json.loads(carrito((vid, 1)).model_dump_json())).json["id"]


# ============================================================================
# POST /auth/login
# ============================================================================
def test_login_limite_por_ip(api, config):
    config(rate_limit_login="3/minute")
    with capture_logs() as logs:
        codigos = [api.login(ADMIN_USER, "incorrecta").status for _ in range(4)]
        bloqueada = api.login(ADMIN_USER, ADMIN_PASSWORD)

    assert codigos == [401, 401, 401, 429]
    assert bloqueada.status == 429, "ni la contraseña correcta pasa mientras la IP está limitada"
    assert int(bloqueada.headers["Retry-After"]) > 0
    assert bloqueada.headers["X-RateLimit-Limit"] == "3"
    assert any(log["event"] == "rate_limit_excedido" for log in logs)


def test_login_bloquea_al_usuario_tras_fallos_aunque_cambie_de_ip(api, config):
    """El contador de fallos es por USUARIO: frena el ataque de diccionario distribuido."""
    config(rate_limit_login="1000/minute", rate_limit_fallos_login="3/hour")
    assert [api.login(ADMIN_USER, "incorrecta").status for _ in range(3)] == [401, 401, 401]

    bloqueado = api.login(ADMIN_USER, ADMIN_PASSWORD)
    assert bloqueado.status == 429
    assert "intentos fallidos" in bloqueado.json["detail"]
    assert int(bloqueado.headers["Retry-After"]) > 0
    # Otro usuario no queda afectado por los fallos de "admin".
    assert api.login("otro-usuario", "x").status == 401


def test_login_exitoso_no_consume_cupo_de_fallos(api, config):
    config(rate_limit_login="1000/minute", rate_limit_fallos_login="2/hour")
    assert all(api.login(ADMIN_USER, ADMIN_PASSWORD).status == 200 for _ in range(5))


# ============================================================================
# GET /pedidos/{id}
# ============================================================================
def test_seguimiento_bloquea_el_pedido_tras_fallos(api, fabrica, config):
    """Anti-enumeración: 3 intentos fallidos bloquean el pedido incluso para los dígitos correctos."""
    config(rate_limit_fallos_seguimiento="3/day")
    pedido_id = _crear_pedido(api, fabrica)
    otro_id = _crear_pedido(api, fabrica)

    with capture_logs() as logs:
        intentos = [api.get(f"/pedidos/{pedido_id}?ultimos4={d}").status for d in ("0000", "1111", "2222")]
        bloqueado = api.get(f"/pedidos/{pedido_id}?ultimos4={ULTIMOS4_PRUEBA}")

    assert intentos == [403, 403, 403]
    assert bloqueado.status == 429
    assert api.get(f"/pedidos/{otro_id}?ultimos4={ULTIMOS4_PRUEBA}").status == 200  # otro pedido, intacto
    assert any(log["event"] == "rate_limit_bloqueo_por_fallos" and log["ambito"] == "seguimiento"
               for log in logs)


def test_seguimiento_legitimo_no_se_bloquea(api, fabrica, config):
    """El cliente que refresca su pedido con los dígitos correctos no consume cupo de fallos."""
    config(rate_limit_fallos_seguimiento="2/day")
    pedido_id = _crear_pedido(api, fabrica)
    assert all(api.get(f"/pedidos/{pedido_id}?ultimos4={ULTIMOS4_PRUEBA}").status == 200 for _ in range(10))


def test_seguimiento_limite_por_ip(api, fabrica, config):
    config(rate_limit_seguimiento="5/minute")
    pedido_id = _crear_pedido(api, fabrica)
    codigos = [api.get(f"/pedidos/{pedido_id}?ultimos4={ULTIMOS4_PRUEBA}").status for _ in range(6)]
    assert codigos == [200] * 5 + [429]


def test_endpoints_sin_limite_no_se_ven_afectados(api, config):
    config(rate_limit_seguimiento="1/minute", rate_limit_login="1/minute")
    assert all(api.get("/categorias").status == 200 for _ in range(10))
