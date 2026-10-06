"""esquema inicial

Crea el esquema completo del Sprint 3 (equivalente a init.sql).

Generada con `alembic revision --autogenerate` contra una base vacía y
completada a mano con lo que el autogenerate NO detecta porque no forma parte
de Base.metadata:
    - Los tipos ENUM (los modelos usan create_type=False).
    - La función set_updated_at_timestamp() y sus 7 triggers BEFORE UPDATE.
    - Los COMMENT ON de documentación (tablas, columnas, tipos y función).

Revision ID: 0001
Revises:
Create Date: 2026-10-06 00:33:35.634485

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# --- Añadido a mano: objetos fuera de Base.metadata ------------------------
ESTADO_PEDIDO = postgresql.ENUM(
    'pendiente_pago', 'en_preparacion', 'enviado', 'entregado', 'cancelado', 'reembolsado',
    name='estado_pedido_enum',
)
ESTADO_VALIDACION_PAGO = postgresql.ENUM(
    'pendiente', 'aprobado', 'rechazado',
    name='estado_validacion_pago_enum',
)
TABLAS_CON_UPDATED_AT = {
    'categorias': 'trg_categorias_updated_at',
    'marcas': 'trg_marcas_updated_at',
    'productos': 'trg_productos_updated_at',
    'variantes_producto': 'trg_variantes_updated_at',
    'imagenes_producto': 'trg_imagenes_updated_at',
    'pedidos': 'trg_pedidos_updated_at',
    'pagos_sinpe': 'trg_pagos_sinpe_updated_at',
}
FUNCION_UPDATED_AT = """
CREATE OR REPLACE FUNCTION set_updated_at_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# Documentación del esquema (COMMENT ON), copiada de init.sql. Los modelos no
# declaran comment=; env.py excluye los comentarios del autogenerate, así que se
# mantienen con migraciones explícitas como esta.
COMENTARIOS = [
    "COMMENT ON TYPE estado_pedido_enum IS 'Estados oficiales del ciclo de vida de un pedido en la plataforma';",
    "COMMENT ON TYPE estado_validacion_pago_enum IS 'Estados de auditoría y conciliación para comprobantes SINPE Móvil';",
    "COMMENT ON FUNCTION set_updated_at_timestamp() IS 'Función trigger para actualizar automáticamente updated_at en modificaciones';",
    "COMMENT ON TABLE categorias IS 'Clasificación taxonómica de primer nivel para organización del catálogo';",
    "COMMENT ON COLUMN categorias.id IS 'Identificador universal único (UUID v4) autogenerado';",
    "COMMENT ON COLUMN categorias.nombre IS 'Nombre comercial legible de la categoría (ej. Proteínas Whey)';",
    "COMMENT ON COLUMN categorias.slug IS 'Identificador URL-friendly único para indexación SEO y enrutamiento';",
    "COMMENT ON COLUMN categorias.is_active IS 'Bandera de borrado lógico (Soft Delete); FALSE oculta la categoría sin romper integridad referencial';",
    "COMMENT ON COLUMN categorias.created_at IS 'Marca temporal de auditoría en UTC al momento de la inserción';",
    "COMMENT ON COLUMN categorias.updated_at IS 'Marca temporal de auditoría en UTC actualizada en cada modificación';",
    "COMMENT ON TABLE marcas IS 'Fabricantes, marcas comerciales o proveedores de los productos';",
    "COMMENT ON COLUMN marcas.id IS 'Identificador universal único (UUID v4) autogenerado';",
    "COMMENT ON COLUMN marcas.nombre IS 'Nombre comercial de la marca (ej. Optimum Nutrition, Dymatize)';",
    "COMMENT ON COLUMN marcas.slug IS 'URL amigable única para páginas de filtrado por marca';",
    "COMMENT ON COLUMN marcas.logo_url IS 'URI del recurso gráfico optimizado en CDN o bucket de almacenamiento';",
    "COMMENT ON COLUMN marcas.is_active IS 'Bandera de borrado lógico; desactiva la marca en filtros de catálogo';",
    "COMMENT ON COLUMN marcas.created_at IS 'Marca temporal de creación para auditoría';",
    "COMMENT ON COLUMN marcas.updated_at IS 'Marca temporal de última modificación para auditoría';",
    "COMMENT ON TABLE productos IS 'Entidad matriz del catálogo; agrupa variantes comercializables bajo una misma ficha descriptiva';",
    "COMMENT ON COLUMN productos.id IS 'Identificador universal único (UUID v4)';",
    "COMMENT ON COLUMN productos.categoria_id IS 'FK referenciando a categorias(id). ON DELETE RESTRICT previene eliminar categorías con productos huérfanos';",
    "COMMENT ON COLUMN productos.marca_id IS 'FK referenciando a marcas(id). ON DELETE SET NULL permite desvincular marca sin perder producto';",
    "COMMENT ON COLUMN productos.nombre IS 'Título principal del producto mostrado al cliente';",
    "COMMENT ON COLUMN productos.slug IS 'URL amigable del producto única en toda la tienda para SEO';",
    "COMMENT ON COLUMN productos.descripcion_html IS 'Contenido estructurado en HTML para especificaciones, ficha técnica y beneficios';",
    "COMMENT ON COLUMN productos.is_active IS 'Control de disponibilidad en tienda (Soft Delete); FALSE oculta el producto y sus variantes';",
    "COMMENT ON COLUMN productos.created_at IS 'Marca temporal de auditoría de creación';",
    "COMMENT ON COLUMN productos.updated_at IS 'Marca temporal de auditoría de última actualización';",
    "COMMENT ON TABLE variantes_producto IS 'Unidad mínima de inventario vendible (SKU). Desacoplada mediante atributos JSONB para cualquier nicho';",
    "COMMENT ON COLUMN variantes_producto.id IS 'Identificador universal único (UUID v4)';",
    "COMMENT ON COLUMN variantes_producto.producto_id IS 'FK a productos(id). Representa el contenedor matriz de la variante';",
    "COMMENT ON COLUMN variantes_producto.sku IS 'Stock Keeping Unit o código de barras comercial único en todo el catálogo';",
    'COMMENT ON COLUMN variantes_producto.atributos IS \'Documento JSONB con atributos dinámicos llave-valor (ej. {"sabor": "Chocolate", "peso": "5lb"})\';',
    "COMMENT ON COLUMN variantes_producto.precio IS 'Precio unitario actual de venta al público en moneda local';",
    "COMMENT ON COLUMN variantes_producto.stock_disponible IS 'Existencias físicas disponibles para despacho inmediato (concurrencia controlada)';",
    "COMMENT ON COLUMN variantes_producto.is_active IS 'Soft delete de variante; permite descontinuar una presentación específica';",
    "COMMENT ON COLUMN variantes_producto.created_at IS 'Marca temporal de alta en inventario';",
    "COMMENT ON COLUMN variantes_producto.updated_at IS 'Marca temporal de sincronización de precio o stock';",
    "COMMENT ON TABLE imagenes_producto IS 'Galería fotográfica asociada al producto o a una variante de color/presentación específica';",
    "COMMENT ON COLUMN imagenes_producto.id IS 'Identificador único de la imagen';",
    "COMMENT ON COLUMN imagenes_producto.producto_id IS 'FK a productos(id); producto general al que pertenece la imagen';",
    "COMMENT ON COLUMN imagenes_producto.variante_id IS 'FK a variantes_producto(id); NULL si es imagen genérica del producto, o asignado si es foto de una variante puntual';",
    "COMMENT ON COLUMN imagenes_producto.url IS 'URL pública segura hacia el CDN o Bucket de almacenamiento';",
    "COMMENT ON COLUMN imagenes_producto.is_principal IS 'Indica si es la imagen de portada prioritaria en listados y tarjetas';",
    "COMMENT ON COLUMN imagenes_producto.orden IS 'Secuencia numérica ascendente para ordenar el carrusel de fotos';",
    "COMMENT ON COLUMN imagenes_producto.created_at IS 'Marca temporal de subida';",
    "COMMENT ON COLUMN imagenes_producto.updated_at IS 'Marca temporal de modificación de metadata';",
    "COMMENT ON TABLE pedidos IS 'Cabecera transaccional y financiera del pedido. Soporta Guest Checkout con auditoría inmutable';",
    "COMMENT ON COLUMN pedidos.id IS 'Identificador universal único (UUID v4) que previene enumeración maliciosa de órdenes';",
    "COMMENT ON COLUMN pedidos.cliente_nombre IS 'Nombre y apellidos de quien recibe el despacho';",
    "COMMENT ON COLUMN pedidos.cliente_whatsapp IS 'Canal primario de notificación, confirmación y contacto comercial';",
    "COMMENT ON COLUMN pedidos.cliente_email IS 'Correo electrónico opcional para comprobantes y facturación electrónica';",
    "COMMENT ON COLUMN pedidos.direccion_envio IS 'Estructura JSONB dinámica de entrega (provincia, cantón, distrito, señas exactas, coordenadas GPS)';",
    "COMMENT ON COLUMN pedidos.subtotal_productos IS 'Suma acumulada del importe de todos los ítems adquiridos';",
    "COMMENT ON COLUMN pedidos.costo_envio IS 'Costo de flete logístico calculado según la zona de entrega';",
    "COMMENT ON COLUMN pedidos.monto_total IS 'Importe total exigible y vinculante del pedido (subtotal + flete)';",
    "COMMENT ON COLUMN pedidos.estado_pedido IS 'Estado actual del ciclo de vida del pedido (controlado por ENUM)';",
    "COMMENT ON COLUMN pedidos.clave_idempotencia IS 'Clave Idempotency-Key enviada por el cliente; UNIQUE impide duplicar pedidos y reservas de stock por reintentos o doble clic';",
    "COMMENT ON COLUMN pedidos.fecha_creacion IS 'Marca temporal inmutable de emisión de la orden de compra';",
    "COMMENT ON COLUMN pedidos.updated_at IS 'Marca temporal de actualización de estado u operativas';",
    "COMMENT ON TABLE items_pedido IS 'Líneas detalladas de compra. Congela inmutablemente el precio histórico para auditoría contable';",
    "COMMENT ON COLUMN items_pedido.id IS 'Identificador único de la línea de pedido';",
    "COMMENT ON COLUMN items_pedido.pedido_id IS 'FK referenciando a pedidos(id). ON DELETE RESTRICT protege la inmutabilidad histórica';",
    "COMMENT ON COLUMN items_pedido.variante_id IS 'FK referenciando a variantes_producto(id). ON DELETE RESTRICT impide borrar variantes ya vendidas';",
    "COMMENT ON COLUMN items_pedido.cantidad IS 'Cantidad de unidades físicas adquiridas en la transacción';",
    "COMMENT ON COLUMN items_pedido.precio_unitario_historico IS 'Precio congelado al momento exacto del checkout; inmune a futuras alzas de catálogo';",
    "COMMENT ON COLUMN items_pedido.subtotal_linea IS 'Columna generada almacenada (STORED) calculada como cantidad * precio_unitario_historico';",
    "COMMENT ON COLUMN items_pedido.created_at IS 'Marca temporal de registro de la línea';",
    "COMMENT ON TABLE pagos_sinpe IS 'Registro de conciliación bancaria SINPE Móvil con barrera matemática anti-fraude';",
    "COMMENT ON COLUMN pagos_sinpe.id IS 'Identificador universal único del comprobante registrado';",
    "COMMENT ON COLUMN pagos_sinpe.pedido_id IS 'FK a pedidos(id); pedido comercial que se pretende amortizar o liquidar';",
    "COMMENT ON COLUMN pagos_sinpe.numero_referencia IS 'Referencia bancaria única del voucher o SMS. UNIQUE impide reutilizar comprobantes para estafas';",
    "COMMENT ON COLUMN pagos_sinpe.telefono_emisor IS 'Número de teléfono desde el que se emitió el pase de fondos SINPE';",
    "COMMENT ON COLUMN pagos_sinpe.monto_transferido IS 'Monto neto reportado por el cliente en moneda nacional';",
    "COMMENT ON COLUMN pagos_sinpe.comprobante_url IS 'Enlace al archivo de imagen o captura almacenado en bucket seguro';",
    "COMMENT ON COLUMN pagos_sinpe.estado_validacion IS 'Estado de auditoría financiera (pendiente, aprobado, rechazado) tipificado por ENUM';",
    "COMMENT ON COLUMN pagos_sinpe.fecha_registro IS 'Marca temporal inmutable en que el cliente subió el comprobante';",
    "COMMENT ON COLUMN pagos_sinpe.updated_at IS 'Marca temporal de cuando el administrador u OCR validó la transacción';",
]


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    ESTADO_PEDIDO.create(bind, checkfirst=True)
    ESTADO_VALIDACION_PAGO.create(bind, checkfirst=True)
    op.execute(FUNCION_UPDATED_AT)

    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('categorias',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('nombre', sa.String(length=100), nullable=False),
    sa.Column('slug', sa.String(length=100), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('TRUE'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.CheckConstraint("slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'", name='chk_categorias_slug_format'),
    sa.CheckConstraint('char_length(trim(nombre)) > 0', name='chk_categorias_nombre_not_empty'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug', name='uq_categorias_slug')
    )
    op.create_index('idx_categorias_slug_active', 'categorias', ['slug'], unique=False, postgresql_where=sa.text('is_active = TRUE'))
    op.create_table('marcas',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('nombre', sa.String(length=100), nullable=False),
    sa.Column('slug', sa.String(length=100), nullable=False),
    sa.Column('logo_url', sa.String(length=255), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('TRUE'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.CheckConstraint("slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'", name='chk_marcas_slug_format'),
    sa.CheckConstraint('char_length(trim(nombre)) > 0', name='chk_marcas_nombre_not_empty'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug', name='uq_marcas_slug')
    )
    op.create_index('idx_marcas_slug_active', 'marcas', ['slug'], unique=False, postgresql_where=sa.text('is_active = TRUE'))
    op.create_table('pedidos',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('cliente_nombre', sa.String(length=150), nullable=False),
    sa.Column('cliente_whatsapp', sa.String(length=20), nullable=False),
    sa.Column('cliente_email', sa.String(length=150), nullable=True),
    sa.Column('direccion_envio', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('subtotal_productos', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('costo_envio', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('monto_total', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('estado_pedido', postgresql.ENUM('pendiente_pago', 'en_preparacion', 'enviado', 'entregado', 'cancelado', 'reembolsado', name='estado_pedido_enum', create_type=False), server_default='pendiente_pago', nullable=False),
    sa.Column('clave_idempotencia', sa.String(length=100), nullable=True),
    sa.Column('fecha_creacion', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.CheckConstraint("cliente_whatsapp ~ '^[+0-9]{8,20}$'", name='chk_pedidos_whatsapp_format'),
    sa.CheckConstraint("jsonb_typeof(direccion_envio) = 'object'", name='chk_pedidos_direccion_envio_is_object'),
    sa.CheckConstraint('costo_envio >= 0', name='chk_pedidos_costo_envio_no_negativo'),
    sa.CheckConstraint('monto_total = subtotal_productos + costo_envio', name='chk_pedidos_monto_total_valido'),
    sa.CheckConstraint('subtotal_productos >= 0', name='chk_pedidos_subtotal_no_negativo'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('clave_idempotencia', name='uq_pedidos_clave_idempotencia')
    )
    op.create_index('idx_pedidos_cliente_whatsapp', 'pedidos', ['cliente_whatsapp'], unique=False)
    op.create_index('idx_pedidos_direccion_envio_gin', 'pedidos', ['direccion_envio'], unique=False, postgresql_using='gin')
    op.create_index('idx_pedidos_estado_fecha', 'pedidos', ['estado_pedido', sa.literal_column('fecha_creacion DESC')], unique=False)
    op.create_table('pagos_sinpe',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('pedido_id', sa.UUID(), nullable=False),
    sa.Column('numero_referencia', sa.String(length=100), nullable=False),
    sa.Column('telefono_emisor', sa.String(length=20), nullable=False),
    sa.Column('monto_transferido', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('comprobante_url', sa.String(length=255), nullable=False),
    sa.Column('estado_validacion', postgresql.ENUM('pendiente', 'aprobado', 'rechazado', name='estado_validacion_pago_enum', create_type=False), server_default='pendiente', nullable=False),
    sa.Column('fecha_registro', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.CheckConstraint('char_length(trim(numero_referencia)) > 0', name='chk_pagos_referencia_not_empty'),
    sa.CheckConstraint('monto_transferido > 0', name='chk_pagos_monto_transferido_positivo'),
    sa.ForeignKeyConstraint(['pedido_id'], ['pedidos.id'], name='fk_pagos_sinpe_pedido', onupdate='CASCADE', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('numero_referencia', name='uq_pagos_sinpe_numero_referencia')
    )
    op.create_index('idx_pagos_sinpe_pedido_id', 'pagos_sinpe', ['pedido_id'], unique=False)
    op.create_index('idx_pagos_sinpe_pendientes', 'pagos_sinpe', ['estado_validacion', sa.literal_column('fecha_registro DESC')], unique=False, postgresql_where=sa.text("estado_validacion = 'pendiente'"))
    op.create_table('productos',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('categoria_id', sa.UUID(), nullable=False),
    sa.Column('marca_id', sa.UUID(), nullable=True),
    sa.Column('nombre', sa.String(length=150), nullable=False),
    sa.Column('slug', sa.String(length=150), nullable=False),
    sa.Column('descripcion_html', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('TRUE'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.CheckConstraint("slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'", name='chk_productos_slug_format'),
    sa.CheckConstraint('char_length(trim(nombre)) > 0', name='chk_productos_nombre_not_empty'),
    sa.ForeignKeyConstraint(['categoria_id'], ['categorias.id'], name='fk_productos_categoria', onupdate='CASCADE', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['marca_id'], ['marcas.id'], name='fk_productos_marca', onupdate='CASCADE', ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug', name='uq_productos_slug')
    )
    op.create_index('idx_productos_categoria_id', 'productos', ['categoria_id'], unique=False)
    op.create_index('idx_productos_marca_id', 'productos', ['marca_id'], unique=False)
    op.create_index('idx_productos_slug_active', 'productos', ['slug'], unique=False, postgresql_where=sa.text('is_active = TRUE'))
    op.create_table('variantes_producto',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('producto_id', sa.UUID(), nullable=False),
    sa.Column('sku', sa.String(length=50), nullable=False),
    sa.Column('atributos', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('precio', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('stock_disponible', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('TRUE'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.CheckConstraint("jsonb_typeof(atributos) = 'object'", name='chk_variantes_atributos_is_object'),
    sa.CheckConstraint('precio >= 0', name='chk_variantes_precio_no_negativo'),
    sa.CheckConstraint('stock_disponible >= 0', name='chk_variantes_stock_no_negativo'),
    sa.ForeignKeyConstraint(['producto_id'], ['productos.id'], name='fk_variantes_producto', onupdate='CASCADE', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('sku', name='uq_variantes_sku')
    )
    op.create_index('idx_variantes_atributos_gin', 'variantes_producto', ['atributos'], unique=False, postgresql_using='gin', postgresql_ops={'atributos': 'jsonb_path_ops'})
    op.create_index('idx_variantes_producto_id', 'variantes_producto', ['producto_id'], unique=False)
    op.create_index('idx_variantes_sku_active', 'variantes_producto', ['sku'], unique=False, postgresql_where=sa.text('is_active = TRUE'))
    op.create_table('imagenes_producto',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('producto_id', sa.UUID(), nullable=False),
    sa.Column('variante_id', sa.UUID(), nullable=True),
    sa.Column('url', sa.String(length=255), nullable=False),
    sa.Column('is_principal', sa.Boolean(), server_default=sa.text('FALSE'), nullable=False),
    sa.Column('orden', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.CheckConstraint('orden >= 0', name='chk_imagenes_orden_no_negativo'),
    sa.ForeignKeyConstraint(['producto_id'], ['productos.id'], name='fk_imagenes_producto', onupdate='CASCADE', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['variante_id'], ['variantes_producto.id'], name='fk_imagenes_variante', onupdate='CASCADE', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_imagenes_producto_id', 'imagenes_producto', ['producto_id'], unique=False)
    op.create_index('idx_imagenes_variante_id', 'imagenes_producto', ['variante_id'], unique=False)
    op.create_index('uq_imagenes_principal_por_producto', 'imagenes_producto', ['producto_id'], unique=True, postgresql_where=sa.text('is_principal = TRUE'))
    op.create_table('items_pedido',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('pedido_id', sa.UUID(), nullable=False),
    sa.Column('variante_id', sa.UUID(), nullable=False),
    sa.Column('cantidad', sa.Integer(), nullable=False),
    sa.Column('precio_unitario_historico', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('subtotal_linea', sa.Numeric(precision=12, scale=2), sa.Computed('cantidad * precio_unitario_historico', persisted=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.CheckConstraint('cantidad > 0', name='chk_items_cantidad_positiva'),
    sa.CheckConstraint('precio_unitario_historico >= 0', name='chk_items_precio_historico_no_negativo'),
    sa.ForeignKeyConstraint(['pedido_id'], ['pedidos.id'], name='fk_items_pedido_cabecera', onupdate='CASCADE', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['variante_id'], ['variantes_producto.id'], name='fk_items_pedido_variante', onupdate='CASCADE', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_items_pedido_pedido_id', 'items_pedido', ['pedido_id'], unique=False)
    op.create_index('idx_items_pedido_variante_id', 'items_pedido', ['variante_id'], unique=False)
    # ### end Alembic commands ###

    for tabla, trigger in TABLAS_CON_UPDATED_AT.items():
        op.execute(
            f'CREATE TRIGGER {trigger} BEFORE UPDATE ON {tabla} '
            f'FOR EACH ROW EXECUTE FUNCTION set_updated_at_timestamp()'
        )

    for comentario in COMENTARIOS:
        op.execute(comentario)


def downgrade() -> None:
    """Downgrade schema."""
    # Los triggers caen junto con sus tablas; la función y los ENUM, al final.
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('idx_items_pedido_variante_id', table_name='items_pedido')
    op.drop_index('idx_items_pedido_pedido_id', table_name='items_pedido')
    op.drop_table('items_pedido')
    op.drop_index('uq_imagenes_principal_por_producto', table_name='imagenes_producto', postgresql_where=sa.text('is_principal = TRUE'))
    op.drop_index('idx_imagenes_variante_id', table_name='imagenes_producto')
    op.drop_index('idx_imagenes_producto_id', table_name='imagenes_producto')
    op.drop_table('imagenes_producto')
    op.drop_index('idx_variantes_sku_active', table_name='variantes_producto', postgresql_where=sa.text('is_active = TRUE'))
    op.drop_index('idx_variantes_producto_id', table_name='variantes_producto')
    op.drop_index('idx_variantes_atributos_gin', table_name='variantes_producto', postgresql_using='gin', postgresql_ops={'atributos': 'jsonb_path_ops'})
    op.drop_table('variantes_producto')
    op.drop_index('idx_productos_slug_active', table_name='productos', postgresql_where=sa.text('is_active = TRUE'))
    op.drop_index('idx_productos_marca_id', table_name='productos')
    op.drop_index('idx_productos_categoria_id', table_name='productos')
    op.drop_table('productos')
    op.drop_index('idx_pagos_sinpe_pendientes', table_name='pagos_sinpe', postgresql_where=sa.text("estado_validacion = 'pendiente'"))
    op.drop_index('idx_pagos_sinpe_pedido_id', table_name='pagos_sinpe')
    op.drop_table('pagos_sinpe')
    op.drop_index('idx_pedidos_estado_fecha', table_name='pedidos')
    op.drop_index('idx_pedidos_direccion_envio_gin', table_name='pedidos', postgresql_using='gin')
    op.drop_index('idx_pedidos_cliente_whatsapp', table_name='pedidos')
    op.drop_table('pedidos')
    op.drop_index('idx_marcas_slug_active', table_name='marcas', postgresql_where=sa.text('is_active = TRUE'))
    op.drop_table('marcas')
    op.drop_index('idx_categorias_slug_active', table_name='categorias', postgresql_where=sa.text('is_active = TRUE'))
    op.drop_table('categorias')
    # ### end Alembic commands ###

    op.execute('DROP FUNCTION IF EXISTS set_updated_at_timestamp()')
    bind = op.get_bind()
    ESTADO_VALIDACION_PAGO.drop(bind, checkfirst=True)
    ESTADO_PEDIDO.drop(bind, checkfirst=True)
