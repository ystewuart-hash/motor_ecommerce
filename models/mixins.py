"""
Mixins reutilizables para los modelos ORM.

Replican los patrones comunes del DDL (init.sql):
- Claves primarias UUID v4 generadas por PostgreSQL (gen_random_uuid()).
- Columnas de auditoría created_at / updated_at en TIMESTAMPTZ.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPrimaryKeyMixin:
    """Clave primaria UUID v4 generada en la base de datos."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        sort_order=-10,
        server_default=func.gen_random_uuid(),
    )


class TimestampMixin:
    """
    Auditoría de timestamps.

    updated_at lo mantiene el trigger set_updated_at_timestamp() en PostgreSQL;
    FetchedValue() le indica al ORM que la BD modifica la columna en cada UPDATE
    para que la expire y la recargue en vez de conservar un valor obsoleto.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        sort_order=10,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        sort_order=10,
        server_onupdate=FetchedValue(),
    )
