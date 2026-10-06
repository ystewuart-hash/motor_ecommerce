"""
Entorno de ejecución de Alembic, conectado a la Base declarativa del proyecto.

- La URL sale de `config.attributes["url"]` (uso programático: tests, scripts)
  o, si no, de la variable DATABASE_URL (.env o entorno).
- `target_metadata = Base.metadata` habilita `alembic revision --autogenerate`
  y `alembic check`: Alembic compara los modelos de models/ con la base real.
"""
import os
import warnings
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool

config = context.config

# Solo la CLI configura logging desde alembic.ini; cuando se invoca desde código
# (tests, arranque de la app) se respeta el logging estructurado ya configurado.
if config.config_file_name is not None and config.attributes.get("configurar_logging", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

load_dotenv()
URL = config.attributes.get("url") or os.getenv("DATABASE_URL")
if not URL:
    raise RuntimeError("Alembic necesita DATABASE_URL (en .env o en el entorno)")
os.environ.setdefault("DATABASE_URL", URL)  # database.py la exige al importarse

# Importar los modelos registra todas las tablas en Base.metadata.
import models  # noqa: E402, F401
from database import Base  # noqa: E402

target_metadata = Base.metadata

# items_pedido.subtotal_linea es GENERATED ALWAYS: no tiene DEFAULT que comparar.
warnings.filterwarnings("ignore", message="Computed default on .* cannot be modified")

OPCIONES_COMPARACION = {
    "compare_type": True,             # detecta cambios de tipo (VARCHAR(50) -> VARCHAR(100))
    "compare_server_default": True,   # detecta cambios de DEFAULT
    # Los COMMENT ON de documentación viven en las migraciones (ver 0001), no en
    # los modelos: sin esta exclusión, el autogenerate propondría borrarlos todos.
    "autogenerate_plugins": ["alembic.autogenerate.*", "~alembic.autogenerate.comments"],
}


def run_migrations_offline() -> None:
    """Modo offline (`alembic upgrade head --sql`): genera el SQL sin conectarse."""
    context.configure(
        url=URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **OPCIONES_COMPARACION,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Modo online: se conecta y aplica las migraciones en una transacción."""
    motor = create_engine(URL, poolclass=pool.NullPool)
    with motor.connect() as conexion:
        context.configure(
            connection=conexion,
            target_metadata=target_metadata,
            # PostgreSQL soporta DDL transaccional: si una migración falla a
            # mitad de camino, se revierte completa y el esquema queda intacto.
            transaction_per_migration=True,
            **OPCIONES_COMPARACION,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
