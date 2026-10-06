"""
Servicio de catálogo: consultas del storefront y CRUD administrativo.

El borrado de categorías, marcas, productos y variantes es lógico (is_active),
tal como lo diseña el DDL; solo las imágenes se eliminan físicamente.
"""
import uuid
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session, contains_eager, joinedload, selectinload

from models import Categoria, ImagenProducto, Marca, Producto, VarianteProducto
from schemas.base import UpdateSchema
from schemas.catalogo import (
    AjusteStock,
    ImagenProductoCreate,
    ImagenProductoUpdate,
    VarianteProductoUpdate,
)
from services.bloqueos import bloquear_variantes, establecer_lock_timeout
from services.excepciones import ConflictoNegocio, RecursoNoEncontrado, ReglaNegocioInvalida

MENSAJE_NO_ENCONTRADO: dict[type, str] = {
    Categoria: "Categoría no encontrada",
    Marca: "Marca no encontrada",
    Producto: "Producto no encontrado",
    VarianteProducto: "Variante no encontrada",
    ImagenProducto: "Imagen no encontrada",
}


# ============================================================================
# Operaciones genéricas
# ============================================================================
def obtener_por_id[M](db: Session, modelo: type[M], id_: uuid.UUID) -> M:
    obj = db.get(modelo, id_)
    if obj is None:
        raise RecursoNoEncontrado(MENSAJE_NO_ENCONTRADO[modelo])
    return obj


def obtener_activo_por_slug[M](db: Session, modelo: type[M], slug: str) -> M:
    stmt = select(modelo).where(modelo.slug == slug, modelo.is_active.is_(True))
    obj = db.scalars(stmt).one_or_none()
    if obj is None:
        raise RecursoNoEncontrado(MENSAJE_NO_ENCONTRADO[modelo])
    return obj


def listar_por_nombre[M](
    db: Session, modelo: type[M], *, solo_activos: bool, limit: int, offset: int
) -> list[M]:
    stmt = select(modelo).order_by(modelo.nombre).limit(limit).offset(offset)
    if solo_activos:
        stmt = stmt.where(modelo.is_active.is_(True))
    return list(db.scalars(stmt))


def crear[M](db: Session, modelo: type[M], datos: BaseModel) -> M:
    obj = modelo(**datos.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def actualizar[M](db: Session, modelo: type[M], id_: uuid.UUID, datos: UpdateSchema) -> M:
    obj = obtener_por_id(db, modelo, id_)
    _aplicar_cambios(obj, datos.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(obj)
    return obj


def desactivar[M](db: Session, modelo: type[M], id_: uuid.UUID) -> None:
    """Borrado lógico: oculta el registro sin romper la integridad referencial."""
    obj = obtener_por_id(db, modelo, id_)
    obj.is_active = False
    db.commit()


def _aplicar_cambios(obj: Any, cambios: dict[str, Any]) -> None:
    for campo, valor in cambios.items():
        setattr(obj, campo, valor)


# ============================================================================
# Productos
# ============================================================================
def listar_productos(
    db: Session,
    *,
    categoria_slug: str | None,
    marca_slug: str | None,
    solo_activos: bool,
    limit: int,
    offset: int,
) -> list[Producto]:
    stmt = (
        select(Producto)
        .join(Producto.categoria)
        .order_by(Producto.nombre)
        .limit(limit)
        .offset(offset)
    )
    if solo_activos:
        stmt = stmt.where(Producto.is_active.is_(True), Categoria.is_active.is_(True))
    if categoria_slug:
        stmt = stmt.where(Categoria.slug == categoria_slug)
    if marca_slug:
        stmt = stmt.join(Producto.marca).where(Marca.slug == marca_slug)
    return list(db.scalars(stmt))


def obtener_producto_publico(db: Session, slug: str) -> Producto:
    """Ficha de tienda: producto y categoría activos, solo variantes activas."""
    stmt = (
        select(Producto)
        .join(Producto.categoria)
        .where(
            Producto.slug == slug,
            Producto.is_active.is_(True),
            Categoria.is_active.is_(True),
        )
        .options(
            contains_eager(Producto.categoria),
            joinedload(Producto.marca),
            selectinload(Producto.variantes.and_(VarianteProducto.is_active.is_(True))),
            selectinload(Producto.imagenes),
        )
    )
    producto = db.scalars(stmt).unique().one_or_none()
    if producto is None:
        raise RecursoNoEncontrado("Producto no encontrado")
    return producto


def obtener_producto_admin(db: Session, producto_id: uuid.UUID) -> Producto:
    producto = db.get(
        Producto,
        producto_id,
        options=[
            joinedload(Producto.categoria),
            joinedload(Producto.marca),
            selectinload(Producto.variantes),
            selectinload(Producto.imagenes),
        ],
    )
    if producto is None:
        raise RecursoNoEncontrado("Producto no encontrado")
    return producto


# ============================================================================
# Variantes
# ============================================================================
def buscar_variantes(
    db: Session,
    *,
    producto_id: uuid.UUID | None,
    atributos: dict[str, Any] | None,
    solo_activos: bool,
    limit: int,
    offset: int,
) -> list[VarianteProducto]:
    stmt = (
        select(VarianteProducto)
        .join(VarianteProducto.producto)
        .order_by(VarianteProducto.sku)
        .limit(limit)
        .offset(offset)
    )
    if solo_activos:
        stmt = stmt.where(VarianteProducto.is_active.is_(True), Producto.is_active.is_(True))
    if producto_id:
        stmt = stmt.where(VarianteProducto.producto_id == producto_id)
    if atributos:
        # atributos @> '{...}': aprovecha idx_variantes_atributos_gin (jsonb_path_ops).
        stmt = stmt.where(VarianteProducto.atributos.contains(atributos))
    return list(db.scalars(stmt))


def actualizar_variante(
    db: Session, variante_id: uuid.UUID, datos: VarianteProductoUpdate
) -> VarianteProducto:
    # Bloquea la fila: un PATCH de precio/stock no debe pisar un checkout en curso.
    establecer_lock_timeout(db)
    variante = _bloquear_variante(db, variante_id)
    _aplicar_cambios(variante, datos.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(variante)
    return variante


def ajustar_stock(db: Session, variante_id: uuid.UUID, ajuste: AjusteStock) -> VarianteProducto:
    establecer_lock_timeout(db)
    variante = _bloquear_variante(db, variante_id)
    nuevo_stock = variante.stock_disponible + ajuste.delta
    if nuevo_stock < 0:
        raise ConflictoNegocio(
            f"El ajuste dejaría el stock en negativo (disponible: {variante.stock_disponible})"
        )
    variante.stock_disponible = nuevo_stock
    db.commit()
    db.refresh(variante)
    return variante


def _bloquear_variante(db: Session, variante_id: uuid.UUID) -> VarianteProducto:
    variante = bloquear_variantes(db, [variante_id]).get(variante_id)
    if variante is None:
        raise RecursoNoEncontrado("Variante no encontrada")
    return variante


# ============================================================================
# Imágenes
# ============================================================================
def crear_imagen(db: Session, datos: ImagenProductoCreate) -> ImagenProducto:
    obtener_por_id(db, Producto, datos.producto_id)
    _validar_variante_del_producto(db, datos.producto_id, datos.variante_id)

    imagen = ImagenProducto(**datos.model_dump())
    if imagen.is_principal:
        _quitar_principal(db, datos.producto_id)
    db.add(imagen)
    db.commit()
    db.refresh(imagen)
    return imagen


def actualizar_imagen(
    db: Session, imagen_id: uuid.UUID, datos: ImagenProductoUpdate
) -> ImagenProducto:
    imagen = obtener_por_id(db, ImagenProducto, imagen_id)
    cambios = datos.model_dump(exclude_unset=True)

    if cambios.get("variante_id") is not None:
        _validar_variante_del_producto(db, imagen.producto_id, cambios["variante_id"])
    if cambios.get("is_principal"):
        _quitar_principal(db, imagen.producto_id, excepto=imagen.id)

    _aplicar_cambios(imagen, cambios)
    db.commit()
    db.refresh(imagen)
    return imagen


def eliminar_imagen(db: Session, imagen_id: uuid.UUID) -> None:
    imagen = obtener_por_id(db, ImagenProducto, imagen_id)
    db.delete(imagen)
    db.commit()


def _validar_variante_del_producto(
    db: Session, producto_id: uuid.UUID, variante_id: uuid.UUID | None
) -> None:
    if variante_id is None:
        return
    variante = db.get(VarianteProducto, variante_id)
    if variante is None or variante.producto_id != producto_id:
        raise ReglaNegocioInvalida("La variante indicada no pertenece al producto")


def _quitar_principal(
    db: Session, producto_id: uuid.UUID, excepto: uuid.UUID | None = None
) -> None:
    """Un producto tiene una sola imagen principal."""
    stmt = (
        update(ImagenProducto)
        .where(
            ImagenProducto.producto_id == producto_id,
            ImagenProducto.is_principal.is_(True),
        )
        .values(is_principal=False)
    )
    if excepto is not None:
        stmt = stmt.where(ImagenProducto.id != excepto)
    db.execute(stmt)
