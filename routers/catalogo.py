"""Storefront público: lectura del catálogo activo."""
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status

from dependencies import DbSession, PaginacionDep
from models import Categoria, Marca
from schemas import (
    CategoriaResponse,
    MarcaResponse,
    ProductoDetalleResponse,
    ProductoResponse,
    VarianteProductoResponse,
)
from services import catalogo

router = APIRouter(tags=["Catálogo"])


@router.get("/categorias", response_model=list[CategoriaResponse])
def listar_categorias(db: DbSession, pag: PaginacionDep):
    return catalogo.listar_por_nombre(
        db, Categoria, solo_activos=True, limit=pag.limit, offset=pag.offset
    )


@router.get("/categorias/{slug}", response_model=CategoriaResponse)
def obtener_categoria(slug: str, db: DbSession):
    return catalogo.obtener_activo_por_slug(db, Categoria, slug)


@router.get("/marcas", response_model=list[MarcaResponse])
def listar_marcas(db: DbSession, pag: PaginacionDep):
    return catalogo.listar_por_nombre(
        db, Marca, solo_activos=True, limit=pag.limit, offset=pag.offset
    )


@router.get("/marcas/{slug}", response_model=MarcaResponse)
def obtener_marca(slug: str, db: DbSession):
    return catalogo.obtener_activo_por_slug(db, Marca, slug)


@router.get("/productos", response_model=list[ProductoResponse])
def listar_productos(
    db: DbSession,
    pag: PaginacionDep,
    categoria: Annotated[str | None, Query(description="Slug de la categoría")] = None,
    marca: Annotated[str | None, Query(description="Slug de la marca")] = None,
):
    return catalogo.listar_productos(
        db,
        categoria_slug=categoria,
        marca_slug=marca,
        solo_activos=True,
        limit=pag.limit,
        offset=pag.offset,
    )


@router.get("/productos/{slug}", response_model=ProductoDetalleResponse)
def obtener_producto(slug: str, db: DbSession):
    return catalogo.obtener_producto_publico(db, slug)


@router.get("/variantes", response_model=list[VarianteProductoResponse])
def buscar_variantes(
    db: DbSession,
    pag: PaginacionDep,
    producto_id: uuid.UUID | None = None,
    atributos: Annotated[
        str | None,
        Query(description='Objeto JSON a contener, ej. {"sabor": "Chocolate"}'),
    ] = None,
):
    return catalogo.buscar_variantes(
        db,
        producto_id=producto_id,
        atributos=_parsear_atributos(atributos),
        solo_activos=True,
        limit=pag.limit,
        offset=pag.offset,
    )


def _parsear_atributos(valor: str | None) -> dict[str, Any] | None:
    if valor is None:
        return None
    try:
        atributos = json.loads(valor)
    except json.JSONDecodeError:
        atributos = None
    if not isinstance(atributos, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="'atributos' debe ser un objeto JSON",
        )
    return atributos
