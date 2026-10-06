"""
Schemas del Bloque 1: Catálogo e Inventario.

Patrón por entidad:
    <Entidad>Base      -> campos comunes editables
    <Entidad>Create    -> entrada POST (sin id ni timestamps)
    <Entidad>Update    -> entrada PATCH (todo opcional)
    <Entidad>Response  -> salida (incluye id y timestamps)
"""
import uuid
from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from schemas.base import (
    BaseSchema,
    MontoNoNegativo,
    ResponseSchema,
    Slug100,
    Slug150,
    UpdateSchema,
    Url255,
)


class _AuditoriaResponse(ResponseSchema):
    """Campos que el servidor genera en todas las tablas del catálogo."""

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# ============================================================================
# Categoría
# ============================================================================
class CategoriaBase(BaseSchema):
    nombre: str = Field(min_length=1, max_length=100, examples=["Proteínas Whey"])
    slug: Slug100 = Field(examples=["proteinas-whey"])
    is_active: bool = True


class CategoriaCreate(CategoriaBase):
    pass


class CategoriaUpdate(UpdateSchema):
    nombre: str | None = Field(default=None, min_length=1, max_length=100)
    slug: Slug100 | None = None
    is_active: bool | None = None


class CategoriaResponse(CategoriaBase, _AuditoriaResponse):
    pass


# ============================================================================
# Marca
# ============================================================================
class MarcaBase(BaseSchema):
    nombre: str = Field(min_length=1, max_length=100, examples=["Optimum Nutrition"])
    slug: Slug100 = Field(examples=["optimum-nutrition"])
    logo_url: Url255 | None = None
    is_active: bool = True


class MarcaCreate(MarcaBase):
    pass


class MarcaUpdate(UpdateSchema):
    campos_anulables = frozenset({"logo_url"})

    nombre: str | None = Field(default=None, min_length=1, max_length=100)
    slug: Slug100 | None = None
    logo_url: Url255 | None = None
    is_active: bool | None = None


class MarcaResponse(MarcaBase, _AuditoriaResponse):
    pass


# ============================================================================
# Imagen de producto
# ============================================================================
class ImagenProductoBase(BaseSchema):
    url: Url255
    variante_id: uuid.UUID | None = Field(
        default=None,
        description="NULL si es una imagen genérica del producto",
    )
    is_principal: bool = False
    orden: int = Field(default=0, ge=0)


class ImagenProductoCreate(ImagenProductoBase):
    producto_id: uuid.UUID


class ImagenProductoUpdate(UpdateSchema):
    campos_anulables = frozenset({"variante_id"})

    url: Url255 | None = None
    variante_id: uuid.UUID | None = None
    is_principal: bool | None = None
    orden: int | None = Field(default=None, ge=0)


class ImagenProductoResponse(ImagenProductoBase, _AuditoriaResponse):
    producto_id: uuid.UUID


# ============================================================================
# Variante de producto (SKU)
# ============================================================================
class VarianteProductoBase(BaseSchema):
    sku: str = Field(min_length=1, max_length=50, examples=["ON-WHEY-CHOC-5LB"])
    atributos: dict[str, Any] = Field(
        default_factory=dict,
        examples=[{"sabor": "Chocolate", "peso": "5lb"}],
    )
    precio: MontoNoNegativo
    stock_disponible: int = Field(ge=0)
    is_active: bool = True


class VarianteProductoCreate(VarianteProductoBase):
    producto_id: uuid.UUID


class VarianteProductoUpdate(UpdateSchema):
    # producto_id no es editable: una variante no se mueve entre productos.
    sku: str | None = Field(default=None, min_length=1, max_length=50)
    atributos: dict[str, Any] | None = None
    precio: MontoNoNegativo | None = None
    stock_disponible: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class AjusteStock(BaseSchema):
    """
    Ajuste relativo de inventario (entrada de mercadería, merma, devolución).

    Preferible a fijar stock_disponible por PATCH: un valor absoluto calculado
    a partir de una lectura vieja pisaría las ventas ocurridas entre medio.
    """

    delta: int = Field(description="Unidades a sumar (positivo) o restar (negativo)")
    motivo: str | None = Field(default=None, max_length=255)

    @field_validator("delta")
    @classmethod
    def _delta_distinto_de_cero(cls, valor: int) -> int:
        if valor == 0:
            raise ValueError("El ajuste debe ser distinto de cero")
        return valor


class VarianteProductoResponse(VarianteProductoBase, _AuditoriaResponse):
    producto_id: uuid.UUID


class VarianteProductoDetalleResponse(VarianteProductoResponse):
    imagenes: list[ImagenProductoResponse] = []


# ============================================================================
# Producto
# ============================================================================
class ProductoBase(BaseSchema):
    nombre: str = Field(min_length=1, max_length=150, examples=["Gold Standard 100% Whey"])
    slug: Slug150 = Field(examples=["gold-standard-100-whey"])
    descripcion_html: str | None = None
    is_active: bool = True
    categoria_id: uuid.UUID
    marca_id: uuid.UUID | None = None


class ProductoCreate(ProductoBase):
    pass


class ProductoUpdate(UpdateSchema):
    campos_anulables = frozenset({"descripcion_html", "marca_id"})

    nombre: str | None = Field(default=None, min_length=1, max_length=150)
    slug: Slug150 | None = None
    descripcion_html: str | None = None
    is_active: bool | None = None
    categoria_id: uuid.UUID | None = None
    marca_id: uuid.UUID | None = None


class ProductoResponse(ProductoBase, _AuditoriaResponse):
    """Versión ligera para listados (no dispara carga de relaciones)."""


class ProductoDetalleResponse(ProductoResponse):
    """Ficha completa: carga categoría, marca, variantes e imágenes."""

    categoria: CategoriaResponse
    marca: MarcaResponse | None = None
    variantes: list[VarianteProductoResponse] = []
    imagenes: list[ImagenProductoResponse] = []
