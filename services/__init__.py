"""
Capa de servicios: reglas de negocio, cálculos monetarios y control de concurrencia.

Los servicios no conocen HTTP: reciben una Session y schemas validados, y señalan
problemas con las excepciones de services.excepciones. errores.py las traduce a
códigos HTTP, de modo que los routers solo reciben tráfico y delegan.

Cada función pública de escritura es una unidad de trabajo: hace commit al final
y, si algo falla, la sesión se descarta (rollback) al cerrar la request.
"""
