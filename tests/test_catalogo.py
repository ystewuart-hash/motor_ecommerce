"""Catálogo: imagen principal única (índice parcial) y script de seed."""
import os
import subprocess
import sys
from collections import Counter

import psycopg
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from models import ImagenProducto
from schemas import ImagenProductoCreate
from services import catalogo
from tests.ayudantes import en_paralelo
from tests.conftest import RAIZ, a_psycopg, crear_base


def _principales(Sesion, producto_id) -> list[str]:  # noqa: N803
    with Sesion() as db:
        return list(db.scalars(select(ImagenProducto.url).where(
            ImagenProducto.producto_id == producto_id, ImagenProducto.is_principal.is_(True))))


def test_portadas_simultaneas_dejan_una_sola_principal(fabrica, Sesion):  # noqa: N803
    pid = fabrica.producto()

    def tarea(i: int) -> str:
        with Sesion() as db:
            try:
                catalogo.crear_imagen(db, ImagenProductoCreate(
                    producto_id=pid, url=f"https://cdn.example.com/{i}.webp", is_principal=True))
                return "creada"
            except IntegrityError as exc:
                return f"rechazada:{exc.orig.diag.constraint_name}"

    resultado = Counter(en_paralelo(8, tarea))
    assert set(resultado) <= {"creada", "rechazada:uq_imagenes_principal_por_producto"}
    assert len(_principales(Sesion, pid)) == 1


def test_portada_nueva_desplaza_a_la_anterior(fabrica, Sesion, db):  # noqa: N803
    pid = fabrica.producto()
    catalogo.crear_imagen(db, ImagenProductoCreate(producto_id=pid, url="https://cdn.example.com/a.webp",
                                                   is_principal=True))
    catalogo.crear_imagen(db, ImagenProductoCreate(producto_id=pid, url="https://cdn.example.com/b.webp",
                                                   is_principal=True))
    assert _principales(Sesion, pid) == ["https://cdn.example.com/b.webp"]


def test_seed_es_idempotente():
    url = crear_base("seed", alembic=True)
    entorno = {**os.environ, "DATABASE_URL": url, "PYTHONIOENCODING": "utf-8"}
    for _ in range(2):
        salida = subprocess.run([sys.executable, "-m", "scripts.seed_catalogo"], cwd=RAIZ, env=entorno,
                                capture_output=True, text=True, encoding="utf-8")
        assert salida.returncode == 0, salida.stderr

    assert "creados:  0" in salida.stdout  # la 2ª corrida no creó nada
    with psycopg.connect(a_psycopg(url)) as conn:
        conteos = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                   for t in ("categorias", "marcas", "productos", "variantes_producto", "imagenes_producto")}
        sin_portada = conn.execute(
            "SELECT count(*) FROM productos p WHERE NOT EXISTS "
            "(SELECT 1 FROM imagenes_producto i WHERE i.producto_id = p.id AND i.is_principal)"
        ).fetchone()[0]
        minimo, maximo = conn.execute("SELECT min(precio), max(precio) FROM variantes_producto").fetchone()

    assert conteos == {"categorias": 3, "marcas": 2, "productos": 5, "variantes_producto": 11,
                       "imagenes_producto": 5}
    assert sin_portada == 0
    assert (str(minimo), str(maximo)) == ("17900.00", "79900.00")


def test_conteo_de_imagenes_por_producto_no_afecta_otras(fabrica, Sesion):  # noqa: N803
    """Un producto puede tener muchas imágenes no principales."""
    pid = fabrica.producto()
    with Sesion() as db:
        for i in range(3):
            catalogo.crear_imagen(db, ImagenProductoCreate(producto_id=pid, url=f"https://cdn.example.com/g{i}.webp"))
        total = db.scalar(select(func.count()).select_from(ImagenProducto).where(ImagenProducto.producto_id == pid))
    assert total >= 3
    assert len(_principales(Sesion, pid)) <= 1
