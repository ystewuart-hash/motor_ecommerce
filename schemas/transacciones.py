"""
Schemas del Bloque 2: Transaccional y Financiero.

Regla de seguridad: el cliente nunca envía montos ni estados. Precios,
subtotales, costo de envío y monto_total los calcula el servidor a partir del
catálogo; los estados solo los cambia un administrador vía *Update.
"""
import enum
import unicodedata
import uuid
from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field, field_validator

from models.transacciones import EstadoPedido, EstadoValidacionPago
from schemas.base import (
    EMAIL_PATTERN,
    WHATSAPP_PATTERN,
    BaseSchema,
    Monto,
    MontoNoNegativo,
    MontoPositivo,
    ResponseSchema,
    UpdateSchema,
    Url255,
)

# Límites anti-abuso: como el stock se reserva al crear el pedido (antes del pago),
# sin topes un solo carrito podría acaparar todo el inventario.
MAX_LINEAS_POR_PEDIDO = 50
MAX_UNIDADES_POR_LINEA = 100


# ============================================================================
# Dirección de envío (columna JSONB)
# ============================================================================
class Provincia(enum.StrEnum):
    SAN_JOSE = "San José"
    ALAJUELA = "Alajuela"
    CARTAGO = "Cartago"
    HEREDIA = "Heredia"
    GUANACASTE = "Guanacaste"
    PUNTARENAS = "Puntarenas"
    LIMON = "Limón"


def _normalizar_texto(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.split()).casefold()


_PROVINCIAS_POR_CLAVE = {_normalizar_texto(p.value): p for p in Provincia}


class DireccionEnvio(BaseSchema):
    """
    Estructura validada del JSONB pedidos.direccion_envio.

    extra="allow" mantiene la flexibilidad del JSONB para claves adicionales.
    Al guardar en el ORM usa `direccion.a_jsonb()`.
    """

    model_config = ConfigDict(extra="allow", from_attributes=True)

    provincia: Provincia = Field(examples=["San José"])
    canton: str = Field(min_length=1, max_length=50, examples=["Escazú"])
    distrito: str = Field(min_length=1, max_length=50, examples=["San Rafael"])
    senas_exactas: str = Field(min_length=1, max_length=500)
    latitud: float | None = Field(default=None, ge=-90, le=90)
    longitud: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("provincia", mode="before")
    @classmethod
    def _normalizar_provincia(cls, valor: Any) -> Any:
        # Acepta "san jose", "SAN JOSÉ", "Limon"... y guarda siempre el nombre
        # canónico, para que los filtros sobre el JSONB sean consistentes.
        if isinstance(valor, str):
            return _PROVINCIAS_POR_CLAVE.get(_normalizar_texto(valor), valor)
        return valor

    def a_jsonb(self) -> dict[str, Any]:
        """Representación lista para la columna JSONB."""
        return self.model_dump(mode="json", exclude_none=True)


# ============================================================================
# Ítem de pedido
# ============================================================================
class ItemPedidoBase(BaseSchema):
    variante_id: uuid.UUID
    cantidad: int = Field(gt=0, le=MAX_UNIDADES_POR_LINEA)


class ItemPedidoCreate(ItemPedidoBase):
    """El precio NO se recibe: se congela desde variantes_producto.precio."""


# Sin ItemPedidoUpdate: las líneas de pedido son inmutables (auditoría contable).


class ItemPedidoResponse(ItemPedidoBase, ResponseSchema):
    id: uuid.UUID
    pedido_id: uuid.UUID
    precio_unitario_historico: Monto
    subtotal_linea: Monto
    created_at: datetime


# ============================================================================
# Pago SINPE Móvil
# ============================================================================
class PagoSinpeBase(BaseSchema):
    numero_referencia: str = Field(min_length=1, max_length=100)
    telefono_emisor: str = Field(max_length=20, pattern=WHATSAPP_PATTERN)
    monto_transferido: MontoPositivo
    comprobante_url: Url255


class PagoSinpeCreate(PagoSinpeBase):
    pedido_id: uuid.UUID


class PagoSinpeUpdate(UpdateSchema):
    """Solo conciliación administrativa: los datos del comprobante son inmutables."""

    estado_validacion: EstadoValidacionPago | None = None


class PagoSinpeResponse(PagoSinpeBase, ResponseSchema):
    id: uuid.UUID
    pedido_id: uuid.UUID
    estado_validacion: EstadoValidacionPago
    fecha_registro: datetime
    updated_at: datetime


# ============================================================================
# Pedido
# ============================================================================
class PedidoBase(BaseSchema):
    cliente_nombre: str = Field(min_length=1, max_length=150)
    cliente_whatsapp: str = Field(max_length=20, pattern=WHATSAPP_PATTERN, examples=["+50688887777"])
    cliente_email: str | None = Field(default=None, max_length=150, pattern=EMAIL_PATTERN)
    direccion_envio: DireccionEnvio


class PedidoCreate(PedidoBase):
    """Checkout de invitado: datos del cliente + líneas. Los montos los calcula el servidor."""

    items: list[ItemPedidoCreate] = Field(min_length=1, max_length=MAX_LINEAS_POR_PEDIDO)


class PedidoUpdate(UpdateSchema):
    """Uso administrativo: cambio de estado o corrección de datos de contacto/envío."""

    campos_anulables = frozenset({"cliente_email"})

    cliente_nombre: str | None = Field(default=None, min_length=1, max_length=150)
    cliente_whatsapp: str | None = Field(default=None, max_length=20, pattern=WHATSAPP_PATTERN)
    cliente_email: str | None = Field(default=None, max_length=150, pattern=EMAIL_PATTERN)
    direccion_envio: DireccionEnvio | None = None
    estado_pedido: EstadoPedido | None = None


class PedidoResponse(PedidoBase, ResponseSchema):
    """Versión ligera para listados (no dispara carga de ítems ni pagos)."""

    id: uuid.UUID
    subtotal_productos: MontoNoNegativo
    costo_envio: MontoNoNegativo
    monto_total: MontoNoNegativo
    estado_pedido: EstadoPedido
    fecha_creacion: datetime
    updated_at: datetime


class PedidoDetalleResponse(PedidoResponse):
    items: list[ItemPedidoResponse] = []
    pagos: list[PagoSinpeResponse] = []
