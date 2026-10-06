-- ============================================================================
-- MOTOR E-COMMERCE HEADLESS - SPRINT 1: CORE COMPLETO
-- Catálogo, Inventario Dinámico, Transacciones Inmutables y Pagos SINPE
-- Motor de Base de Datos: PostgreSQL 14+ / 15 / 16
-- Estándar: Arquitectura desacoplada, UUID v4, Auditoría y Seguridad Financiera
-- ============================================================================

-- ⚠ DESDE EL SPRINT 4 LA FUENTE DE VERDAD DEL ESQUEMA ES ALEMBIC (alembic/versions/).
--   Este archivo se conserva como documentación legible del modelo de datos.
--   Para crear o actualizar una base usar:  python -m alembic upgrade head
--   tests/test_migraciones.py verifica en cada CI que ambos producen el mismo esquema.
-- ============================================================================

-- Los UUID v4 se generan con gen_random_uuid(), nativo del núcleo desde PostgreSQL 13:
-- no requiere la extensión pgcrypto.

-- ============================================================================
-- 1. TIPOS ENUMERADOS (ENUMS DE NEGOCIO Y ESTADOS)
-- ============================================================================

-- Estado del ciclo de vida del pedido comercial
CREATE TYPE estado_pedido_enum AS ENUM (
    'pendiente_pago',      -- Carrito confirmado esperando comprobante o validación
    'en_preparacion',      -- Pago validado, orden en empaque y alistado
    'enviado',             -- Entregado a mensajería / servicio de logística
    'entregado',           -- Pedido completado exitosamente por el cliente
    'cancelado',           -- Cancelado por falta de pago o solicitud del cliente
    'reembolsado'          -- Fondos devueltos al cliente
);

COMMENT ON TYPE estado_pedido_enum IS 'Estados oficiales del ciclo de vida de un pedido en la plataforma';

-- Estado de validación financiera de pagos SINPE Móvil
CREATE TYPE estado_validacion_pago_enum AS ENUM (
    'pendiente',           -- Comprobante reportado por el cliente, pendiente de conciliación bancaria
    'aprobado',            -- Comprobante verificado en cuenta y acreditado a la orden
    'rechazado'            -- Comprobante falso, monto inconsistente o referencia duplicada
);

COMMENT ON TYPE estado_validacion_pago_enum IS 'Estados de auditoría y conciliación para comprobantes SINPE Móvil';

-- ============================================================================
-- 2. FUNCIÓN Y TRIGGERS DE AUDITORÍA AUTOMÁTICA (TIMESTAMPS)
-- ============================================================================

CREATE OR REPLACE FUNCTION set_updated_at_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION set_updated_at_timestamp() IS 'Función trigger para actualizar automáticamente updated_at en modificaciones';

-- ============================================================================
-- 3. BLOQUE 1: CATÁLOGO E INVENTARIO
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 3.1. TABLA: categorias
-- ----------------------------------------------------------------------------
CREATE TABLE categorias (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre VARCHAR(100) NOT NULL,
    slug VARCHAR(100) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Restricciones
    CONSTRAINT uq_categorias_slug UNIQUE (slug),
    CONSTRAINT chk_categorias_nombre_not_empty CHECK (char_length(trim(nombre)) > 0),
    CONSTRAINT chk_categorias_slug_format CHECK (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$')
);

COMMENT ON TABLE categorias IS 'Clasificación taxonómica de primer nivel para organización del catálogo';
COMMENT ON COLUMN categorias.id IS 'Identificador universal único (UUID v4) autogenerado';
COMMENT ON COLUMN categorias.nombre IS 'Nombre comercial legible de la categoría (ej. Proteínas Whey)';
COMMENT ON COLUMN categorias.slug IS 'Identificador URL-friendly único para indexación SEO y enrutamiento';
COMMENT ON COLUMN categorias.is_active IS 'Bandera de borrado lógico (Soft Delete); FALSE oculta la categoría sin romper integridad referencial';
COMMENT ON COLUMN categorias.created_at IS 'Marca temporal de auditoría en UTC al momento de la inserción';
COMMENT ON COLUMN categorias.updated_at IS 'Marca temporal de auditoría en UTC actualizada en cada modificación';

-- ----------------------------------------------------------------------------
-- 3.2. TABLA: marcas
-- ----------------------------------------------------------------------------
CREATE TABLE marcas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre VARCHAR(100) NOT NULL,
    slug VARCHAR(100) NOT NULL,
    logo_url VARCHAR(255) NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Restricciones
    CONSTRAINT uq_marcas_slug UNIQUE (slug),
    CONSTRAINT chk_marcas_nombre_not_empty CHECK (char_length(trim(nombre)) > 0),
    CONSTRAINT chk_marcas_slug_format CHECK (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$')
);

COMMENT ON TABLE marcas IS 'Fabricantes, marcas comerciales o proveedores de los productos';
COMMENT ON COLUMN marcas.id IS 'Identificador universal único (UUID v4) autogenerado';
COMMENT ON COLUMN marcas.nombre IS 'Nombre comercial de la marca (ej. Optimum Nutrition, Dymatize)';
COMMENT ON COLUMN marcas.slug IS 'URL amigable única para páginas de filtrado por marca';
COMMENT ON COLUMN marcas.logo_url IS 'URI del recurso gráfico optimizado en CDN o bucket de almacenamiento';
COMMENT ON COLUMN marcas.is_active IS 'Bandera de borrado lógico; desactiva la marca en filtros de catálogo';
COMMENT ON COLUMN marcas.created_at IS 'Marca temporal de creación para auditoría';
COMMENT ON COLUMN marcas.updated_at IS 'Marca temporal de última modificación para auditoría';

-- ----------------------------------------------------------------------------
-- 3.3. TABLA: productos
-- ----------------------------------------------------------------------------
CREATE TABLE productos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    categoria_id UUID NOT NULL,
    marca_id UUID NULL,
    nombre VARCHAR(150) NOT NULL,
    slug VARCHAR(150) NOT NULL,
    descripcion_html TEXT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Restricciones de Clave Foránea
    CONSTRAINT fk_productos_categoria
        FOREIGN KEY (categoria_id)
        REFERENCES categorias(id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CONSTRAINT fk_productos_marca
        FOREIGN KEY (marca_id)
        REFERENCES marcas(id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,

    -- Restricciones de Negocio
    CONSTRAINT uq_productos_slug UNIQUE (slug),
    CONSTRAINT chk_productos_nombre_not_empty CHECK (char_length(trim(nombre)) > 0),
    CONSTRAINT chk_productos_slug_format CHECK (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$')
);

COMMENT ON TABLE productos IS 'Entidad matriz del catálogo; agrupa variantes comercializables bajo una misma ficha descriptiva';
COMMENT ON COLUMN productos.id IS 'Identificador universal único (UUID v4)';
COMMENT ON COLUMN productos.categoria_id IS 'FK referenciando a categorias(id). ON DELETE RESTRICT previene eliminar categorías con productos huérfanos';
COMMENT ON COLUMN productos.marca_id IS 'FK referenciando a marcas(id). ON DELETE SET NULL permite desvincular marca sin perder producto';
COMMENT ON COLUMN productos.nombre IS 'Título principal del producto mostrado al cliente';
COMMENT ON COLUMN productos.slug IS 'URL amigable del producto única en toda la tienda para SEO';
COMMENT ON COLUMN productos.descripcion_html IS 'Contenido estructurado en HTML para especificaciones, ficha técnica y beneficios';
COMMENT ON COLUMN productos.is_active IS 'Control de disponibilidad en tienda (Soft Delete); FALSE oculta el producto y sus variantes';
COMMENT ON COLUMN productos.created_at IS 'Marca temporal de auditoría de creación';
COMMENT ON COLUMN productos.updated_at IS 'Marca temporal de auditoría de última actualización';

-- ----------------------------------------------------------------------------
-- 3.4. TABLA: variantes_producto (Core Transaccional de Inventario)
-- ----------------------------------------------------------------------------
CREATE TABLE variantes_producto (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    producto_id UUID NOT NULL,
    sku VARCHAR(50) NOT NULL,
    atributos JSONB NOT NULL DEFAULT '{}'::jsonb,
    precio NUMERIC(12,2) NOT NULL,
    stock_disponible INTEGER NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Restricciones de Clave Foránea
    CONSTRAINT fk_variantes_producto
        FOREIGN KEY (producto_id)
        REFERENCES productos(id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,

    -- Restricciones de Integridad y Negocio
    CONSTRAINT uq_variantes_sku UNIQUE (sku),
    CONSTRAINT chk_variantes_precio_no_negativo CHECK (precio >= 0),
    CONSTRAINT chk_variantes_stock_no_negativo CHECK (stock_disponible >= 0),
    CONSTRAINT chk_variantes_atributos_is_object CHECK (jsonb_typeof(atributos) = 'object')
);

COMMENT ON TABLE variantes_producto IS 'Unidad mínima de inventario vendible (SKU). Desacoplada mediante atributos JSONB para cualquier nicho';
COMMENT ON COLUMN variantes_producto.id IS 'Identificador universal único (UUID v4)';
COMMENT ON COLUMN variantes_producto.producto_id IS 'FK a productos(id). Representa el contenedor matriz de la variante';
COMMENT ON COLUMN variantes_producto.sku IS 'Stock Keeping Unit o código de barras comercial único en todo el catálogo';
COMMENT ON COLUMN variantes_producto.atributos IS 'Documento JSONB con atributos dinámicos llave-valor (ej. {"sabor": "Chocolate", "peso": "5lb"})';
COMMENT ON COLUMN variantes_producto.precio IS 'Precio unitario actual de venta al público en moneda local';
COMMENT ON COLUMN variantes_producto.stock_disponible IS 'Existencias físicas disponibles para despacho inmediato (concurrencia controlada)';
COMMENT ON COLUMN variantes_producto.is_active IS 'Soft delete de variante; permite descontinuar una presentación específica';
COMMENT ON COLUMN variantes_producto.created_at IS 'Marca temporal de alta en inventario';
COMMENT ON COLUMN variantes_producto.updated_at IS 'Marca temporal de sincronización de precio o stock';

-- ----------------------------------------------------------------------------
-- 3.5. TABLA: imagenes_producto
-- ----------------------------------------------------------------------------
CREATE TABLE imagenes_producto (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    producto_id UUID NOT NULL,
    variante_id UUID NULL,
    url VARCHAR(255) NOT NULL,
    is_principal BOOLEAN NOT NULL DEFAULT FALSE,
    orden INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Restricciones de Clave Foránea
    CONSTRAINT fk_imagenes_producto
        FOREIGN KEY (producto_id)
        REFERENCES productos(id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT fk_imagenes_variante
        FOREIGN KEY (variante_id)
        REFERENCES variantes_producto(id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,

    -- Restricciones
    CONSTRAINT chk_imagenes_orden_no_negativo CHECK (orden >= 0)
);

COMMENT ON TABLE imagenes_producto IS 'Galería fotográfica asociada al producto o a una variante de color/presentación específica';
COMMENT ON COLUMN imagenes_producto.id IS 'Identificador único de la imagen';
COMMENT ON COLUMN imagenes_producto.producto_id IS 'FK a productos(id); producto general al que pertenece la imagen';
COMMENT ON COLUMN imagenes_producto.variante_id IS 'FK a variantes_producto(id); NULL si es imagen genérica del producto, o asignado si es foto de una variante puntual';
COMMENT ON COLUMN imagenes_producto.url IS 'URL pública segura hacia el CDN o Bucket de almacenamiento';
COMMENT ON COLUMN imagenes_producto.is_principal IS 'Indica si es la imagen de portada prioritaria en listados y tarjetas';
COMMENT ON COLUMN imagenes_producto.orden IS 'Secuencia numérica ascendente para ordenar el carrusel de fotos';
COMMENT ON COLUMN imagenes_producto.created_at IS 'Marca temporal de subida';
COMMENT ON COLUMN imagenes_producto.updated_at IS 'Marca temporal de modificación de metadata';

-- ============================================================================
-- 4. BLOQUE 2: TRANSACCIONAL Y FINANCIERO
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 4.1. TABLA: pedidos
-- ----------------------------------------------------------------------------
CREATE TABLE pedidos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_nombre VARCHAR(150) NOT NULL,
    cliente_whatsapp VARCHAR(20) NOT NULL,
    cliente_email VARCHAR(150) NULL,
    direccion_envio JSONB NOT NULL,
    subtotal_productos NUMERIC(12,2) NOT NULL,
    costo_envio NUMERIC(12,2) NOT NULL,
    monto_total NUMERIC(12,2) NOT NULL,
    estado_pedido estado_pedido_enum NOT NULL DEFAULT 'pendiente_pago',
    clave_idempotencia VARCHAR(100) NULL,
    fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Idempotencia del checkout (varios NULL están permitidos por UNIQUE)
    CONSTRAINT uq_pedidos_clave_idempotencia UNIQUE (clave_idempotencia),

    -- Restricciones de Consistencia Financiera
    CONSTRAINT chk_pedidos_subtotal_no_negativo CHECK (subtotal_productos >= 0),
    CONSTRAINT chk_pedidos_costo_envio_no_negativo CHECK (costo_envio >= 0),
    CONSTRAINT chk_pedidos_monto_total_valido CHECK (monto_total = subtotal_productos + costo_envio),
    CONSTRAINT chk_pedidos_direccion_envio_is_object CHECK (jsonb_typeof(direccion_envio) = 'object'),
    CONSTRAINT chk_pedidos_whatsapp_format CHECK (cliente_whatsapp ~ '^[+0-9]{8,20}$')
);

COMMENT ON TABLE pedidos IS 'Cabecera transaccional y financiera del pedido. Soporta Guest Checkout con auditoría inmutable';
COMMENT ON COLUMN pedidos.id IS 'Identificador universal único (UUID v4) que previene enumeración maliciosa de órdenes';
COMMENT ON COLUMN pedidos.cliente_nombre IS 'Nombre y apellidos de quien recibe el despacho';
COMMENT ON COLUMN pedidos.cliente_whatsapp IS 'Canal primario de notificación, confirmación y contacto comercial';
COMMENT ON COLUMN pedidos.cliente_email IS 'Correo electrónico opcional para comprobantes y facturación electrónica';
COMMENT ON COLUMN pedidos.direccion_envio IS 'Estructura JSONB dinámica de entrega (provincia, cantón, distrito, señas exactas, coordenadas GPS)';
COMMENT ON COLUMN pedidos.subtotal_productos IS 'Suma acumulada del importe de todos los ítems adquiridos';
COMMENT ON COLUMN pedidos.costo_envio IS 'Costo de flete logístico calculado según la zona de entrega';
COMMENT ON COLUMN pedidos.monto_total IS 'Importe total exigible y vinculante del pedido (subtotal + flete)';
COMMENT ON COLUMN pedidos.estado_pedido IS 'Estado actual del ciclo de vida del pedido (controlado por ENUM)';
COMMENT ON COLUMN pedidos.clave_idempotencia IS 'Clave Idempotency-Key enviada por el cliente; UNIQUE impide duplicar pedidos y reservas de stock por reintentos o doble clic';
COMMENT ON COLUMN pedidos.fecha_creacion IS 'Marca temporal inmutable de emisión de la orden de compra';
COMMENT ON COLUMN pedidos.updated_at IS 'Marca temporal de actualización de estado u operativas';

-- ----------------------------------------------------------------------------
-- 4.2. TABLA: items_pedido
-- ----------------------------------------------------------------------------
CREATE TABLE items_pedido (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pedido_id UUID NOT NULL,
    variante_id UUID NOT NULL,
    cantidad INTEGER NOT NULL,
    precio_unitario_historico NUMERIC(12,2) NOT NULL,
    subtotal_linea NUMERIC(12,2) GENERATED ALWAYS AS (cantidad * precio_unitario_historico) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Restricciones de Clave Foránea
    CONSTRAINT fk_items_pedido_cabecera
        FOREIGN KEY (pedido_id)
        REFERENCES pedidos(id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CONSTRAINT fk_items_pedido_variante
        FOREIGN KEY (variante_id)
        REFERENCES variantes_producto(id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,

    -- Restricciones
    CONSTRAINT chk_items_cantidad_positiva CHECK (cantidad > 0),
    CONSTRAINT chk_items_precio_historico_no_negativo CHECK (precio_unitario_historico >= 0)
);

COMMENT ON TABLE items_pedido IS 'Líneas detalladas de compra. Congela inmutablemente el precio histórico para auditoría contable';
COMMENT ON COLUMN items_pedido.id IS 'Identificador único de la línea de pedido';
COMMENT ON COLUMN items_pedido.pedido_id IS 'FK referenciando a pedidos(id). ON DELETE RESTRICT protege la inmutabilidad histórica';
COMMENT ON COLUMN items_pedido.variante_id IS 'FK referenciando a variantes_producto(id). ON DELETE RESTRICT impide borrar variantes ya vendidas';
COMMENT ON COLUMN items_pedido.cantidad IS 'Cantidad de unidades físicas adquiridas en la transacción';
COMMENT ON COLUMN items_pedido.precio_unitario_historico IS 'Precio congelado al momento exacto del checkout; inmune a futuras alzas de catálogo';
COMMENT ON COLUMN items_pedido.subtotal_linea IS 'Columna generada almacenada (STORED) calculada como cantidad * precio_unitario_historico';
COMMENT ON COLUMN items_pedido.created_at IS 'Marca temporal de registro de la línea';

-- ----------------------------------------------------------------------------
-- 4.3. TABLA: pagos_sinpe (Seguridad y Conciliación Anti-Fraude)
-- ----------------------------------------------------------------------------
CREATE TABLE pagos_sinpe (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pedido_id UUID NOT NULL,
    numero_referencia VARCHAR(100) NOT NULL,
    telefono_emisor VARCHAR(20) NOT NULL,
    monto_transferido NUMERIC(12,2) NOT NULL,
    comprobante_url VARCHAR(255) NOT NULL,
    estado_validacion estado_validacion_pago_enum NOT NULL DEFAULT 'pendiente',
    fecha_registro TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Restricciones de Clave Foránea
    CONSTRAINT fk_pagos_sinpe_pedido
        FOREIGN KEY (pedido_id)
        REFERENCES pedidos(id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,

    -- Barrera Anti-Fraude Estricta a Nivel de Motor
    CONSTRAINT uq_pagos_sinpe_numero_referencia UNIQUE (numero_referencia),
    CONSTRAINT chk_pagos_monto_transferido_positivo CHECK (monto_transferido > 0),
    CONSTRAINT chk_pagos_referencia_not_empty CHECK (char_length(trim(numero_referencia)) > 0)
);

COMMENT ON TABLE pagos_sinpe IS 'Registro de conciliación bancaria SINPE Móvil con barrera matemática anti-fraude';
COMMENT ON COLUMN pagos_sinpe.id IS 'Identificador universal único del comprobante registrado';
COMMENT ON COLUMN pagos_sinpe.pedido_id IS 'FK a pedidos(id); pedido comercial que se pretende amortizar o liquidar';
COMMENT ON COLUMN pagos_sinpe.numero_referencia IS 'Referencia bancaria única del voucher o SMS. UNIQUE impide reutilizar comprobantes para estafas';
COMMENT ON COLUMN pagos_sinpe.telefono_emisor IS 'Número de teléfono desde el que se emitió el pase de fondos SINPE';
COMMENT ON COLUMN pagos_sinpe.monto_transferido IS 'Monto neto reportado por el cliente en moneda nacional';
COMMENT ON COLUMN pagos_sinpe.comprobante_url IS 'Enlace al archivo de imagen o captura almacenado en bucket seguro';
COMMENT ON COLUMN pagos_sinpe.estado_validacion IS 'Estado de auditoría financiera (pendiente, aprobado, rechazado) tipificado por ENUM';
COMMENT ON COLUMN pagos_sinpe.fecha_registro IS 'Marca temporal inmutable en que el cliente subió el comprobante';
COMMENT ON COLUMN pagos_sinpe.updated_at IS 'Marca temporal de cuando el administrador u OCR validó la transacción';

-- ============================================================================
-- 5. ASIGNACIÓN DE TRIGGERS PARA AUDITORÍA DE TIMESTAMP (updated_at)
-- ============================================================================

CREATE TRIGGER trg_categorias_updated_at
    BEFORE UPDATE ON categorias
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at_timestamp();

CREATE TRIGGER trg_marcas_updated_at
    BEFORE UPDATE ON marcas
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at_timestamp();

CREATE TRIGGER trg_productos_updated_at
    BEFORE UPDATE ON productos
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at_timestamp();

CREATE TRIGGER trg_variantes_updated_at
    BEFORE UPDATE ON variantes_producto
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at_timestamp();

CREATE TRIGGER trg_imagenes_updated_at
    BEFORE UPDATE ON imagenes_producto
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at_timestamp();

CREATE TRIGGER trg_pedidos_updated_at
    BEFORE UPDATE ON pedidos
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at_timestamp();

CREATE TRIGGER trg_pagos_sinpe_updated_at
    BEFORE UPDATE ON pagos_sinpe
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at_timestamp();

-- ============================================================================
-- 6. ESTRATEGIA DE ÍNDICES DE ALTO RENDIMIENTO (B-TREE, PARCIALES Y GIN JSONB)
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 6.1. Índices para Búsquedas por Slugs y Soft-Delete (Catálogo Activo)
-- ----------------------------------------------------------------------------
-- Optimiza consultas del storefront: WHERE slug = $1 AND is_active = TRUE
CREATE INDEX idx_categorias_slug_active 
    ON categorias (slug) 
    WHERE is_active = TRUE;

CREATE INDEX idx_marcas_slug_active 
    ON marcas (slug) 
    WHERE is_active = TRUE;

CREATE INDEX idx_productos_slug_active 
    ON productos (slug) 
    WHERE is_active = TRUE;

CREATE INDEX idx_variantes_sku_active 
    ON variantes_producto (sku) 
    WHERE is_active = TRUE;

-- ----------------------------------------------------------------------------
-- 6.2. Índices B-Tree en Claves Foráneas (Aceleración de JOINs y Cascada)
-- ----------------------------------------------------------------------------
CREATE INDEX idx_productos_categoria_id 
    ON productos (categoria_id);

CREATE INDEX idx_productos_marca_id 
    ON productos (marca_id);

CREATE INDEX idx_variantes_producto_id 
    ON variantes_producto (producto_id);

CREATE INDEX idx_imagenes_producto_id 
    ON imagenes_producto (producto_id);

CREATE INDEX idx_imagenes_variante_id 
    ON imagenes_producto (variante_id);

CREATE INDEX idx_items_pedido_pedido_id 
    ON items_pedido (pedido_id);

CREATE INDEX idx_items_pedido_variante_id 
    ON items_pedido (variante_id);

CREATE INDEX idx_pagos_sinpe_pedido_id 
    ON pagos_sinpe (pedido_id);

-- ----------------------------------------------------------------------------
-- 6.3. Índices Especializados GIN para Campos JSONB
-- ----------------------------------------------------------------------------
-- Indexación GIN especializada (jsonb_path_ops) para atributos dinámicos
-- Optimiza consultas de contención: WHERE atributos @> '{"sabor": "Chocolate"}'
CREATE INDEX idx_variantes_atributos_gin 
    ON variantes_producto 
    USING gin (atributos jsonb_path_ops);

-- Indexación GIN general para inspección de estructura y claves de dirección
-- Optimiza filtros por provincia/cantón: WHERE direccion_envio ->> 'provincia' = 'San Jose'
CREATE INDEX idx_pedidos_direccion_envio_gin 
    ON pedidos 
    USING gin (direccion_envio);

-- ----------------------------------------------------------------------------
-- 6.4. Índices Operativos para Órdenes, Pagos y Galería
-- ----------------------------------------------------------------------------
-- Búsqueda de órdenes por estado y fecha reciente para tableros de despacho
CREATE INDEX idx_pedidos_estado_fecha 
    ON pedidos (estado_pedido, fecha_creacion DESC);

-- Búsqueda de órdenes por WhatsApp para Guest Checkout y atención al cliente
CREATE INDEX idx_pedidos_cliente_whatsapp 
    ON pedidos (cliente_whatsapp);

-- Búsqueda de pagos SINPE pendientes de conciliación
CREATE INDEX idx_pagos_sinpe_pendientes 
    ON pagos_sinpe (estado_validacion, fecha_registro DESC) 
    WHERE estado_validacion = 'pendiente';

-- Una sola imagen principal por producto (garantía a nivel de motor) y búsqueda
-- rápida de la portada. Al haber como máximo una fila por producto, ordenar por
-- 'orden' ya no aporta: sustituye al antiguo idx_imagenes_principal.
CREATE UNIQUE INDEX uq_imagenes_principal_por_producto
    ON imagenes_producto (producto_id)
    WHERE is_principal = TRUE;

-- ============================================================================
-- FIN DEL SCRIPT DDL
-- ============================================================================
