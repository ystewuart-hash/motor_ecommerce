"""
Genera una migración de Alembic por autogenerate sin tocar ninguna base real.

Pasos:
    1. Levanta un PostgreSQL desechable (pgembed).
    2. Aplica las migraciones existentes (`alembic upgrade head`).
    3. Ejecuta `alembic revision --autogenerate`: Alembic compara ese esquema con
       los modelos de models/ y escribe en alembic/versions/ solo la diferencia.
    4. Destruye el servidor temporal.

La primera migración (0001_esquema_inicial) se creó así, partiendo de una base vacía.

Uso:
    venv/Scripts/python.exe -m scripts.generar_migracion "agrega tabla usuarios"
    venv/Scripts/python.exe -m scripts.generar_migracion "agrega tabla usuarios" --rev-id 0002

SIEMPRE revisa el archivo generado: el autogenerate no detecta ENUMs nuevos con
create_type=False, funciones, triggers, ni renombres (los ve como drop + add).
"""
import argparse
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mensaje", help="Descripción corta de la migración")
    parser.add_argument("--rev-id", help="Id de revisión explícito (ej. 0002)")
    args = parser.parse_args()

    import pgembed
    import psycopg
    from alembic import command
    from alembic.config import Config

    base = Path(tempfile.mkdtemp(prefix="pg_migracion_"))
    servidor = pgembed.get_server(base / "data", cleanup_mode="delete")
    try:
        uri_admin = servidor.get_uri()
        with psycopg.connect(uri_admin, autocommit=True) as conn:
            conn.execute("CREATE DATABASE autogenerate")
        url = uri_admin.rsplit("/", 1)[0].replace("postgresql://", "postgresql+psycopg://", 1) + "/autogenerate"

        config = Config(str(RAIZ / "alembic.ini"))
        config.attributes["url"] = url
        print("1/2 Aplicando migraciones existentes sobre la base temporal...")
        command.upgrade(config, "head")
        print("2/2 Comparando con los modelos (autogenerate)...")
        command.revision(config, message=args.mensaje, autogenerate=True, rev_id=args.rev_id)
        print("Listo. Revisa el archivo nuevo en alembic/versions/ antes de commitearlo.")
    finally:
        servidor.cleanup()
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    main()
