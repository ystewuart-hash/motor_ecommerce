-- ============================================================================
-- Migración Sprint 3: idempotencia de checkout e imagen principal única
-- Aplica a bases creadas con el init.sql anterior. Las bases nuevas ya
-- incluyen estos cambios en init.sql.
--
-- Uso:  psql "$DATABASE_URL" -f migrations/001_sprint3_idempotencia_imagen_principal.sql
-- ============================================================================
BEGIN;

-- 1. Idempotencia del checkout
ALTER TABLE pedidos
    ADD COLUMN IF NOT EXISTS clave_idempotencia VARCHAR(100) NULL;

ALTER TABLE pedidos
    ADD CONSTRAINT uq_pedidos_clave_idempotencia UNIQUE (clave_idempotencia);

COMMENT ON COLUMN pedidos.clave_idempotencia IS 'Clave Idempotency-Key enviada por el cliente; UNIQUE impide duplicar pedidos y reservas de stock por reintentos o doble clic';

-- 2. Una sola imagen principal por producto.
--    Si ya hubiera duplicados, conserva como principal la de menor 'orden'.
UPDATE imagenes_producto AS i
SET is_principal = FALSE
WHERE i.is_principal
  AND EXISTS (
      SELECT 1 FROM imagenes_producto AS otra
      WHERE otra.producto_id = i.producto_id
        AND otra.is_principal
        AND (otra.orden, otra.id) < (i.orden, i.id)
  );

DROP INDEX IF EXISTS idx_imagenes_principal;

CREATE UNIQUE INDEX uq_imagenes_principal_por_producto
    ON imagenes_producto (producto_id)
    WHERE is_principal = TRUE;

COMMIT;
