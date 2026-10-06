"""Administración del catálogo. Todas las rutas exigen un token JWT Bearer de administrador."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from dependencies import DbSession, PaginacionDep, verificar_admin
from models import Categoria, Marca, Producto, VarianteProducto
from schemas import (
    AjusteStock,
    CategoriaCreate,
    CategoriaResponse,
    CategoriaUpdate,
    ImagenProductoCreate,
    ImagenProductoResponse,
    ImagenProductoUpdate,
    MarcaCreate,
    MarcaResponse,
    MarcaUpdate,
    ProductoCreate,
    ProductoDetalleResponse,
    ProductoResponse,
    ProductoUpdate,
    VarianteProductoCreate,
    VarianteProductoResponse,
    VarianteProductoUpdate,
)
from services import catalogo

router = APIRouter(
    prefix="/admin",
    tags=["Admin · Catálogo"],
    dependencies=[Depends(verificar_admin)],
)

IncluirInactivos = Annotated[bool, Query(description="Incluir registros desactivados")]


# ============================================================================
# Categorías
# ============================================================================
@router.get("/categorias", response_model=list[CategoriaResponse])
def listar_categorias(db: DbSession, pag: PaginacionDep, incluir_inactivas: IncluirInactivos = True):
    return catalogo.listar_por_nombre(
        db, Categoria, solo_activos=not incluir_inactivas, limit=pag.limit, offset=pag.offset
    )


@router.post("/categorias", response_model=CategoriaResponse, status_code=status.HTTP_201_CREATED)
def crear_categoria(datos: CategoriaCreate, db: DbSession):
    return catalogo.crear(db, Categoria, datos)


@router.patch("/categorias/{categoria_id}", response_model=CategoriaResponse)
def actualizar_categoria(categoria_id: uuid.UUID, datos: CategoriaUpdate, db: DbSession):
    return catalogo.actualizar(db, Categoria, categoria_id, datos)


@router.delete("/categorias/{categoria_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar_categoria(categoria_id: uuid.UUID, db: DbSession):
    catalogo.desactivar(db, Categoria, categoria_id)


# ============================================================================
# Marcas
# ============================================================================
@router.get("/marcas", response_model=list[MarcaResponse])
def listar_marcas(db: DbSession, pag: PaginacionDep, incluir_inactivas: IncluirInactivos = True):
    return catalogo.listar_por_nombre(
        db, Marca, solo_activos=not incluir_inactivas, limit=pag.limit, offset=pag.offset
    )


@router.post("/marcas", response_model=MarcaResponse, status_code=status.HTTP_201_CREATED)
def crear_marca(datos: MarcaCreate, db: DbSession):
    return catalogo.crear(db, Marca, datos)


@router.patch("/marcas/{marca_id}", response_model=MarcaResponse)
def actualizar_marca(marca_id: uuid.UUID, datos: MarcaUpdate, db: DbSession):
    return catalogo.actualizar(db, Marca, marca_id, datos)


@router.delete("/marcas/{marca_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar_marca(marca_id: uuid.UUID, db: DbSession):
    catalogo.desactivar(db, Marca, marca_id)


# ============================================================================
# Productos
# ============================================================================
@router.get("/productos", response_model=list[ProductoResponse])
def listar_productos(
    db: DbSession,
    pag: PaginacionDep,
    categoria: str | None = None,
    marca: str | None = None,
    incluir_inactivos: IncluirInactivos = True,
):
    return catalogo.listar_productos(
        db,
        categoria_slug=categoria,
        marca_slug=marca,
        solo_activos=not incluir_inactivos,
        limit=pag.limit,
        offset=pag.offset,
    )


@router.get("/productos/{producto_id}", response_model=ProductoDetalleResponse)
def obtener_producto(producto_id: uuid.UUID, db: DbSession):
    return catalogo.obtener_producto_admin(db, producto_id)


@router.post("/productos", response_model=ProductoResponse, status_code=status.HTTP_201_CREATED)
def crear_producto(datos: ProductoCreate, db: DbSession):
    return catalogo.crear(db, Producto, datos)


@router.patch("/productos/{producto_id}", response_model=ProductoResponse)
def actualizar_producto(producto_id: uuid.UUID, datos: ProductoUpdate, db: DbSession):
    return catalogo.actualizar(db, Producto, producto_id, datos)


@router.delete("/productos/{producto_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar_producto(producto_id: uuid.UUID, db: DbSession):
    catalogo.desactivar(db, Producto, producto_id)


# ============================================================================
# Variantes
# ============================================================================
@router.post("/variantes", response_model=VarianteProductoResponse, status_code=status.HTTP_201_CREATED)
def crear_variante(datos: VarianteProductoCreate, db: DbSession):
    return catalogo.crear(db, VarianteProducto, datos)


@router.patch("/variantes/{variante_id}", response_model=VarianteProductoResponse)
def actualizar_variante(variante_id: uuid.UUID, datos: VarianteProductoUpdate, db: DbSession):
    return catalogo.actualizar_variante(db, variante_id, datos)


@router.post("/variantes/{variante_id}/ajuste-stock", response_model=VarianteProductoResponse)
def ajustar_stock(variante_id: uuid.UUID, ajuste: AjusteStock, db: DbSession):
    """Suma o resta unidades de forma atómica (recomendado frente a fijar el stock)."""
    return catalogo.ajustar_stock(db, variante_id, ajuste)


@router.delete("/variantes/{variante_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar_variante(variante_id: uuid.UUID, db: DbSession):
    catalogo.desactivar(db, VarianteProducto, variante_id)


# ============================================================================
# Imágenes
# ============================================================================
@router.post("/imagenes", response_model=ImagenProductoResponse, status_code=status.HTTP_201_CREATED)
def crear_imagen(datos: ImagenProductoCreate, db: DbSession):
    return catalogo.crear_imagen(db, datos)


@router.patch("/imagenes/{imagen_id}", response_model=ImagenProductoResponse)
def actualizar_imagen(imagen_id: uuid.UUID, datos: ImagenProductoUpdate, db: DbSession):
    return catalogo.actualizar_imagen(db, imagen_id, datos)


@router.delete("/imagenes/{imagen_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_imagen(imagen_id: uuid.UUID, db: DbSession):
    catalogo.eliminar_imagen(db, imagen_id)
