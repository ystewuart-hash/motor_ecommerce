"""
Bloque 2: Transaccional y Financiero.

Tablas: pedidos, items_pedido, pagos_sinpe.
ENUMs:  estado_pedido_enum, estado_validacion_pago_enum.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    FetchedValue,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from models.catalogo import VarianteProducto


# ============================================================================
# ENUMS DE NEGOCIO
# ============================================================================
class EstadoPedido(enum.StrEnum):
    """Ciclo de vida de un pedido (estado_pedido_enum)."""

    PENDIENTE_PAGO = "pendiente_pago"
    EN_PREPARACION = "en_preparacion"
    ENVIADO = "enviado"
    ENTREGADO = "entregado"
    CANCELADO = "cancelado"
    REEMBOLSADO = "reembolsado"


class EstadoValidacionPago(enum.StrEnum):
    """Conciliación de comprobantes SINPE Móvil (estado_validacion_pago_enum)."""

    PENDIENTE = "pendiente"
    APROBADO = "aprobado"
    RECHAZADO = "rechazado"


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    # Persiste los .value en minúscula (como en el DDL) en lugar de los nombres.
    return [member.value for member in enum_cls]


# create_type=False: los tipos ya los crea init.sql; el ORM no debe emitir CREATE TYPE.
estado_pedido_pg = ENUM(
    EstadoPedido,
    name="estado_pedido_enum",
    create_type=False,
    values_callable=_enum_values,
)
estado_validacion_pago_pg = ENUM(
    EstadoValidacionPago,
    name="estado_validacion_pago_enum",
    create_type=False,
    values_callable=_enum_values,
)


# ----------------------------------------------------------------------------
# pedidos
# ----------------------------------------------------------------------------
class Pedido(UUIDPrimaryKeyMixin, Base):
    """Cabecera transaccional del pedido (Guest Checkout)."""

    __tablename__ = "pedidos"
    __table_args__ = (
        CheckConstraint("subtotal_productos >= 0", name="chk_pedidos_subtotal_no_negativo"),
        CheckConstraint("costo_envio >= 0", name="chk_pedidos_costo_envio_no_negativo"),
        CheckConstraint(
            "monto_total = subtotal_productos + costo_envio",
            name="chk_pedidos_monto_total_valido",
        ),
        CheckConstraint(
            "jsonb_typeof(direccion_envio) = 'object'",
            name="chk_pedidos_direccion_envio_is_object",
        ),
        CheckConstraint("cliente_whatsapp ~ '^[+0-9]{8,20}$'", name="chk_pedidos_whatsapp_format"),
        UniqueConstraint("clave_idempotencia", name="uq_pedidos_clave_idempotencia"),
        Index("idx_pedidos_direccion_envio_gin", "direccion_envio", postgresql_using="gin"),
        Index("idx_pedidos_cliente_whatsapp", "cliente_whatsapp"),
    )

    cliente_nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    cliente_whatsapp: Mapped[str] = mapped_column(String(20), nullable=False)
    cliente_email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    direccion_envio: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
    )
    subtotal_productos: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    costo_envio: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    monto_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    estado_pedido: Mapped[EstadoPedido] = mapped_column(
        estado_pedido_pg,
        nullable=False,
        server_default=EstadoPedido.PENDIENTE_PAGO.value,
    )
    # Header Idempotency-Key del checkout: un reintento con la misma clave
    # devuelve el pedido original en vez de crear otro (y reservar stock dos veces).
    clave_idempotencia: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        server_onupdate=FetchedValue(),
    )

    # ON DELETE RESTRICT protege la inmutabilidad histórica: el ORM crea los ítems
    # y pagos en cascada junto al pedido, pero nunca los borra ni los desvincula.
    items: Mapped[list[ItemPedido]] = relationship(
        back_populates="pedido",
        cascade="save-update, merge",
        passive_deletes="all",
    )
    pagos: Mapped[list[PagoSinpe]] = relationship(
        back_populates="pedido",
        cascade="save-update, merge",
        passive_deletes="all",
        order_by="PagoSinpe.fecha_registro",
    )

    def __repr__(self) -> str:
        return f"<Pedido id={self.id} estado={self.estado_pedido}>"


Index(
    "idx_pedidos_estado_fecha",
    Pedido.estado_pedido,
    Pedido.fecha_creacion.desc(),
)


# ----------------------------------------------------------------------------
# items_pedido
# ----------------------------------------------------------------------------
class ItemPedido(UUIDPrimaryKeyMixin, Base):
    """Línea de compra con precio histórico congelado."""

    __tablename__ = "items_pedido"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="chk_items_cantidad_positiva"),
        CheckConstraint(
            "precio_unitario_historico >= 0",
            name="chk_items_precio_historico_no_negativo",
        ),
        Index("idx_items_pedido_pedido_id", "pedido_id"),
        Index("idx_items_pedido_variante_id", "variante_id"),
    )

    pedido_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "pedidos.id",
            name="fk_items_pedido_cabecera",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        nullable=False,
    )
    variante_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "variantes_producto.id",
            name="fk_items_pedido_variante",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        nullable=False,
    )
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    precio_unitario_historico: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # GENERATED ALWAYS AS ... STORED: solo lectura desde el ORM.
    subtotal_linea: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        Computed("cantidad * precio_unitario_historico", persisted=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    pedido: Mapped[Pedido] = relationship(back_populates="items")
    variante: Mapped[VarianteProducto] = relationship(back_populates="items_pedido")

    def __repr__(self) -> str:
        return f"<ItemPedido variante_id={self.variante_id} cantidad={self.cantidad}>"


# ----------------------------------------------------------------------------
# pagos_sinpe
# ----------------------------------------------------------------------------
class PagoSinpe(UUIDPrimaryKeyMixin, Base):
    """Comprobante SINPE Móvil con barrera anti-fraude por referencia única."""

    __tablename__ = "pagos_sinpe"
    __table_args__ = (
        UniqueConstraint("numero_referencia", name="uq_pagos_sinpe_numero_referencia"),
        CheckConstraint("monto_transferido > 0", name="chk_pagos_monto_transferido_positivo"),
        CheckConstraint(
            "char_length(trim(numero_referencia)) > 0",
            name="chk_pagos_referencia_not_empty",
        ),
        Index("idx_pagos_sinpe_pedido_id", "pedido_id"),
    )

    pedido_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "pedidos.id",
            name="fk_pagos_sinpe_pedido",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        nullable=False,
    )
    numero_referencia: Mapped[str] = mapped_column(String(100), nullable=False)
    telefono_emisor: Mapped[str] = mapped_column(String(20), nullable=False)
    monto_transferido: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    comprobante_url: Mapped[str] = mapped_column(String(255), nullable=False)
    estado_validacion: Mapped[EstadoValidacionPago] = mapped_column(
        estado_validacion_pago_pg,
        nullable=False,
        server_default=EstadoValidacionPago.PENDIENTE.value,
    )
    fecha_registro: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        server_onupdate=FetchedValue(),
    )

    pedido: Mapped[Pedido] = relationship(back_populates="pagos")

    def __repr__(self) -> str:
        return f"<PagoSinpe referencia={self.numero_referencia!r} estado={self.estado_validacion}>"


Index(
    "idx_pagos_sinpe_pendientes",
    PagoSinpe.estado_validacion,
    PagoSinpe.fecha_registro.desc(),
    postgresql_where=text("estado_validacion = 'pendiente'"),
)
