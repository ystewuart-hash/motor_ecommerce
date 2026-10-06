"""
Bases y tipos compartidos por todos los schemas Pydantic.

Los tipos anotados replican las restricciones CHECK de init.sql para rechazar
datos inválidos con un 422 antes de llegar a PostgreSQL.
"""
from decimal import Decimal
from typing import Annotated, ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ----------------------------------------------------------------------------
# Tipos reutilizables
# ----------------------------------------------------------------------------
SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
WHATSAPP_PATTERN = r"^[+0-9]{8,20}$"
# Validación básica; para validación estricta instala email-validator y usa EmailStr.
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

Slug100 = Annotated[str, Field(min_length=1, max_length=100, pattern=SLUG_PATTERN)]
Slug150 = Annotated[str, Field(min_length=1, max_length=150, pattern=SLUG_PATTERN)]
Url255 = Annotated[str, Field(min_length=1, max_length=255)]

# NUMERIC(12,2)
Monto = Annotated[Decimal, Field(max_digits=12, decimal_places=2)]
MontoNoNegativo = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
MontoPositivo = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]


# ----------------------------------------------------------------------------
# Clases base
# ----------------------------------------------------------------------------
class BaseSchema(BaseModel):
    """Base de entrada: recorta espacios y rechaza campos desconocidos."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )


class UpdateSchema(BaseSchema):
    """
    Base para actualizaciones parciales (PATCH).

    Todos los campos son opcionales; usa `schema.model_dump(exclude_unset=True)`
    para aplicar solo lo que el cliente envió. Como "omitido" y "null" son
    distintos, se rechaza un null explícito en columnas NOT NULL salvo que el
    campo aparezca en `campos_anulables`.
    """

    campos_anulables: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _rechazar_nulos_en_columnas_not_null(self) -> Self:
        for campo in self.model_fields_set:
            if getattr(self, campo) is None and campo not in self.campos_anulables:
                raise ValueError(f"El campo '{campo}' no admite null")
        return self


class ResponseSchema(BaseModel):
    """Base de salida: lee directamente objetos ORM de SQLAlchemy."""

    model_config = ConfigDict(from_attributes=True)
