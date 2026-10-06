# Respaldo del Proyecto — Motor E-Commerce Headless

> **Propósito de este documento:** ser la memoria completa del proyecto. Permite que
> cualquier persona (o una nueva sesión de asistente de IA) retome el trabajo sin
> contexto previo. Reúne qué se construyó, cómo funciona, por qué se tomó cada decisión,
> qué se verificó, qué problemas aparecieron y qué falta.
>
> **Fecha de corte:** 6 de octubre de 2026 · **Commit de referencia:** `97ea990`
> (rama `main`) · **Estado:** 4 sprints cerrados; 59/59 tests en verde.
>
> Documentos complementarios (más profundos en su tema):
> - [`arquitectura_backend_sprint3.md`](arquitectura_backend_sprint3.md): diseño interno y flujo de la información (didáctico).
> - [`infraestructura_produccion_sprint4.md`](infraestructura_produccion_sprint4.md): manual de operaciones.

---

## Índice

1. [Ficha rápida](#1-ficha-rápida)
2. [Contexto de negocio](#2-contexto-de-negocio)
3. [Cronología del trabajo](#3-cronología-del-trabajo)
4. [Stack y versiones exactas](#4-stack-y-versiones-exactas)
5. [Estructura del repositorio](#5-estructura-del-repositorio)
6. [Modelo de datos](#6-modelo-de-datos)
7. [Arquitectura en capas](#7-arquitectura-en-capas)
8. [API: las 42 operaciones](#8-api-las-42-operaciones)
9. [Reglas de negocio](#9-reglas-de-negocio)
10. [Concurrencia e integridad](#10-concurrencia-e-integridad)
11. [Seguridad](#11-seguridad)
12. [Errores y su traducción a HTTP](#12-errores-y-su-traducción-a-http)
13. [Configuración (variables de entorno)](#13-configuración-variables-de-entorno)
14. [Operación: comandos de referencia](#14-operación-comandos-de-referencia)
15. [Pruebas y CI](#15-pruebas-y-ci)
16. [Logging estructurado](#16-logging-estructurado)
17. [Registro de decisiones de diseño](#17-registro-de-decisiones-de-diseño)
18. [Problemas encontrados y cómo se resolvieron](#18-problemas-encontrados-y-cómo-se-resolvieron)
19. [Estado del entorno local](#19-estado-del-entorno-local)
20. [Pendientes y próximos pasos](#20-pendientes-y-próximos-pasos)
21. [Cómo retomar el proyecto](#21-cómo-retomar-el-proyecto)

---

## 1. Ficha rápida

| Aspecto | Valor |
|---|---|
| Nombre | Motor E-Commerce Headless (`motor-ecommerce` en `pyproject.toml`) |
| Ubicación | `C:\Users\je-qu\motor_ecommerce` |
| Repositorio | https://github.com/ystewuart-hash/motor_ecommerce · rama `main` · commit inicial `97ea990` (64 archivos, 8 035 líneas) + commit de este respaldo |
| Autor de los commits | `Yordy Quesada <ystewuart@gmail.com>` (configurado solo en este repositorio) |
| Rol del dueño del proyecto | Tech Lead; aprueba las decisiones de diseño. Idioma de trabajo: español |
| Stack | Python 3.14 · FastAPI · SQLAlchemy 2.1 · Pydantic V2 · PostgreSQL 14+ (probado con 17) |
| Tipo de API | *Headless*: solo JSON; el frontend vive en otro origen |
| Dominio | Tienda de suplementos deportivos en Costa Rica (colones, provincias, SINPE Móvil, WhatsApp) |
| Tamaño | 32 rutas / 42 operaciones HTTP, 8 tablas, 2 ENUMs, 18 índices, 7 triggers |
| Calidad | 59 tests pytest contra PostgreSQL real · ruff sin errores · **CI de GitHub Actions en verde** (primera corrida: lint 7 s, tests 58 s) |

---

## 2. Contexto de negocio

- **Qué vende:** suplementos (proteínas, creatinas, pre-entrenos) de marcas como Optimum
  Nutrition y Dymatize. Cada **producto** tiene **variantes** (SKU) con atributos libres
  en JSONB (sabor, peso, porciones…), precio y stock propios.
- **Cómo compra el cliente:** *guest checkout* (sin cuenta). Deja nombre, **WhatsApp**
  (canal principal de contacto), email opcional y dirección (provincia, cantón, distrito,
  señas exactas, coordenadas opcionales).
- **Cómo paga:** **SINPE Móvil** (transferencia instantánea costarricense). El cliente
  reporta el comprobante (número de referencia, teléfono emisor, monto, captura) y un
  administrador lo concilia. Si los pagos aprobados cubren el total, el pedido pasa a
  preparación.
- **Moneda:** colones (CRC), `NUMERIC(12,2)`.
- **Envío:** tarifa por provincia (estática por ahora; la logística avanzada queda para
  otro sprint).
- **Principio rector, definido por el Tech Lead:** *el backend es la única fuente de
  verdad*. El cliente nunca envía precios, totales ni estados; solo `variante_id` y
  `cantidad`.

---

## 3. Cronología del trabajo

Todo el trabajo se hizo entre el 5 y el 6 de octubre de 2026, en sesiones con un
asistente de IA (Claude Code), a partir del DDL (`init.sql`) escrito por el Tech Lead.

### Punto de partida

El proyecto tenía `init.sql` (DDL completo de 8 tablas), `database.py` (engine, `SessionLocal`,
`Base = declarative_base()`, `get_db`), un `main.py` con un *health check*, carpetas
`models/`, `routers/` y `schemas/` vacías, un `.env` con `DATABASE_URL` y un `venv` con
FastAPI, SQLAlchemy 2.1.3, Pydantic 2.13 y psycopg2-binary.

### Sprint 1 — Modelos ORM

- Traducción de las 8 tablas a SQLAlchemy 2.x tipado (`Mapped` / `mapped_column`) en
  `models/catalogo.py` y `models/transacciones.py`, más `models/mixins.py` (PK UUID y
  timestamps).
- Tipos nativos: `UUID(as_uuid=True)`, `JSONB` con `MutableDict` (detecta cambios
  in-place), `postgresql.ENUM(..., create_type=False)` con `values_callable` (persiste
  los valores en minúscula), `Computed` para `subtotal_linea`, `FetchedValue` para el
  `updated_at` mantenido por trigger.
- Relaciones bidireccionales con `passive_deletes` coherente con las FK del DDL
  (RESTRICT, SET NULL, CASCADE).
- Verificado: los mappers se configuran y el DDL que generan coincide con `init.sql`.

### Sprint 2 — Schemas, servicios de checkout y routers

- **Schemas Pydantic V2** (`schemas/`): patrón `Base` / `Create` / `Update` / `Response`,
  `from_attributes=True` en las respuestas, `extra="forbid"` en las entradas,
  validaciones que replican los `CHECK` del DDL, `UpdateSchema` que rechaza `null` en
  columnas NOT NULL.
- **Capa `services/`** (pedida por el Tech Lead: lógica y bloqueos fuera de los routers):
  checkout con `SELECT … FOR UPDATE`, máquina de estados del pedido, devolución de stock
  al cancelar, vencimiento de pedidos impagos, conciliación SINPE, CRUD de catálogo.
- **Envío:** tabla por provincia, aprobada por el Tech Lead como solución estática.
- **Routers** separados por público y admin; admin protegido inicialmente con una API key
  (`X-Admin-Key`), luego reemplazada por JWT en el Sprint 3.
- **Errores** centralizados en `errores.py`.
- **Prueba de concurrencia real:** se instaló `pgembed` (PostgreSQL embebido) tras revisar
  su código. Resultado: el checkout ingenuo vendió 12 unidades de 1 disponible; el real,
  exactamente 1.

### Sprint 3 — Ajustes críticos, JWT, seed y documentación

- Se quitó `CREATE EXTENSION pgcrypto` de `init.sql` (`gen_random_uuid()` es nativo desde PG13).
- **Idempotencia** (`pedidos.clave_idempotencia` UNIQUE + header `Idempotency-Key`).
  Se detectó y corrigió un caso borde (doble clic sobre las últimas unidades).
- **Privacidad del seguimiento:** `GET /pedidos/{id}` exige `?ultimos4=` del WhatsApp → 403.
- **Imagen principal única** garantizada por índice único parcial.
- **`.gitignore`** (excluye `.env` y `venv/`).
- **JWT** (`core/security.py`, `core/config.py`, `routers/auth.py`): HS256, Argon2id,
  credenciales del admin en `.env`.
- **Seed** `scripts/seed_catalogo.py` (idempotente).
- **Documento** `docs/arquitectura_backend_sprint3.md`.
- Migración SQL manual para bases existentes (hoy en `alembic/legacy/`).

### Sprint 4 — Preparación para producción

- **Alembic** (migración `0001` equivalente objeto por objeto a `init.sql`, incluidos los 78 comentarios).
- **Rate limiting** en dos capas (slowapi por IP + contador de fallos por recurso).
- **APScheduler**: job horario que libera el stock de carritos abandonados, con advisory lock.
- **pytest** (59 tests, fixtures) + **GitHub Actions**.
- **structlog**: logs JSON con `request_id` y eventos de negocio y concurrencia.
- **Documento** `docs/infraestructura_produccion_sprint4.md`.

### Cierre

- `git init -b main` y commit inicial `97ea990`.
- Remoto `origin` → `https://github.com/ystewuart-hash/motor_ecommerce.git` y `git push -u origin main`
  (había un `origin` con la URL de ejemplo `<tu-usuario>`; se corrigió con `git remote set-url`).
- Este respaldo (`docs/respaldo_proyecto.md`).

---

## 4. Stack y versiones exactas

Versiones instaladas en `venv` (Python **3.14.4**) al cierre:

| Paquete | Versión | Uso |
|---|---|---|
| fastapi | 0.142.2 | Framework web (sobre starlette 1.7.0) |
| uvicorn | 0.54.0 | Servidor ASGI |
| SQLAlchemy | 2.1.3 | ORM (estilo 2.0 tipado) |
| pydantic / pydantic-settings | 2.13.5 / 2.15.0 | Schemas y configuración |
| python-dotenv | 1.2.4 | Carga de `.env` |
| psycopg (+ psycopg-binary) | 3.3.6 | Driver PostgreSQL v3 (el que usa la app) |
| psycopg2-binary | 2.9.13 | Instalado de origen; **ya no se usa** (no está en requirements) |
| alembic | 1.20.0 | Migraciones |
| PyJWT | 2.15.1 | Tokens JWT |
| pwdlib (+ argon2-cffi 25.1.0) | 0.3.1 | Hash Argon2id |
| python-multipart | 0.0.32 | Formulario OAuth2 de login |
| slowapi (+ limits 5.8.0) | 0.1.10 | Rate limiting |
| APScheduler | 3.11.3 | Tareas programadas |
| structlog | 26.1.0 | Logging estructurado |
| pytest | 9.1.1 | Tests (dev) |
| ruff | 0.16.10 | Linter (dev) |
| pgembed | 0.2.0 | PostgreSQL embebido para tests locales (dev) |

`requirements.txt` fija las de producción y `requirements-dev.txt` agrega pytest, ruff y
pgembed. `pyproject.toml` declara `requires-python = ">=3.14"` y configura pytest y ruff.

---

## 5. Estructura del repositorio

```
motor_ecommerce/                         (líneas)
├── main.py                       121   App FastAPI: lifespan (scheduler), logging, limiter, middleware, CORS, routers, /salud
├── database.py                    33   Engine (pool_pre_ping), SessionLocal, Base, get_db
├── dependencies.py                55   DbSession, verificar_admin (JWT Bearer), PaginacionDep
├── errores.py                    158   Excepciones → HTTP (dominio, BD, seguridad, 429)
├── init.sql                      485   DDL documentado (referencia; la fuente de verdad es Alembic)
├── alembic.ini / alembic/              Migraciones
│   ├── env.py                     80   URL desde DATABASE_URL; compara tipos y defaults; excluye comentarios
│   ├── versions/2026_10_06_0001_esquema_inicial.py   339   Esquema completo (ENUMs, función, triggers, comentarios)
│   └── legacy/001_sprint3_idempotencia_imagen_principal.sql   37   Para bases previas al Sprint 3
├── core/                               Infraestructura transversal
│   ├── config.py                  58   Settings (pydantic-settings), get_settings() cacheado
│   ├── security.py               203   Argon2id, JWT, autenticar_admin; CLI hash/secreto
│   ├── rate_limit.py             107   Limiter slowapi + limitar_fallos()
│   ├── scheduler.py              152   Job liberar_stock_vencido, advisory lock, EstadoJob
│   └── logs.py                   137   configurar_logging() (structlog) + middleware_logging
├── models/                             ORM
│   ├── mixins.py                  48   UUIDPrimaryKeyMixin, TimestampMixin
│   ├── catalogo.py               268   Categoria, Marca, Producto, VarianteProducto, ImagenProducto
│   └── transacciones.py          278   Pedido, ItemPedido, PagoSinpe, EstadoPedido, EstadoValidacionPago
├── schemas/                            Pydantic V2
│   ├── base.py                    65   BaseSchema, UpdateSchema, ResponseSchema, tipos (Slug, Monto…)
│   ├── catalogo.py               206   CRUD de catálogo + AjusteStock
│   ├── transacciones.py          180   Pedido/Item/Pago, DireccionEnvio, Provincia
│   ├── auth.py                    19   TokenResponse, SesionResponse
│   └── sistema.py                 27   JobEstadoResponse, SaludResponse
├── services/                           Lógica de negocio (sin HTTP)
│   ├── excepciones.py             35   Excepciones de dominio + restriccion_violada()
│   ├── bloqueos.py               122   FOR UPDATE ordenado, lock_timeout, medición de esperas
│   ├── checkout.py               208   ★ carrito → pedido (concurrencia + idempotencia)
│   ├── pedidos.py                189   Estados, cancelación, reposición de stock, vencidos, seguimiento
│   ├── pagos.py                   98   Registro y conciliación SINPE
│   ├── envio.py                   29   Tarifa por provincia
│   └── catalogo.py               281   CRUD genérico y consultas del storefront
├── routers/
│   ├── catalogo.py               100   Público: catálogo
│   ├── checkout.py                92   Público: pedidos, seguimiento, pagos
│   ├── auth.py                    48   Login y sesión
│   ├── admin_catalogo.py         169   /admin catálogo
│   ├── admin_pedidos.py           63   /admin pedidos y pagos
│   └── admin_sistema.py           49   /admin/sistema jobs
├── scripts/
│   ├── seed_catalogo.py          222   Datos iniciales (idempotente)
│   └── generar_migracion.py       62   Autogenerate de Alembic contra un PostgreSQL desechable
├── tests/                              59 tests (ver sección 15)
├── docs/                               Documentación (este archivo y los de sprint 3 y 4)
├── .github/workflows/backend.yml  94   CI: lint → migraciones (SQL offline) → pytest
├── pyproject.toml                 55   Config de pytest y ruff
├── requirements.txt / requirements-dev.txt
├── .env.example                   41   Plantilla de configuración (sin secretos)
└── .gitignore                     48   Excluye .env, venv/, cachés, logs
```

**No versionados** (por `.gitignore`): `.env`, `venv/`, `__pycache__/`, `.ruff_cache/`.

---

## 6. Modelo de datos

### 6.1 Diagrama

```mermaid
erDiagram
    categorias ||--o{ productos : "RESTRICT"
    marcas |o--o{ productos : "SET NULL"
    productos ||--o{ variantes_producto : "CASCADE"
    productos ||--o{ imagenes_producto : "CASCADE"
    variantes_producto |o--o{ imagenes_producto : "CASCADE"
    pedidos ||--o{ items_pedido : "RESTRICT"
    variantes_producto ||--o{ items_pedido : "RESTRICT"
    pedidos ||--o{ pagos_sinpe : "RESTRICT"
```

Todas las tablas usan PK `UUID DEFAULT gen_random_uuid()` y timestamps `TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP`.
Las que tienen `updated_at` lo actualizan con el trigger `set_updated_at_timestamp()`
(7 triggers `trg_*_updated_at`).

### 6.2 Tablas

| Tabla | Columnas principales | Restricciones destacadas |
|---|---|---|
| `categorias` | nombre(100), slug(100), is_active | `uq_categorias_slug`, slug `^[a-z0-9]+(?:-[a-z0-9]+)*$`, nombre no vacío |
| `marcas` | nombre, slug, logo_url, is_active | `uq_marcas_slug`, mismas reglas de slug y nombre |
| `productos` | categoria_id (RESTRICT), marca_id (SET NULL, nullable), nombre(150), slug(150), descripcion_html, is_active | `uq_productos_slug` |
| `variantes_producto` | producto_id (CASCADE), sku(50), atributos JSONB `{}`, precio NUMERIC(12,2), stock_disponible int, is_active | `uq_variantes_sku`, precio ≥ 0, **stock ≥ 0**, atributos debe ser objeto |
| `imagenes_producto` | producto_id (CASCADE), variante_id (CASCADE, nullable), url(255), is_principal, orden | orden ≥ 0, **una sola principal por producto** (índice único parcial) |
| `pedidos` | cliente_nombre, cliente_whatsapp(20), cliente_email, direccion_envio JSONB, subtotal_productos, costo_envio, monto_total, estado_pedido, **clave_idempotencia(100) UNIQUE**, fecha_creacion, updated_at | **`monto_total = subtotal + envío`**, WhatsApp `^[+0-9]{8,20}$`, montos ≥ 0, dirección debe ser objeto |
| `items_pedido` | pedido_id (RESTRICT), variante_id (RESTRICT), cantidad, precio_unitario_historico, **subtotal_linea GENERATED** | cantidad > 0, precio ≥ 0 |
| `pagos_sinpe` | pedido_id (RESTRICT), numero_referencia(100) **UNIQUE**, telefono_emisor, monto_transferido, comprobante_url, estado_validacion, fecha_registro, updated_at | monto > 0, referencia no vacía |

**ENUMs:**
- `estado_pedido_enum`: `pendiente_pago`, `en_preparacion`, `enviado`, `entregado`, `cancelado`, `reembolsado`.
- `estado_validacion_pago_enum`: `pendiente`, `aprobado`, `rechazado`.

En Python son `EstadoPedido` / `EstadoValidacionPago` (`StrEnum`, miembros en mayúscula y
valores en minúscula).

### 6.3 Índices (18)

| Tipo | Índices |
|---|---|
| Parciales por slug/SKU activos | `idx_categorias_slug_active`, `idx_marcas_slug_active`, `idx_productos_slug_active`, `idx_variantes_sku_active` (`WHERE is_active = TRUE`) |
| FK (B-tree) | `idx_productos_categoria_id`, `idx_productos_marca_id`, `idx_variantes_producto_id`, `idx_imagenes_producto_id`, `idx_imagenes_variante_id`, `idx_items_pedido_pedido_id`, `idx_items_pedido_variante_id`, `idx_pagos_sinpe_pedido_id` |
| GIN sobre JSONB | `idx_variantes_atributos_gin` (`jsonb_path_ops`, para `@>`), `idx_pedidos_direccion_envio_gin` |
| Operativos | `idx_pedidos_estado_fecha` (estado, fecha DESC), `idx_pedidos_cliente_whatsapp`, `idx_pagos_sinpe_pendientes` (parcial `WHERE estado_validacion='pendiente'`) |
| Único parcial | `uq_imagenes_principal_por_producto` (`producto_id WHERE is_principal`), que reemplazó al antiguo `idx_imagenes_principal` |

### 6.4 Fuente de verdad del esquema

- **Alembic** (`alembic/versions/`) desde el Sprint 4. Cadena: `<base> → 0001 (head)`.
- `init.sql` se mantiene como documentación legible (con `COMMENT ON` en tablas y columnas).
- `tests/test_migraciones.py` verifica en cada CI que ambos producen **el mismo esquema**:
  columnas, restricciones, índices, triggers, ENUMs, función y los 78 comentarios.
- Los comentarios **no** están en los modelos: viven en la migración. `env.py` excluye el
  plugin `alembic.autogenerate.comments` para que el autogenerate no proponga borrarlos.

### 6.5 Datos semilla (`scripts/seed_catalogo.py`)

Categorías: **Proteínas**, **Creatinas**, **Pre-entrenos**. Marcas: **Optimum Nutrition**, **Dymatize**.

| Producto (slug) | Marca | SKU | Atributos | Precio ₡ | Stock |
|---|---|---|---|---|---|
| Gold Standard 100% Whey (`gold-standard-100-whey`) | ON | ON-GSW-CHOC-2LB | Double Rich Chocolate · 2 lb | 29 900 | 25 |
| | | ON-GSW-CHOC-5LB | Double Rich Chocolate · 5 lb | 56 900 | 15 |
| | | ON-GSW-VAN-5LB | Vanilla Ice Cream · 5 lb | 56 900 | 10 |
| ISO100 Hydrolyzed (`iso100-hydrolyzed`) | Dymatize | DYM-ISO-FUDGE-1.6LB | Fudge Brownie · 1.6 lb | 36 900 | 12 |
| | | DYM-ISO-FUDGE-5LB | Fudge Brownie · 5 lb | 79 900 | 8 |
| | | DYM-ISO-VAN-5LB | Gourmet Vanilla · 5 lb | 79 900 | 6 |
| Micronized Creatine Powder (`micronized-creatine-powder`) | ON | ON-CREA-300G | Sin sabor · 300 g | 17 900 | 30 |
| | | ON-CREA-600G | Sin sabor · 600 g | 29 900 | 20 |
| Creatine Monohydrate (`dymatize-creatine-monohydrate`) | Dymatize | DYM-CREA-500G | Sin sabor · 500 g | 24 900 | 18 |
| Gold Standard Pre-Workout (`gold-standard-pre-workout`) | ON | ON-PRE-BR-30 | Blue Raspberry · 30 porciones | 24 500 | 14 |
| | | ON-PRE-FP-30 | Fruit Punch · 30 porciones | 24 500 | 9 |

Cada producto recibe una imagen principal con URL **placeholder**
(`https://cdn.example.com/productos/<slug>/principal.webp`) que hay que reemplazar.
Los precios son de referencia: el Tech Lead debe validarlos.

---

## 7. Arquitectura en capas

```mermaid
flowchart TD
    C([Cliente]) -->|HTTP JSON| MW[middleware_logging<br/>request_id]
    MW --> R[routers/<br/>reciben y delegan]
    R --> S[schemas/<br/>validan la entrada]
    R --> D[dependencies.py<br/>sesión BD · JWT · paginación]
    R --> RL[core/rate_limit.py]
    R --> SV[services/<br/>reglas · cálculos · bloqueos]
    SV --> M[models/] --> DB[(PostgreSQL)]
    SV -. excepciones de dominio .-> E[errores.py → HTTP]
    SCH[[core/scheduler.py<br/>hilo APScheduler]] --> SV
```

- **Routers:** sin lógica de negocio; solo reciben, aplican límites y delegan.
- **Schemas:** validan forma y valores; replican los `CHECK` para dar 422 claros.
- **Services:** no conocen HTTP. Cada operación de escritura es una unidad de trabajo con
  `commit` propio; si algo falla, la sesión se descarta (rollback) al cerrar la request.
- **Errores:** los servicios lanzan `RecursoNoEncontrado`, `AccesoDenegado`,
  `ReglaNegocioInvalida`, `ConflictoNegocio` o `StockInsuficiente`, y `errores.py` los
  traduce a HTTP.
- **Defensa en profundidad:** las reglas críticas también están en PostgreSQL (`CHECK`,
  `UNIQUE`, FK, índices parciales).

El recorrido completo de un pedido, paso a paso y con diagramas de secuencia, está en
`arquitectura_backend_sprint3.md`.

---

## 8. API: las 42 operaciones

**Públicas (sin autenticación)**

| Método | Ruta | Descripción | Límite |
|---|---|---|---|
| GET | `/` | *Liveness* simple | — |
| GET | `/salud` | *Readiness*: BD + scheduler (503 si la BD cae) | — |
| GET | `/categorias`, `/categorias/{slug}` | Categorías activas | — |
| GET | `/marcas`, `/marcas/{slug}` | Marcas activas | — |
| GET | `/productos?categoria=&marca=` | Listado de productos activos (paginado) | — |
| GET | `/productos/{slug}` | Ficha: categoría, marca, variantes activas, imágenes | — |
| GET | `/variantes?producto_id=&atributos={json}` | Búsqueda por contención JSONB (`@>`, usa índice GIN) | — |
| POST | `/pedidos` | Checkout; header opcional `Idempotency-Key` → 201 (+ `Idempotent-Replayed: true` en repeticiones) | — |
| GET | `/pedidos/{id}?ultimos4=NNNN` | Seguimiento (403 si los dígitos no coinciden) | 30/min por IP + 10 fallos/día por pedido |
| POST | `/pagos` | Reportar comprobante SINPE | — |
| POST | `/auth/login` | Form OAuth2 → `{access_token, token_type, expires_in}` | 5/min por IP + 10 fallos/h por usuario |

**Con JWT Bearer de administrador**

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/auth/sesion` | Quién es el token y cuándo vence |
| GET, POST | `/admin/categorias`, `/admin/marcas`, `/admin/productos` | Listar (incluye inactivos) / crear |
| PATCH, DELETE | `/admin/categorias/{id}`, `/admin/marcas/{id}`, `/admin/productos/{id}` | Editar / borrado lógico (204) |
| GET | `/admin/productos/{id}` | Detalle con todas las variantes |
| POST / PATCH / DELETE | `/admin/variantes`, `/admin/variantes/{id}` | CRUD de variantes (PATCH bloquea la fila) |
| POST | `/admin/variantes/{id}/ajuste-stock` | Ajuste relativo `{"delta": ±n, "motivo"}` |
| POST / PATCH / DELETE | `/admin/imagenes`, `/admin/imagenes/{id}` | Imágenes (borrado físico) |
| GET | `/admin/pedidos?estado=` | Listado de pedidos |
| GET, PATCH | `/admin/pedidos/{id}` | Detalle / cambio de estado y corrección de datos |
| POST | `/admin/pedidos/cancelar-vencidos?horas=48` | Limpieza manual |
| GET | `/admin/pagos?estado=pendiente` | Cola de conciliación |
| PATCH | `/admin/pagos/{id}` | Aprobar o rechazar un comprobante |
| GET | `/admin/sistema/jobs` | Estado de los jobs programados |
| POST | `/admin/sistema/jobs/{job_id}/ejecutar` | Ejecutar un job ahora (202) |

Paginación común: `limit` (1–100, por defecto 50) y `offset`. Documentación interactiva
en `/docs` (con botón **Authorize**).

---

## 9. Reglas de negocio

### 9.1 Checkout (`services/checkout.py`)

1. Consolida líneas repetidas de la misma variante.
2. Si trae `Idempotency-Key` y ya existe un pedido con esa clave, lo devuelve (`fase=previa`).
3. `SET LOCAL lock_timeout = '5s'`.
4. `SELECT … FOR UPDATE OF variantes_producto … ORDER BY id`.
5. Vuelve a buscar la clave (`fase=tras_espera_de_lock`, la corrección del doble clic).
6. Valida: existe, variante activa y producto activo (→ 422); stock suficiente (→ 409
   con `errores[]` por SKU). Reporta **todos** los problemas a la vez.
7. Descuenta stock, congela `precio_unitario_historico`, calcula subtotal (`Decimal`,
   `ROUND_HALF_UP` a céntimos) y envío.
8. Inserta con estado `pendiente_pago` **explícito**. Si choca con UNIQUE de la clave →
   rollback y repetición (`fase=colision_unique`).
9. Un solo `COMMIT`.

**Límites anti-acaparamiento:** máximo 50 líneas por pedido y 100 unidades por línea.

### 9.2 Envío (`services/envio.py`)

| Provincias | Tarifa |
|---|---|
| San José, Alajuela, Cartago, Heredia (GAM) | ₡3 000 |
| Guanacaste, Puntarenas, Limón | ₡4 000 |

Valores **de referencia, a confirmar** por el negocio. La provincia se normaliza (sin
tildes ni mayúsculas: `"limon"` → `"Limón"`); una provincia desconocida da 422.

### 9.3 Máquina de estados (`services/pedidos.py`)

```
pendiente_pago → en_preparacion | cancelado
en_preparacion → enviado | cancelado
enviado        → entregado | reembolsado
entregado      → reembolsado
cancelado      → reembolsado
reembolsado    → (final)
```

- `→ en_preparacion` exige que los pagos aprobados sean ≥ `monto_total`.
- `→ reembolsado` exige al menos un pago aprobado.
- `→ cancelado` **repone el stock**. Un reembolso tras el envío no lo repone (se usa ajuste-stock).
- Datos de contacto editables en `pendiente_pago` y `en_preparacion`. La dirección, solo
  en `pendiente_pago`, y recalcula envío y total.
- Transición inválida → 409.

### 9.4 Pagos SINPE (`services/pagos.py`)

- Solo se registran pagos para pedidos en `pendiente_pago` (bloquea el pedido).
- `numero_referencia` UNIQUE: un comprobante no se puede reutilizar (→ 409).
- Conciliar: solo pagos `pendiente`, solo a `aprobado`/`rechazado`. Si los aprobados
  cubren el total, el pedido pasa **automáticamente** a `en_preparacion`.

### 9.5 Vencimiento de pedidos impagos

`cancelar_pedidos_vencidos(horas)`: `pendiente_pago` más antiguos que `horas`, **sin**
comprobantes pendientes ni aprobados, en lotes de 200 con `FOR UPDATE SKIP LOCKED`.
Repone el stock con un único bloqueo ordenado de todas las variantes del lote. Se
ejecuta cada hora vía scheduler (48 h por defecto) o a mano por el endpoint admin.

### 9.6 Catálogo

- Borrado **lógico** (`is_active=False`) en categorías, marcas, productos y variantes;
  físico solo en imágenes.
- El storefront solo muestra productos activos de categorías activas, y variantes activas.
- Una imagen solo puede asociarse a una variante del mismo producto (→ 422).
- Marcar una imagen como principal desmarca las demás del producto.
- `ajuste-stock` es relativo y atómico (bloquea la fila); se rechaza si dejaría el stock negativo.

---

## 10. Concurrencia e integridad

| Mecanismo | Dónde | Propósito |
|---|---|---|
| `SELECT … FOR UPDATE` | `services/bloqueos.py` | Bloqueo pesimista del stock |
| Orden global de locks | `pedidos → pagos_sinpe → variantes (ORDER BY id)` | Evitar deadlocks |
| `SET LOCAL lock_timeout = '5s'` | Toda transacción que bloquea | Nadie espera indefinidamente (55P03 → 409 + `Retry-After: 1`) |
| `populate_existing=True` | Consultas con lock | Leer el valor recién bloqueado, no uno cacheado |
| `FOR UPDATE SKIP LOCKED` | Vencimientos | Limpieza en paralelo sin estorbar al tráfico |
| `pg_try_advisory_lock(7302001)` | Job programado | Una sola ejecución entre N workers |
| `UNIQUE (clave_idempotencia)` | Pedidos | Red de seguridad de la idempotencia |
| Índice único parcial | Imágenes | Una portada por producto incluso con admins simultáneos |
| `CHECK`, FK RESTRICT | BD | Última línea de defensa |

**Resultados medidos contra PostgreSQL 17 real** (con 50 ms de retardo artificial dentro
de la sección crítica, para forzar los choques):

| Escenario | Resultado |
|---|---|
| Checkout **ingenuo** sin lock, 20 compradores × 1 unidad | Vendió **8 a 12** unidades (sobreventa; el `CHECK` no la detecta) |
| Checkout real, 20 compradores, stock 1 | 1 venta, 19 rechazos |
| 40 compradores, stock 10 | 10 ventas, stock 0 |
| 40 carritos cruzados `[X,Y]` / `[Y,X]` | 40 ventas, 0 deadlocks |
| 10 cancelaciones + 20 compras simultáneas | Invariante stock + vendidas = 20 |
| Fila retenida 8 s por otra transacción | Se rinde a los 5,0 s (55P03), stock intacto |
| 10 dobles clics, misma clave, últimas 2 unidades | 1 venta + 9 repeticiones, 0 "sin stock" |
| 8 admins marcando portada a la vez | Queda 1; 7 rechazados por el índice |

---

## 11. Seguridad

| Tema | Implementación |
|---|---|
| Autenticación admin | `POST /auth/login` (form OAuth2) → JWT **HS256**, 30 min, claims `sub`, `rol`, `iss=motor-ecommerce`, `iat`, `exp`, `jti` |
| Validación del token | `algorithms=["HS256"]` explícito (bloquea `alg:none` y confusión de algoritmo), `issuer`, claims requeridos, `rol == admin` |
| Contraseñas | Argon2id (`pwdlib`); `compare_digest` en el usuario + **hash señuelo** (el tiempo no revela si el usuario existe) |
| Credenciales | `ADMIN_USER` + `ADMIN_PASSWORD_HASH` (recomendado) o `ADMIN_PASSWORD` (dev, con warning) en `.env`. CLI: `python -m core.security hash` / `secreto` |
| Fallar cerrado | Sin `JWT_SECRET_KEY` (≥ 32 caracteres) o sin credenciales → `/admin` responde 503 |
| Protección de rutas | `dependencies=[Depends(verificar_admin)]` a nivel de router (no se puede olvidar) |
| 401 | Con `WWW-Authenticate: Bearer` (RFC 6750) |
| Rate limiting | Por IP (slowapi, ventana deslizante) + por recurso solo con fallos (ver 13) |
| Seguimiento público | UUID (no enumerable) + últimos 4 dígitos del WhatsApp, `compare_digest`, 10 fallos por día por pedido |
| Precios | Nunca vienen del cliente (`extra="forbid"`) |
| Logs | Sin datos personales, contraseñas, tokens ni query strings |
| Errores de BD | Nunca se expone el mensaje crudo de PostgreSQL |
| CORS | Lista explícita en `CORS_ORIGINS`; vacío = ninguno |
| Secretos en git | `.env` ignorado; `.env.example` sin valores reales. Se revisó el commit inicial: no contiene credenciales |

Tokens maliciosos probados (todos → 401): firma alterada, firmado con otra clave, vencido,
`alg=none` y rol distinto de admin.

---

## 12. Errores y su traducción a HTTP

| Origen | HTTP |
|---|---|
| Validación Pydantic | 422 |
| `RecursoNoEncontrado` | 404 |
| `AccesoDenegado` | 403 |
| `ReglaNegocioInvalida` | 422 |
| `ConflictoNegocio` / `StockInsuficiente` (con `errores[]`) | 409 |
| `TokenInvalido` / `CredencialesInvalidas` | 401 + `WWW-Authenticate: Bearer` |
| `ConfiguracionIncompleta` | 503 |
| `RateLimitExceeded` (slowapi) / `DemasiadosIntentos` | 429 + `Retry-After` (+ `X-RateLimit-*`) |
| `IntegrityError` 23505 / 23503 / 23514 | 409 / 422-409 / 422, con mensaje por nombre de restricción |
| `OperationalError` 55P03, 40P01, 40001 | 409 + `Retry-After: 1` |
| Otro `OperationalError` | 503 |

Mensajes por restricción (`MENSAJES_RESTRICCION` en `errores.py`): slugs y SKU
duplicados, referencia SINPE repetida, FK inexistentes, stock negativo, imagen principal
duplicada y clave de idempotencia usada.

---

## 13. Configuración (variables de entorno)

Se leen de `.env` o del entorno (`core/config.py`; `database.py` lee `DATABASE_URL`).

| Variable | Defecto | Notas |
|---|---|---|
| `DATABASE_URL` | — (obligatoria) | `postgresql://…` o `postgresql+psycopg://…` (en SQLAlchemy 2.1 ambas usan psycopg 3) |
| `ADMIN_USER` | — | |
| `ADMIN_PASSWORD_HASH` | — | Entre comillas simples (el hash contiene `$`) |
| `ADMIN_PASSWORD` | — | Solo desarrollo |
| `JWT_SECRET_KEY` | — | ≥ 32 caracteres |
| `JWT_EXPIRACION_MINUTOS` | 30 | |
| `CORS_ORIGINS` | vacío | Separados por comas |
| `RATE_LIMIT_HABILITADO` | true | |
| `RATE_LIMIT_STORAGE_URI` | `memory://` | **Redis** si hay más de un proceso |
| `RATE_LIMIT_LOGIN` | 5/minute | Por IP |
| `RATE_LIMIT_SEGUIMIENTO` | 30/minute | Por IP |
| `RATE_LIMIT_FALLOS_LOGIN` | 10/hour | Por usuario |
| `RATE_LIMIT_FALLOS_SEGUIMIENTO` | 10/day | Por pedido |
| `SCHEDULER_HABILITADO` | true | |
| `JOB_VENCIDOS_INTERVALO_MINUTOS` | 60 | |
| `PEDIDOS_VENCEN_HORAS` | 48 | |
| `LOG_NIVEL` | INFO | |
| `LOG_FORMATO` | json | `consola` en desarrollo |
| `LOG_UMBRAL_LOCK_LENTO_MS` | 100 | |
| `TEST_POSTGRES_URI` | — | Solo tests (servidor externo, usado en CI) |

**Estado del `.env` real al cierre:** solo contiene `DATABASE_URL`
(`postgresql://usuario:****@localhost:5432/ecommerce_db`). **Faltan** `ADMIN_USER`,
`ADMIN_PASSWORD_HASH` y `JWT_SECRET_KEY`: mientras no se agreguen, `/admin` responde 503.

---

## 14. Operación: comandos de referencia

Desde `C:\Users\je-qu\motor_ecommerce` (en Windows, `venv\Scripts\python.exe` en lugar de `python`):

```bash
# Instalar
python -m pip install -r requirements-dev.txt

# Secretos para el .env
python -m core.security secreto        # → JWT_SECRET_KEY
python -m core.security hash           # → ADMIN_PASSWORD_HASH

# Esquema (ver sección 6.4 y el manual del Sprint 4)
python -m alembic upgrade head         # base nueva o pendiente de migrar
python -m alembic stamp head           # base creada con el init.sql actual
python -m alembic check                # modelos == base
python -m alembic upgrade head --sql   # ver el SQL sin ejecutarlo

# Nueva migración (PostgreSQL desechable, no toca la base real)
python -m scripts.generar_migracion "descripcion" --rev-id 0002

# Datos iniciales
python -m scripts.seed_catalogo

# Servidor
python -m uvicorn main:app --reload                       # desarrollo
uvicorn main:app --workers 4 --proxy-headers --forwarded-allow-ips="<IPs del proxy>"   # producción

# Calidad
python -m pytest                       # 59 tests, ~25 s
python -m pytest -m "not lento"        # sin la prueba de 5 s de lock_timeout
python -m ruff check .
```

---

## 15. Pruebas y CI

### 15.1 Suite (59 tests en verde, estables en corridas repetidas)

| Archivo | Tests | Qué cubre |
|---|---|---|
| `test_api.py` | 18 | Login (ok/incorrecto/inexistente), sesión, sin token, 5 tokens maliciosos, checkout concurrente por HTTP (3×201 / 12×409), montos rechazados, Idempotency-Key por HTTP, clave inválida, seguimiento 422/403/200, pagos y conciliación, cancelar vencidos, portada, `/salud` |
| `test_migraciones.py` | 10 | Alembic ≡ init.sql (7 aspectos), sin deriva, downgrade/upgrade, SQL legado + stamp |
| `test_concurrencia.py` | 7 | Control con sobreventa, última unidad, stock limitado, carritos cruzados, cancelaciones, lock_timeout (+ log), espera lenta (+ log) |
| `test_rate_limit.py` | 7 | Límite por IP en login, bloqueo por usuario, éxito sin consumir cupo, bloqueo por pedido, seguimiento legítimo, límite por IP en seguimiento, endpoints sin límite |
| `test_idempotencia.py` | 5 | Doble clic simultáneo, reintento posterior, clave reutilizada, red de seguridad UNIQUE, sin clave |
| `test_scheduler.py` | 4 | Job cancela y libera, omitido por advisory lock, no propaga errores, endpoints de monitoreo |
| `test_logging.py` | 4 | Formato JSON, request_id sin query string, request_id generado, herencia en eventos de servicio |
| `test_catalogo.py` | 4 | Portadas simultáneas, portada desplaza, seed idempotente, varias imágenes no principales |

**Infraestructura de tests** (`tests/conftest.py`):
- En `pytest_configure` levanta PostgreSQL (pgembed local o `TEST_POSTGRES_URI`) y crea
  la base **con `alembic upgrade head`**, antes de importar la app.
- Fixtures: `url_bd`, `motor` (pool de 60), `Sesion`, `db`, `fabrica`,
  `retardo_en_lock`, `config` (sobrescribe la configuración solo durante un test), `api`
  (uvicorn real en un hilo), `token_admin` y `_rate_limit_limpio` (autouse).
- Marcadores: `demostracion` (control de sobreventa) y `lento` (lock_timeout).
- `pyproject.toml` convierte en error cualquier `DeprecationWarning` del código propio e
  ignora el de slowapi.

### 15.2 CI (`.github/workflows/backend.yml`)

`push` / `pull_request` → **lint** (`ruff check`) → **tests** con servicio `postgres:17`.
El job de tests instala dependencias, genera el SQL offline de Alembic, corre `pytest
--junitxml` y publica el artefacto `reporte-pytest` (JUnit + `migraciones.sql`, 14 días).
`concurrency` cancela corridas viejas de la misma rama.

**Primera corrida en GitHub** (commit `97ea990`, 6 oct 2026,
[run 37429125900](https://github.com/ystewuart-hash/motor_ecommerce/actions/runs/37429125900)):
**éxito en todos los pasos**. Lint 7 s; tests 58 s en total, de los cuales pytest tomó 22 s
contra el contenedor `postgres:17`. Es la confirmación de que la suite no depende de
pgembed ni de Windows.

> Ojo con `cancel-in-progress`: un push nuevo a la misma rama cancela la corrida en curso.
> Si necesitas el resultado de una corrida concreta, espera a que termine antes de volver a hacer push.

---

## 16. Logging estructurado

- `core/logs.py`: structlog + `ProcessorFormatter`. Una línea JSON por evento con
  `event`, `level`, `logger`, `timestamp` (UTC); los logs de uvicorn, APScheduler y
  SQLAlchemy también salen en JSON. Se elimina el `color_message` de uvicorn.
- `middleware_logging`: `request_id` (respeta `X-Request-ID` o genera uno; se devuelve
  en la respuesta), `metodo` y `ruta` vía contextvars, más un evento `request` con
  `status`, `duracion_ms` e `ip`. **No** registra la query string.
- **Eventos principales:** `request`, `lock_espera_lenta`, `lock_timeout`,
  `lock_deadlock`, `idempotencia_colision` (`fase`), `idempotencia_clave_reutilizada`,
  `pedido_creado`, `checkout_stock_insuficiente`, `pedido_estado_cambiado`,
  `stock_repuesto`, `pedidos_vencidos_cancelados`, `pago_registrado`, `pago_conciliado`,
  `login_exitoso` / `login_fallido`, `token_rechazado`, `rate_limit_excedido`,
  `rate_limit_fallo_registrado`, `rate_limit_bloqueo_por_fallos`, `job_inicio` / `fin` /
  `omitido` / `error`, `bd_error_operacional`, `seguridad_sin_configurar`,
  `admin_password_texto_plano`, `scheduler_iniciado`, `api_iniciada`.
- El catálogo con campos, niveles, consultas `jq` y alertas recomendadas está en el
  manual del Sprint 4 (sección 6).

---

## 17. Registro de decisiones de diseño

| # | Decisión | Por qué | Quién |
|---|---|---|---|
| D1 | El cliente nunca envía precios, totales ni estados | El backend es la única fuente de verdad; evita manipulación | Tech Lead |
| D2 | Lógica y bloqueos en `services/`; routers delgados | Separación de responsabilidades; probar sin HTTP | Tech Lead |
| D3 | Envío estático por provincia | Suficiente hasta modelar la logística | Tech Lead |
| D4 | Bloqueo **pesimista** (`FOR UPDATE`) y no optimista | En un *flash sale* el optimista reintenta en masa; el pesimista encola | Propuesta aprobada |
| D5 | Locks en una sola consulta con `ORDER BY id` y orden global de tablas | Elimina deadlocks por construcción | Propuesta aprobada |
| D6 | Stock **reservado** al crear el pedido, con vencimiento | Protege al cliente; los vencimientos evitan stock retenido para siempre | Propuesta aprobada |
| D7 | Límites de 50 líneas y 100 unidades por pedido | Evitar acaparar inventario con pedidos impagos | Propuesta |
| D8 | Idempotencia por header `Idempotency-Key` + columna UNIQUE | Estándar de la industria; segura ante carreras | Tech Lead |
| D9 | Seguimiento con UUID + últimos 4 dígitos (403) | Protege los datos personales del invitado | Tech Lead |
| D10 | JWT HS256 de corta duración, admin en `.env` | Paso intermedio antes de una tabla de usuarios | Tech Lead |
| D11 | Argon2id; `ADMIN_PASSWORD` en texto plano solo como alternativa de desarrollo | Cumple lo pedido sin renunciar al hashing | Propuesta |
| D12 | Fallar cerrado (503) ante configuración incompleta | Nunca dejar `/admin` abierto por error | Propuesta |
| D13 | Alembic como fuente de verdad; `init.sql` como documentación verificada por test | Evita deriva entre dos definiciones del esquema | Propuesta (Sprint 4) |
| D14 | Comentarios en la migración, excluidos del autogenerate | Si no, el autogenerate borraría los 78 comentarios | Propuesta (Sprint 4) |
| D15 | Rate limit en dos capas (IP + fallos por recurso) | Frena la fuerza bruta distribuida sin castigar al usuario legítimo | Propuesta (Sprint 4) |
| D16 | APScheduler dentro de la app + advisory lock | Sin infraestructura extra; seguro con N workers | Propuesta (Sprint 4) |
| D17 | Tests siempre contra PostgreSQL real (pgembed / contenedor) | `FOR UPDATE`, JSONB, ENUMs e índices parciales son lo que se prueba | Propuesta |
| D18 | Migraciones como paso de despliegue, no al arrancar la app | Varios workers migrarían a la vez | Propuesta (Sprint 4) |
| D19 | Logs a stdout en JSON, sin datos personales | 12-factor; agregables y aptos para privacidad | Propuesta (Sprint 4) |

---

## 18. Problemas encontrados y cómo se resolvieron

| Momento | Problema | Resolución |
|---|---|---|
| Sprint 2 | La app fallaba al importar `database.py`: no había módulo `psycopg` | Se instaló `psycopg[binary]` 3. **Causa real** (aclarada en este respaldo): SQLAlchemy 2.1 usa **psycopg 3 por defecto** para `postgresql://`; el `.env` usa `postgresql://` sin driver explícito. En su momento se dijo, por error, que el `.env` tenía `+psycopg` |
| Sprint 2 | No había PostgreSQL local ni Docker para probar | Se usó `pgembed` (wheel revisado antes de instalar; solo escucha en 127.0.0.1) |
| Sprint 2 | El estado inicial del pedido dependía del DEFAULT del servidor (`None` en memoria) | Se fija `estado_pedido=PENDIENTE_PAGO` explícitamente en el checkout |
| Sprint 3 | `pgcrypto` no venía en el PostgreSQL embebido | Se eliminó del DDL: `gen_random_uuid()` es nativo desde PG13 |
| Sprint 3 | **Doble clic sobre las últimas unidades** respondía "sin stock" aunque el pedido existía | Revisar la clave de idempotencia justo después de obtener los locks |
| Sprint 3 | Carpeta temporal vacía quedaba tras las pruebas | `atexit` LIFO registrado antes de pgembed |
| Sprint 4 | Defaults `now()` en modelos vs `CURRENT_TIMESTAMP` en DDL | Modelos alineados a `func.current_timestamp()` |
| Sprint 4 | Autogenerate no crea ENUMs (`create_type=False`), función ni triggers | Agregados a mano en la migración 0001 |
| Sprint 4 | **Los 78 comentarios del DDL** habrían sido borrados por el autogenerate en bases creadas con `init.sql` | Comentarios en la migración + plugin de comentarios excluido + test de equivalencia |
| Sprint 4 | Aviso "Computed default cannot be modified" en `alembic check` | Filtrado en `env.py` |
| Sprint 4 | ruff confundía la carpeta `alembic/` con la librería | `known-third-party = ["alembic"]` |
| Sprint 4 | `dataclasses.asdict` fallaba al copiar el `threading.Lock` del estado del job | Instantánea construida campo por campo |
| Sprint 4 | El trigger del job mostraba hora local | `IntervalTrigger(timezone="UTC")` |
| Sprint 4 | `capture_logs` no incluía el `request_id` | `capture_logs(processors=[merge_contextvars])` |
| Sprint 4 | El test de formato JSON dejaba el handler en un stream cerrado | Reconfiguración dentro de `capsys.disabled()` |
| Sprint 4 | `color_message` con códigos ANSI en los logs JSON de uvicorn | Procesador que lo elimina |

---

## 19. Estado del entorno local

- **Equipo:** Windows 11 Home; Python 3.14.4 en `motor_ecommerce\venv`.
- **PostgreSQL:** **no instalado localmente** (ni servicio ni Docker). La base real
  `ecommerce_db` del `.env` **nunca se pudo verificar**: no se sabe si existe ni con qué
  esquema. Todas las pruebas usaron PostgreSQL 17.9 embebido (pgembed) en carpetas
  temporales que se borran al terminar.
- **Git:** rama `main` sincronizada con `origin` (GitHub). Identidad configurada solo en
  este repositorio. `gh` (GitHub CLI) **no** está instalado; el estado del CI se consultó con
  la API pública de GitHub.
- **Otro proyecto en el equipo** (no relacionado): `C:\Users\je-qu\OneDrive\Documentos\Cowork\Primer Proyecto`,
  un sitio web en la rama `feature/full-website-modernization`, con un `Gastos_Viaje.csv`
  sin versionar.

---

## 20. Pendientes y próximos pasos

### Inmediatos (para poder operar)

1. **Completar el `.env`:** `ADMIN_USER`, `ADMIN_PASSWORD_HASH` y `JWT_SECRET_KEY` (ver sección 14).
2. **Base de datos real:** instalar o levantar PostgreSQL ≥ 14 y luego:
   base nueva → `alembic upgrade head`; creada con el `init.sql` actual → `alembic stamp head`;
   creada antes del Sprint 3 → `alembic/legacy/001…sql` y después `stamp head`. Luego, el seed.
3. **Activar *branch protection* sobre `main`** en GitHub (Settings → Branches), exigiendo
   los checks `Lint (ruff)` y `Tests (pytest + PostgreSQL 17)`.

### Del negocio (a validar por el Tech Lead)

4. Tarifas reales de envío (hoy ₡3 000 / ₡4 000 de referencia).
5. Precios del seed y URLs reales de imágenes (hoy `cdn.example.com`).
6. Límites del checkout (50 líneas / 100 unidades) y vencimiento de pedidos (48 h).

### Técnicos

| Prioridad | Tarea |
|---|---|
| Alta | Redis para el rate limiting con más de un worker o servidor (`limits[redis]`) |
| Alta | Dockerfile multi-stage + CD que ejecute `alembic upgrade head` antes de publicar |
| Media | Tabla `usuarios` con roles, refresh tokens y revocación por `jti` |
| Media | Persistir las ejecuciones del job (hoy el estado es por proceso) |
| Media | Endpoint admin para desbloquear contadores de rate limit |
| Media | Métricas Prometheus (`/metrics`) |
| Media | Agregar Redis al CI y un test con `redis://` |
| Baja | Logística avanzada (reemplazar `services/envio.py`) |
| Baja | Actualizar slowapi cuando soporte Python 3.16 (usa `asyncio.iscoroutinefunction`) |
| Baja | Desinstalar `psycopg2-binary` del venv (no se usa) |
| Baja | Validación de email con `EmailStr` (requiere `email-validator`) |

---

## 21. Cómo retomar el proyecto

**Checklist para una persona nueva:**

1. Leer este documento y luego `arquitectura_backend_sprint3.md` (diseño) e
   `infraestructura_produccion_sprint4.md` (operación).
2. `python -m pip install -r requirements-dev.txt`.
3. `python -m pytest`: debe dar **59 passed** sin instalar PostgreSQL (lo levanta pgembed).
4. Revisar la sección 20 y elegir el siguiente paso.

**Para retomarlo con un asistente de IA**, abrir la sesión en
`C:\Users\je-qu\motor_ecommerce` e indicarle:

> "Lee `docs/respaldo_proyecto.md`. Es el estado completo del proyecto Motor E-Commerce
> Headless al commit `97ea990`. Trabajo como Tech Lead, en español. Sigue las
> convenciones existentes: lógica en `services/`, routers delgados, esquema por Alembic
> (`python -m scripts.generar_migracion`), tests pytest contra PostgreSQL real y logs
> como eventos structlog. Corre `python -m pytest` y `python -m ruff check .` antes de
> dar algo por terminado."

**Convenciones del código a respetar:**

- Nombres de dominio en **español** (`crear_pedido`, `StockInsuficiente`); comentarios y
  docstrings en español explicando el *porqué*.
- Montos siempre `Decimal` / `NUMERIC(12,2)`, nunca `float`.
- Toda escritura concurrente sobre stock pasa por `services/bloqueos.py` respetando el
  orden global de locks.
- Las excepciones de dominio se traducen a HTTP solo en `errores.py`.
- Cada evento de log es un identificador `snake_case` estable con campos estructurados,
  sin datos personales.
- Cambios de esquema: modificar `models/`, generar la migración, revisarla, actualizar
  `init.sql` y correr `tests/test_migraciones.py`.
