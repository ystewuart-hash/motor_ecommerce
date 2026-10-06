"""
Cálculo del costo de envío.

Versión estática del Sprint 1: tarifa fija por provincia definida en código.
La logística avanzada (zonas, peso, proveedores) reemplazará este módulo sin
tocar el checkout, que solo depende de calcular_costo_envio().
"""
from decimal import Decimal

from schemas.transacciones import DireccionEnvio, Provincia

# Valores de referencia en colones (CRC). Ajustar a las tarifas reales.
TARIFA_GAM = Decimal("3000.00")
TARIFA_FUERA_GAM = Decimal("4000.00")
TARIFA_POR_DEFECTO = TARIFA_FUERA_GAM

TARIFAS_POR_PROVINCIA: dict[Provincia, Decimal] = {
    Provincia.SAN_JOSE: TARIFA_GAM,
    Provincia.ALAJUELA: TARIFA_GAM,
    Provincia.CARTAGO: TARIFA_GAM,
    Provincia.HEREDIA: TARIFA_GAM,
    Provincia.GUANACASTE: TARIFA_FUERA_GAM,
    Provincia.PUNTARENAS: TARIFA_FUERA_GAM,
    Provincia.LIMON: TARIFA_FUERA_GAM,
}


def calcular_costo_envio(direccion: DireccionEnvio) -> Decimal:
    return TARIFAS_POR_PROVINCIA.get(direccion.provincia, TARIFA_POR_DEFECTO)
