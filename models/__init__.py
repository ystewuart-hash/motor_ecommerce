"""
Registro central de modelos ORM.

Importar ambos módulos aquí garantiza que todas las clases queden registradas en
Base.metadata antes de configurar los mappers, de modo que las relaciones
declaradas por nombre entre catalogo.py y transacciones.py se resuelvan.
"""
from models.catalogo import (
    Categoria,
    ImagenProducto,
    Marca,
    Producto,
    VarianteProducto,
)
from models.transacciones import (
    EstadoPedido,
    EstadoValidacionPago,
    ItemPedido,
    PagoSinpe,
    Pedido,
)

__all__ = [
    "Categoria",
    "Marca",
    "Producto",
    "VarianteProducto",
    "ImagenProducto",
    "Pedido",
    "ItemPedido",
    "PagoSinpe",
    "EstadoPedido",
    "EstadoValidacionPago",
]
