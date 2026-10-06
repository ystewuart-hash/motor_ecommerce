"""Job programado de liberación de stock (APScheduler + advisory lock)."""
import time

import psycopg
import pytest
from structlog.testing import capture_logs

import main
from core import scheduler as sched
from services import checkout, pedidos
from tests.ayudantes import carrito
from tests.conftest import a_psycopg


@pytest.fixture
def pedido_vencido(fabrica, Sesion):  # noqa: N803
    """Una variante con stock 3, un pedido impago de 1 unidad envejecido 3 días."""
    vid = fabrica.variante(stock=3)
    with Sesion() as db:
        checkout.crear_pedido(db, carrito((vid, 1)))
    fabrica.envejecer_pedidos_de(vid)
    return vid


def test_job_cancela_vencidos_y_libera_stock(pedido_vencido, fabrica):
    assert fabrica.stock(pedido_vencido) == 2
    with capture_logs() as logs:
        cancelados = sched.liberar_stock_vencido(horas=48)

    assert cancelados >= 1
    assert fabrica.stock(pedido_vencido) == 3
    estado = sched.ESTADOS[sched.JOB_LIBERAR_STOCK].instantanea()
    assert estado["ultimo_resultado"] == "ok" and estado["ultimos_cancelados"] == cancelados

    eventos = [log["event"] for log in logs]
    assert "job_inicio" in eventos and "job_fin" in eventos
    fin = next(log for log in logs if log["event"] == "job_fin")
    assert fin["cancelados"] == cancelados and fin["duracion_ms"] >= 0


def test_job_se_omite_si_otra_instancia_tiene_el_lock(pedido_vencido, fabrica, url_bd):
    """Simula otro worker ejecutando el job: este debe salir sin tocar nada."""
    with psycopg.connect(a_psycopg(url_bd), autocommit=True) as otra_instancia:
        otra_instancia.execute("SELECT pg_advisory_lock(%s)", (sched.ADVISORY_LOCK_LIBERAR_STOCK,))
        with capture_logs() as logs:
            cancelados = sched.liberar_stock_vencido(horas=48)
        otra_instancia.execute("SELECT pg_advisory_unlock(%s)", (sched.ADVISORY_LOCK_LIBERAR_STOCK,))

    assert cancelados == 0
    assert fabrica.stock(pedido_vencido) == 2  # el pedido sigue vigente
    assert sched.ESTADOS[sched.JOB_LIBERAR_STOCK].instantanea()["ultimo_resultado"] == "omitido"
    assert any(log["event"] == "job_omitido" for log in logs)


def test_job_no_propaga_errores(monkeypatch):
    def falla(*args, **kwargs):
        raise RuntimeError("base caída")

    monkeypatch.setattr(pedidos, "cancelar_pedidos_vencidos", falla)
    with capture_logs() as logs:
        assert sched.liberar_stock_vencido(horas=48) == 0

    estado = sched.ESTADOS[sched.JOB_LIBERAR_STOCK].instantanea()
    assert estado["ultimo_resultado"] == "error"
    assert "base caída" in estado["ultimo_error"]
    assert any(log["event"] == "job_error" and log["log_level"] == "error" for log in logs)


def test_scheduler_y_endpoints_de_monitoreo(api, token_admin, pedido_vencido, fabrica, monkeypatch):
    scheduler = sched.crear_scheduler()
    scheduler.start()
    monkeypatch.setattr(main.app.state, "scheduler", scheduler)
    try:
        jobs = api.get("/admin/sistema/jobs", token=token_admin)
        assert jobs.status == 200
        job = jobs.json[0]
        assert job["id"] == sched.JOB_LIBERAR_STOCK and job["activo"] and job["proxima_ejecucion"]
        assert "interval[1:00:00]" in job["intervalo"]

        antes = sched.ESTADOS[sched.JOB_LIBERAR_STOCK].instantanea()["ejecuciones"]
        assert api.post(f"/admin/sistema/jobs/{sched.JOB_LIBERAR_STOCK}/ejecutar", token=token_admin).status == 202
        limite = time.monotonic() + 10
        while sched.ESTADOS[sched.JOB_LIBERAR_STOCK].instantanea()["ejecuciones"] == antes:
            assert time.monotonic() < limite, "el job no se ejecutó"
            time.sleep(0.1)
        time.sleep(0.5)
        assert fabrica.stock(pedido_vencido) == 3

        assert api.get("/salud").json["scheduler"] == "activo"
        assert api.post("/admin/sistema/jobs/inexistente/ejecutar", token=token_admin).status == 404
        assert api.get("/admin/sistema/jobs").status == 401
    finally:
        scheduler.shutdown(wait=True)
