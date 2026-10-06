"""
Bloque 1: Catálogo e Inventario.

Tablas: categorias, marcas, productos, variantes_producto, imagenes_producto.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from models.transacciones import ItemPedido

SLUG_REGEX = "^[a-z0-9]+(?:-[a-z0-9]+)*$"


# ----------------------------------------------------------------------------
# categorias
# ----------------------------------------------------------------------------
class Categoria(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Clasificación taxonómica de primer nivel del catálogo."""

    __tablename__ = "categorias"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_categorias_slug"),
        CheckConstraint("char_length(trim(nombre)) > 0", name="chk_categorias_nombre_not_empty"),
        CheckConstraint(f"slug ~ '{SLUG_REGEX}'", name="chk_categorias_slug_format"),
        Index("idx_categorias_slug_active", "slug", postgresql_where=text("is_active = TRUE")),
    )

    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))

    # ON DELETE RESTRICT: passive_deletes="all" evita que el ORM intente poner
    # categoria_id = NULL en los hijos y deja que PostgreSQL bloquee el borrado.
    productos: Mapped[list[Producto]] = relationship(
        back_populates="categoria",
        passive_deletes="all",
    )

    def __repr__(self) -> str:
        return f"<Categoria slug={self.slug!r}>"


# ----------------------------------------------------------------------------
# marcas
# ----------------------------------------------------------------------------
class Marca(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Fabricantes, marcas comerciales o proveedores."""

    __tablename__ = "marcas"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_marcas_slug"),
        CheckConstraint("char_length(trim(nombre)) > 0", name="chk_marcas_nombre_not_empty"),
        CheckConstraint(f"slug ~ '{SLUG_REGEX}'", name="chk_marcas_slug_format"),
        Index("idx_marcas_slug_active", "slug", postgresql_where=text("is_active = TRUE")),
    )

    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))

    # ON DELETE SET NULL lo resuelve la BD; passive_deletes evita cargar los hijos.
    productos: Mapped[list[Producto]] = relationship(
        back_populates="marca",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Marca slug={self.slug!r}>"


# ----------------------------------------------------------------------------
# productos
# ----------------------------------------------------------------------------
class Producto(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Ficha matriz del catálogo; agrupa variantes comercializables (SKUs)."""

    __tablename__ = "productos"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_productos_slug"),
        CheckConstraint("char_length(trim(nombre)) > 0", name="chk_productos_nombre_not_empty"),
        CheckConstraint(f"slug ~ '{SLUG_REGEX}'", name="chk_productos_slug_format"),
        Index("idx_productos_slug_active", "slug", postgresql_where=text("is_active = TRUE")),
        Index("idx_productos_categoria_id", "categoria_id"),
        Index("idx_productos_marca_id", "marca_id"),
    )

    categoria_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "categorias.id",
            name="fk_productos_categoria",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        nullable=False,
    )
    marca_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "marcas.id",
            name="fk_productos_marca",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        nullable=True,
    )
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(150), nullable=False)
    descripcion_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))

    categoria: Mapped[Categoria] = relationship(back_populates="productos")
    marca: Mapped[Marca | None] = relationship(back_populates="productos")

    # ON DELETE CASCADE en BD + delete-orphan en ORM: las variantes e imágenes
    # viven y mueren con su producto.
    variantes: Mapped[list[VarianteProducto]] = relationship(
        back_populates="producto",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    imagenes: Mapped[list[ImagenProducto]] = relationship(
        back_populates="producto",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ImagenProducto.orden",
    )

    def __repr__(self) -> str:
        return f"<Producto slug={self.slug!r}>"


# ----------------------------------------------------------------------------
# variantes_producto
# ----------------------------------------------------------------------------
class VarianteProducto(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Unidad mínima de inventario vendible (SKU) con atributos dinámicos JSONB."""

    __tablename__ = "variantes_producto"
    __table_args__ = (
        UniqueConstraint("sku", name="uq_variantes_sku"),
        CheckConstraint("precio >= 0", name="chk_variantes_precio_no_negativo"),
        CheckConstraint("stock_disponible >= 0", name="chk_variantes_stock_no_negativo"),
        CheckConstraint("jsonb_typeof(atributos) = 'object'", name="chk_variantes_atributos_is_object"),
        Index("idx_variantes_sku_active", "sku", postgresql_where=text("is_active = TRUE")),
        Index("idx_variantes_producto_id", "producto_id"),
        Index(
            "idx_variantes_atributos_gin",
            "atributos",
            postgresql_using="gin",
            postgresql_ops={"atributos": "jsonb_path_ops"},
        ),
    )

    producto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "productos.id",
            name="fk_variantes_producto",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=False,
    )
    sku: Mapped[str] = mapped_column(String(50), nullable=False)
    # MutableDict detecta cambios in-place (variante.atributos["sabor"] = "...").
    atributos: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    precio: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    stock_disponible: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))

    producto: Mapped[Producto] = relationship(back_populates="variantes")

    # Sin delete-orphan: una imagen puede pertenecer solo al producto (variante_id NULL),
    # así que no debe considerarse huérfana por no tener variante.
    imagenes: Mapped[list[ImagenProducto]] = relationship(
        back_populates="variante",
        passive_deletes=True,
        order_by="ImagenProducto.orden",
    )

    # ON DELETE RESTRICT: impide borrar variantes ya vendidas.
    items_pedido: Mapped[list[ItemPedido]] = relationship(
        back_populates="variante",
        passive_deletes="all",
    )

    def __repr__(self) -> str:
        return f"<VarianteProducto sku={self.sku!r}>"


# ----------------------------------------------------------------------------
# imagenes_producto
# ----------------------------------------------------------------------------
class ImagenProducto(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Galería del producto o de una variante específica."""

    __tablename__ = "imagenes_producto"
    __table_args__ = (
        CheckConstraint("orden >= 0", name="chk_imagenes_orden_no_negativo"),
        Index("idx_imagenes_producto_id", "producto_id"),
        Index("idx_imagenes_variante_id", "variante_id"),
        # Garantía a nivel de motor: como máximo una imagen principal por producto.
        Index(
            "uq_imagenes_principal_por_producto",
            "producto_id",
            unique=True,
            postgresql_where=text("is_principal = TRUE"),
        ),
    )

    producto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "productos.id",
            name="fk_imagenes_producto",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=False,
    )
    variante_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "variantes_producto.id",
            name="fk_imagenes_variante",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=True,
    )
    url: Mapped[str] = mapped_column(String(255), nullable=False)
    is_principal: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    orden: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    producto: Mapped[Producto] = relationship(back_populates="imagenes")
    variante: Mapped[VarianteProducto | None] = relationship(back_populates="imagenes")

    def __repr__(self) -> str:
        return f"<ImagenProducto url={self.url!r} orden={self.orden}>"
