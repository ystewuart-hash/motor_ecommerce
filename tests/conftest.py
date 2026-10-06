"""
Fixtures compartidas de la suite.

PostgreSQL real, nunca SQLite: FOR UPDATE, JSONB, ENUMs e índices parciales
son parte de lo que se prueba.
    - Local: pgembed levanta un servidor desechable (se borra al terminar).
    - CI: si existe TEST_POSTGRES_URI (ej. postgresql://postgres:postgres@localhost:5432/postgres)
      se usa ese servidor (el contenedor `services: postgres` de GitHub Actions).

La base principal se crea con `alembic upgrade head`, la misma vía que producción.
Todo se prepara en pytest_configure, ANTES de que pytest importe los tests, porque
database.py y core/config.py leen las variables de entorno al importarse.
"""
import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

RAIZ = Path(__file__).resolve().parents[1]
ADMIN_USER, ADMIN_PASSWORD = "admin", "clave-de-prueba-123"
JWT_SECRET = "s" * 48
RETARDO_SECCION_CRITICA = 0.05  # ensancha la ventana de carrera para que los choques sean seguros

_ESTADO: dict = {"bases": []}


# ============================================================================
# Servidor PostgreSQL y bases de datos
# ============================================================================
def _levantar_servidor() -> str:
    externo = os.getenv("TEST_POSTGRES_URI")
    if externo:
        return externo
    import pgembed

    base = Path(tempfile.mkdtemp(prefix="pg_pytest_"))
    servidor = pgembed.get_server(base / "data", cleanup_mode="delete")
    _ESTADO["pgembed"] = (servidor, base)
    return servidor.get_uri()


def _uri_bd(nombre: str) -> str:
    return _ESTADO["uri_admin"].rsplit("/", 1)[0] + f"/{nombre}"


def a_sqlalchemy(uri: str) -> str:
    return uri.replace("postgresql://", "postgresql+psycopg://", 1)


def a_psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def crear_base(prefijo: str, ddl: str | None = None, alembic: bool = False) -> str:
    """Crea una base con nombre único; la inicializa con `ddl` o con Alembic. Devuelve la URL SQLAlchemy."""
    nombre = f"{prefijo}_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(_ESTADO["uri_admin"], autocommit=True) as conn:
        conn.execute(f"CREATE DATABASE {nombre}")
    _ESTADO["bases"].append(nombre)
    url = a_sqlalchemy(_uri_bd(nombre))
    if ddl is not None:
        with psycopg.connect(_uri_bd(nombre), autocommit=True) as conn:
            conn.execute(ddl)
    if alembic:
        aplicar_alembic(url, "head")
    return url


def config_alembic(url: str):
    from alembic.config import Config

    config = Config(str(RAIZ / "alembic.ini"))
    config.attributes.update(url=url, configurar_logging=False)
    return config


def aplicar_alembic(url: str, revision: str = "head") -> None:
    from alembic import command

    command.upgrade(config_alembic(url), revision)


def pytest_configure(config: pytest.Config) -> None:
    logging.getLogger("pgembed").setLevel(logging.WARNING)  # su arranque/parada es ruido en los tests
    _ESTADO["uri_admin"] = _levantar_servidor()
    os.environ.update(
        ADMIN_USER=ADMIN_USER,
        ADMIN_PASSWORD=ADMIN_PASSWORD,
        JWT_SECRET_KEY=JWT_SECRET,
        SCHEDULER_HABILITADO="false",      # los tests controlan el scheduler explícitamente
        RATE_LIMIT_STORAGE_URI="memory://",
        LOG_FORMATO="json",
    )
    url = crear_base("ecommerce_test")
    os.environ["DATABASE_URL"] = url
    aplicar_alembic(url, "head")
    _ESTADO["url"] = url


def pytest_unconfigure(config: pytest.Config) -> None:
    if "uri_admin" not in _ESTADO:
        return
    if "pgembed" in _ESTADO:
        servidor, base = _ESTADO["pgembed"]
        servidor.cleanup()
        shutil.rmtree(base, ignore_errors=True)
        return
    # Servidor externo (CI): borrar las bases creadas.
    with psycopg.connect(_ESTADO["uri_admin"], autocommit=True) as conn:
        for nombre in _ESTADO["bases"]:
            conn.execute(f"DROP DATABASE IF EXISTS {nombre} WITH (FORCE)")


# ============================================================================
# Fixtures de base de datos
# ============================================================================
@pytest.fixture(scope="session")
def url_bd() -> str:
    return _ESTADO["url"]


@pytest.fixture(scope="session")
def uri_admin() -> str:
    return _ESTADO["uri_admin"]


@pytest.fixture(scope="session")
def motor(url_bd: str):
    from sqlalchemy import create_engine

    # Pool amplio: cada hilo de las pruebas de concurrencia necesita su conexión.
    motor = create_engine(url_bd, pool_size=60, max_overflow=0)
    yield motor
    motor.dispose()


@pytest.fixture(scope="session")
def Sesion(motor):  # noqa: N802 - nombre de "clase fábrica", como SessionLocal
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=motor, autoflush=False)


@pytest.fixture
def db(Sesion):
    with Sesion() as sesion:
        yield sesion


class Fabrica:
    """Crea datos de prueba y consulta el estado del inventario."""

    def __init__(self, Sesion) -> None:  # noqa: N803
        self.Sesion = Sesion
        self._producto_id: uuid.UUID | None = None

    def producto(self) -> uuid.UUID:
        from models import Categoria, Producto

        if self._producto_id is None:
            with self.Sesion() as db:
                prod = Producto(nombre="Whey Gold", slug="whey-gold",
                                categoria=Categoria(nombre="Proteínas", slug="proteinas"))
                db.add(prod)
                db.commit()
                self._producto_id = prod.id
        return self._producto_id

    def variante(self, stock: int, precio: str = "10000.00") -> uuid.UUID:
        from models import VarianteProducto

        with self.Sesion() as db:
            variante = VarianteProducto(producto_id=self.producto(), sku=f"SKU-{uuid.uuid4().hex[:8]}",
                                        atributos={"sabor": "Chocolate"}, precio=Decimal(precio),
                                        stock_disponible=stock)
            db.add(variante)
            db.commit()
            return variante.id

    def stock(self, variante_id: uuid.UUID) -> int:
        from sqlalchemy import select

        from models import VarianteProducto

        with self.Sesion() as db:
            return db.scalar(select(VarianteProducto.stock_disponible).where(VarianteProducto.id == variante_id))

    def vendidas(self, variante_id: uuid.UUID) -> int:
        from sqlalchemy import func, select

        from models import EstadoPedido, ItemPedido, Pedido

        with self.Sesion() as db:
            return db.scalar(
                select(func.coalesce(func.sum(ItemPedido.cantidad), 0)).join(Pedido)
                .where(ItemPedido.variante_id == variante_id, Pedido.estado_pedido != EstadoPedido.CANCELADO)
            )

    def envejecer_pedidos_de(self, variante_id: uuid.UUID, dias: int = 3) -> None:
        from sqlalchemy import text

        with self.Sesion() as db:
            db.execute(text(
                "UPDATE pedidos SET fecha_creacion = now() - make_interval(days => :d) "
                "WHERE id IN (SELECT pedido_id FROM items_pedido WHERE variante_id = :v)"
            ), {"d": dias, "v": variante_id})
            db.commit()


@pytest.fixture(scope="session")
def fabrica(Sesion) -> Fabrica:
    return Fabrica(Sesion)


@pytest.fixture
def retardo_en_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Agrega una pausa DENTRO de la sección crítica del checkout para forzar choques."""
    from services import checkout

    original = checkout.bloquear_variantes

    def con_retardo(db, ids):
        variantes = original(db, ids)
        time.sleep(RETARDO_SECCION_CRITICA)
        return variantes

    monkeypatch.setattr(checkout, "bloquear_variantes", con_retardo)


@pytest.fixture
def config(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Sobrescribe valores de configuración solo durante un test: config(rate_limit_login="3/minute")."""
    from core.config import get_settings

    def aplicar(**valores) -> None:
        for clave, valor in valores.items():
            monkeypatch.setattr(get_settings(), clave, valor)

    return aplicar


@pytest.fixture(autouse=True)
def _rate_limit_limpio() -> None:
    """Cada test empieza con los contadores de rate limiting en cero."""
    from core.rate_limit import limiter

    limiter.reset()


# ============================================================================
# Servidor HTTP real
# ============================================================================
@pytest.fixture(scope="session")
def api() -> Iterator:
    import socket

    import uvicorn

    import main
    from tests.ayudantes import ClienteHttp

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    servidor = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=puerto,
                                             log_config=None, access_log=False))
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    while not servidor.started:
        time.sleep(0.05)
    yield ClienteHttp(f"http://127.0.0.1:{puerto}")
    servidor.should_exit = True
    hilo.join(timeout=10)


@pytest.fixture(scope="session")
def token_admin(api) -> str:
    from core.rate_limit import limiter

    limiter.reset()
    respuesta = api.login(ADMIN_USER, ADMIN_PASSWORD)
    assert respuesta.status == 200, respuesta.json
    return respuesta.json["access_token"]
