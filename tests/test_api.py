"""API de punta a punta contra un uvicorn real: JWT, checkout, seguimiento, pagos y administración."""
import json
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from tests.ayudantes import ULTIMOS4_PRUEBA, b64url, carrito, en_paralelo
from tests.conftest import ADMIN_PASSWORD, ADMIN_USER, JWT_SECRET


def _cuerpo(*lineas, provincia: str = "San José") -> dict:
    cuerpo = json.loads(carrito(*lineas).model_dump_json())
    cuerpo["direccion_envio"]["provincia"] = provincia
    return cuerpo


# ============================================================================
# Autenticación JWT
# ============================================================================
def test_login_con_contrasena_incorrecta(api):
    assert api.login(ADMIN_USER, "incorrecta").status == 401


def test_login_con_usuario_inexistente(api):
    assert api.login("otro", ADMIN_PASSWORD).status == 401


def test_login_correcto_y_sesion(api):
    r = api.login(ADMIN_USER, ADMIN_PASSWORD)
    assert r.status == 200 and r.json["token_type"] == "bearer" and r.json["expires_in"] == 1800
    sesion = api.get("/auth/sesion", token=r.json["access_token"])
    assert sesion.status == 200
    assert (sesion.json["usuario"], sesion.json["rol"]) == (ADMIN_USER, "admin")


def test_admin_sin_token(api):
    r = api.get("/admin/pedidos")
    assert r.status == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"


def _tokens_maliciosos(token_valido: str) -> dict[str, str]:
    cabecera, cuerpo, firma = token_valido.split(".")
    ahora = datetime.now(UTC)
    claims = {"sub": ADMIN_USER, "rol": "admin", "iss": "motor-ecommerce", "iat": ahora, "jti": "x"}
    en_5_min = ahora + timedelta(minutes=5)
    return {
        "firma_alterada": f"{cabecera}.{cuerpo}.{firma[:10]}{'A' if firma[10] != 'A' else 'B'}{firma[11:]}",
        "otra_clave": jwt.encode({**claims, "exp": en_5_min}, "o" * 48, algorithm="HS256"),
        "vencido": jwt.encode({**claims, "iat": ahora - timedelta(hours=2), "exp": ahora - timedelta(hours=1)},
                              JWT_SECRET, algorithm="HS256"),
        "alg_none": f"{b64url({'alg': 'none', 'typ': 'JWT'})}.{b64url({**claims, 'iat': 1, 'exp': 9999999999})}.",
        "rol_cliente": jwt.encode({**claims, "rol": "cliente", "exp": en_5_min}, JWT_SECRET, algorithm="HS256"),
    }


@pytest.mark.parametrize("caso", ["firma_alterada", "otra_clave", "vencido", "alg_none", "rol_cliente"])
def test_tokens_maliciosos_son_rechazados(api, token_admin, caso):
    r = api.get("/admin/pedidos", token=_tokens_maliciosos(token_admin)[caso])
    assert r.status == 401, r.json


# ============================================================================
# Checkout, idempotencia y seguimiento
# ============================================================================
@pytest.mark.usefixtures("retardo_en_lock")
def test_checkout_concurrente_por_http(api, fabrica):
    vid = fabrica.variante(stock=3, precio="12500.00")
    respuestas = en_paralelo(15, lambda _: api.post("/pedidos", _cuerpo((vid, 1), provincia="limon")))
    assert Counter(r.status for r in respuestas) == Counter({201: 3, 409: 12})

    rechazo = next(r for r in respuestas if r.status == 409)
    assert rechazo.json["errores"][0]["disponible"] == 0

    pedido = next(r for r in respuestas if r.status == 201).json
    assert (pedido["subtotal_productos"], pedido["costo_envio"], pedido["monto_total"]) == \
        ("12500.00", "4000.00", "16500.00")
    assert pedido["direccion_envio"]["provincia"] == "Limón"


def test_cliente_no_puede_enviar_montos(api, fabrica):
    vid = fabrica.variante(stock=3)
    assert api.post("/pedidos", {**_cuerpo((vid, 1)), "monto_total": "1.00"}).status == 422


@pytest.mark.usefixtures("retardo_en_lock")
def test_idempotency_key_por_http(api, fabrica):
    vid = fabrica.variante(stock=1)
    cabeceras = {"Idempotency-Key": str(uuid.uuid4())}
    respuestas = en_paralelo(5, lambda _: api.post("/pedidos", _cuerpo((vid, 1)), cabeceras=cabeceras))

    assert {r.status for r in respuestas} == {201}
    assert len({r.json["id"] for r in respuestas}) == 1
    assert sum(r.headers.get("Idempotent-Replayed") == "true" for r in respuestas) == 4
    assert fabrica.stock(vid) == 0


def test_idempotency_key_invalida(api, fabrica):
    vid = fabrica.variante(stock=1)
    assert api.post("/pedidos", _cuerpo((vid, 1)), cabeceras={"Idempotency-Key": "corta"}).status == 422


def test_seguimiento_exige_ultimos4(api, fabrica):
    vid = fabrica.variante(stock=1)
    pedido_id = api.post("/pedidos", _cuerpo((vid, 1))).json["id"]
    assert api.get(f"/pedidos/{pedido_id}").status == 422
    assert api.get(f"/pedidos/{pedido_id}?ultimos4=1234").status == 403
    assert api.get(f"/pedidos/{pedido_id}?ultimos4={ULTIMOS4_PRUEBA}").status == 200


# ============================================================================
# Pagos y administración
# ============================================================================
def test_flujo_de_pago_y_conciliacion(api, fabrica, token_admin):
    vid = fabrica.variante(stock=2, precio="12500.00")
    p1 = api.post("/pedidos", _cuerpo((vid, 1))).json
    p2 = api.post("/pedidos", _cuerpo((vid, 1))).json
    pago = {"pedido_id": p1["id"], "numero_referencia": f"SINPE-{uuid.uuid4().hex[:10]}",
            "telefono_emisor": "88887777", "monto_transferido": p1["monto_total"],
            "comprobante_url": "https://cdn.example.com/c1.jpg"}

    creado = api.post("/pagos", pago)
    assert creado.status == 201
    duplicado = api.post("/pagos", {**pago, "pedido_id": p2["id"]})
    assert duplicado.status == 409 and "SINPE" in duplicado.json["detail"]

    assert api.patch(f"/admin/pagos/{creado.json['id']}", {"estado_validacion": "aprobado"},
                     token=token_admin).status == 200
    detalle = api.get(f"/pedidos/{p1['id']}?ultimos4={ULTIMOS4_PRUEBA}").json
    assert detalle["estado_pedido"] == "en_preparacion"

    invalida = api.patch(f"/admin/pedidos/{p1['id']}", {"estado_pedido": "entregado"}, token=token_admin)
    assert invalida.status == 409


def test_cancelar_vencidos_por_http(api, fabrica, token_admin):
    vid = fabrica.variante(stock=2)
    api.post("/pedidos", _cuerpo((vid, 1)))
    api.post("/pedidos", _cuerpo((vid, 1)))
    assert fabrica.stock(vid) == 0
    fabrica.envejecer_pedidos_de(vid)

    r = api.post("/admin/pedidos/cancelar-vencidos?horas=48", token=token_admin)
    assert r.status == 200 and r.json["cancelados"] >= 2
    assert fabrica.stock(vid) == 2


def test_crear_portada_por_http(api, fabrica, token_admin):
    img = {"producto_id": str(fabrica.producto()), "url": f"https://cdn.example.com/{uuid.uuid4().hex}.webp",
           "is_principal": True}
    assert api.post("/admin/imagenes", img, token=token_admin).status == 201


def test_salud(api):
    r = api.get("/salud")
    assert r.status == 200
    assert r.json == {"status": "ok", "base_de_datos": "ok", "scheduler": "deshabilitado"}
