"""Alembic: equivalencia con init.sql, ausencia de deriva, reversibilidad y SQL legado."""
import psycopg
import pytest
from alembic import command

from tests.conftest import RAIZ, a_psycopg, aplicar_alembic, config_alembic, crear_base

DDL = (RAIZ / "init.sql").read_text(encoding="utf-8")

CONSULTAS_CATALOGO = {
    "columnas": """select table_name, column_name, data_type, character_maximum_length, numeric_precision,
                          is_nullable, column_default, is_generated, generation_expression
                   from information_schema.columns
                   where table_schema = 'public' and table_name <> 'alembic_version'""",
    "restricciones": """select conrelid::regclass::text, conname, pg_get_constraintdef(oid) from pg_constraint
                        where connamespace = 'public'::regnamespace
                          and conrelid::regclass::text <> 'alembic_version'""",
    "indices": """select tablename, indexname, indexdef from pg_indexes
                  where schemaname = 'public' and tablename <> 'alembic_version'""",
    "triggers": """select event_object_table, trigger_name, action_timing, event_manipulation, action_statement
                   from information_schema.triggers""",
    "enums": """select t.typname, string_agg(e.enumlabel, ',' order by e.enumsortorder)
                from pg_type t join pg_enum e on e.enumtypid = t.oid group by 1""",
    "funciones": "select proname, md5(prosrc) from pg_proc where pronamespace = 'public'::regnamespace",
    "comentarios": """select d.classoid::regclass::text, coalesce(c.relname, t.typname, p.proname), d.objsubid,
                             d.description
                      from pg_description d
                      left join pg_class c on d.classoid = 'pg_class'::regclass and c.oid = d.objoid
                      left join pg_type t on d.classoid = 'pg_type'::regclass and t.oid = d.objoid
                      left join pg_proc p on d.classoid = 'pg_proc'::regclass and p.oid = d.objoid
                      where coalesce(c.relnamespace, t.typnamespace, p.pronamespace) = 'public'::regnamespace""",
}


def _catalogo(url: str) -> dict[str, set]:
    with psycopg.connect(a_psycopg(url)) as conn:
        return {nombre: set(conn.execute(sql).fetchall()) for nombre, sql in CONSULTAS_CATALOGO.items()}


@pytest.fixture(scope="module")
def esquema_init_sql() -> dict[str, set]:
    return _catalogo(crear_base("via_sql", ddl=DDL))


@pytest.mark.parametrize("objeto", list(CONSULTAS_CATALOGO))
def test_alembic_produce_el_mismo_esquema_que_init_sql(url_bd, esquema_init_sql, objeto):
    via_alembic = _catalogo(url_bd)[objeto]
    assert via_alembic == esquema_init_sql[objeto], {
        "solo_alembic": via_alembic - esquema_init_sql[objeto],
        "solo_init_sql": esquema_init_sql[objeto] - via_alembic,
    }


def test_modelos_sin_deriva_respecto_de_la_base(url_bd):
    """`alembic check` falla si alguien cambió models/ sin generar la migración."""
    command.check(config_alembic(url_bd))


def test_downgrade_y_upgrade_completos():
    url = crear_base("ida_vuelta", alembic=True)
    command.downgrade(config_alembic(url), "base")
    with psycopg.connect(a_psycopg(url)) as conn:
        tablas = conn.execute("select count(*) from pg_tables where schemaname = 'public' "
                              "and tablename <> 'alembic_version'").fetchone()[0]
        tipos = conn.execute("select count(*) from pg_type where typname like 'estado_%_enum'").fetchone()[0]
    assert (tablas, tipos) == (0, 0)
    aplicar_alembic(url, "head")
    assert _catalogo(url)["indices"]


def test_sql_legado_del_sprint3_sobre_esquema_anterior():
    """alembic/legacy/001: para bases creadas con el init.sql previo al Sprint 3."""
    ddl_viejo = (
        DDL.replace("    clave_idempotencia VARCHAR(100) NULL,\n", "")
        .replace("    CONSTRAINT uq_pedidos_clave_idempotencia UNIQUE (clave_idempotencia),\n", "")
        .replace("CREATE UNIQUE INDEX uq_imagenes_principal_por_producto\n    ON imagenes_producto (producto_id)\n",
                 "CREATE INDEX idx_imagenes_principal\n    ON imagenes_producto (producto_id, orden)\n")
    )
    ddl_viejo = "\n".join(linea for linea in ddl_viejo.splitlines() if "pedidos.clave_idempotencia" not in linea)
    url = crear_base("legado", ddl=ddl_viejo)

    with psycopg.connect(a_psycopg(url), autocommit=True) as conn:
        cat = conn.execute("INSERT INTO categorias (nombre, slug) VALUES ('C', 'c') RETURNING id").fetchone()[0]
        prod = conn.execute("INSERT INTO productos (categoria_id, nombre, slug) VALUES (%s, 'P', 'p') RETURNING id",
                            (cat,)).fetchone()[0]
        for orden in (2, 0, 1):  # datos "sucios": tres portadas para el mismo producto
            conn.execute("INSERT INTO imagenes_producto (producto_id, url, is_principal, orden) "
                         "VALUES (%s, %s, TRUE, %s)", (prod, f"https://x/{orden}.webp", orden))
        conn.execute((RAIZ / "alembic" / "legacy" / "001_sprint3_idempotencia_imagen_principal.sql")
                     .read_text(encoding="utf-8"))
        portadas = conn.execute("SELECT orden FROM imagenes_producto WHERE is_principal").fetchall()

    # Tras el SQL legado, la base es equivalente a la de Alembic: basta con `alembic stamp head`.
    command.stamp(config_alembic(url), "head")
    command.check(config_alembic(url))
    assert portadas == [(0,)]
