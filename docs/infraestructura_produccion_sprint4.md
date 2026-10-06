# Infraestructura de Producción — Sprint 4

> **Manual de operaciones** del Motor E-Commerce Headless.
> Explica cómo desplegar y operar el servidor: migraciones con Alembic, límites del
> rate limiter, monitoreo del job de limpieza de carritos, pipeline de CI y lectura de
> los logs estructurados. Complementa a
> [`arquitectura_backend_sprint3.md`](arquitectura_backend_sprint3.md), que explica el
> diseño interno.

---

## Índice

1. [Panorama: qué se agregó en el Sprint 4](#1-panorama-qué-se-agregó-en-el-sprint-4)
2. [Migraciones con Alembic](#2-migraciones-con-alembic)
3. [Rate limiting](#3-rate-limiting)
4. [Job de limpieza de carritos abandonados](#4-job-de-limpieza-de-carritos-abandonados)
5. [Pruebas y CI/CD](#5-pruebas-y-cicd)
6. [Logs estructurados](#6-logs-estructurados)
7. [Puesta en producción](#7-puesta-en-producción)
8. [Runbook: síntomas, causas y acciones](#8-runbook-síntomas-causas-y-acciones)
9. [Referencia de variables de entorno](#9-referencia-de-variables-de-entorno)
10. [Limitaciones conocidas y próximos pasos](#10-limitaciones-conocidas-y-próximos-pasos)

---

## 1. Panorama: qué se agregó en el Sprint 4

| Necesidad | Solución | Dónde vive |
|---|---|---|
| Evolucionar el esquema sin scripts SQL manuales | **Alembic** | `alembic/`, `alembic.ini`, `scripts/generar_migracion.py` |
| Frenar fuerza bruta en login y seguimiento | **slowapi** + contador de fallos | `core/rate_limit.py` |
| Liberar el stock de carritos abandonados | **APScheduler** + advisory lock | `core/scheduler.py`, `routers/admin_sistema.py` |
| Detectar regresiones en cada push | **pytest** + **GitHub Actions** | `tests/`, `.github/workflows/backend.yml` |
| Saber qué pasa en producción | **structlog** (JSON) | `core/logs.py` + eventos en `services/` |

Así se ve un proceso del servidor en ejecución:

```mermaid
flowchart LR
    subgraph Proceso["Proceso uvicorn (cada worker)"]
        MW[middleware_logging<br/>request_id + evento 'request'] --> RL[slowapi<br/>límite por IP]
        RL --> EP[endpoint → servicios]
        SCH[[Hilo APScheduler<br/>job cada 60 min]]
    end
    Cliente((Cliente)) --> MW
    EP --> PG[(PostgreSQL)]
    SCH -->|pg_try_advisory_lock| PG
    RL <-->|contadores| ST[(memory:// o Redis)]
    EP -. contador de fallos .-> ST
    Proceso -->|JSON por stdout| LOGS[[Recolector de logs<br/>Docker / Loki / Datadog]]
```

---

## 2. Migraciones con Alembic

### 2.1 Conceptos en 1 minuto

- Una **migración** (o *revisión*) es un archivo Python en `alembic/versions/` con dos
  funciones: `upgrade()` aplica un cambio y `downgrade()` lo revierte.
- Cada revisión apunta a la anterior (`down_revision`): forman una cadena. La última es
  el **head**.
- Alembic guarda en la tabla **`alembic_version`** de la base qué revisión tiene
  aplicada. `upgrade head` ejecuta solo las que faltan.
- **Fuente de verdad:** desde este sprint el esquema lo define Alembic. `init.sql` queda
  como documentación legible; un test en CI verifica que ambos producen **exactamente**
  el mismo esquema (columnas, restricciones, índices, triggers, ENUMs, función y
  comentarios).

Estado actual de la cadena:

```
<base>  ──►  0001  esquema_inicial   (head)
```

La revisión `0001` se generó con `--autogenerate` contra una base vacía y se completó a
mano con lo que el autogenerate no detecta: los tipos ENUM, la función
`set_updated_at_timestamp()`, sus 7 triggers y los 78 `COMMENT ON`.

### 2.2 Comandos del día a día

La URL se toma de `DATABASE_URL` (`.env` o entorno); **nunca** se escribe en `alembic.ini`.

```bash
python -m alembic upgrade head        # aplica todo lo pendiente
python -m alembic current             # qué revisión tiene la base
python -m alembic history --verbose   # cadena completa de migraciones
python -m alembic downgrade -1        # revierte la última migración
python -m alembic upgrade head --sql  # NO toca la base: imprime el SQL que ejecutaría
python -m alembic check               # falla si models/ y la base no coinciden
```

> En Windows, usa `venv\Scripts\python.exe -m alembic …`.
> `--sql` (modo *offline*) es ideal para que un DBA revise el cambio antes de aplicarlo.

Cada migración corre en **su propia transacción** (`transaction_per_migration=True`).
PostgreSQL soporta DDL transaccional: si una migración falla a mitad de camino, se
revierte completa y el esquema queda como estaba.

### 2.3 ¿Qué hago con mi base? (tres escenarios)

| Tu base… | Comando |
|---|---|
| **No existe** (instalación nueva) | `CREATE DATABASE …` y luego `python -m alembic upgrade head` |
| Se creó con el **`init.sql` actual** (Sprint 3) | `python -m alembic stamp head` — la marca como al día, sin ejecutar nada |
| Se creó con el **`init.sql` anterior al Sprint 3** (sin `clave_idempotencia`) | 1. `psql "$DATABASE_URL" -f alembic/legacy/001_sprint3_idempotencia_imagen_principal.sql`<br/>2. `python -m alembic stamp head` |

Tras `stamp head`, comprueba que todo cuadra con `python -m alembic check`. Debe decir
`No new upgrade operations detected.`

> `stamp` solo escribe en `alembic_version`; no modifica tablas. Úsalo únicamente cuando
> sepas que el esquema real ya coincide con esa revisión.

### 2.4 Crear una migración nueva

1. Modifica los modelos en `models/` (por ejemplo, agrega una columna).
2. Genera la migración. El script levanta un PostgreSQL **desechable**, aplica las
   migraciones existentes y compara con los modelos; nunca toca tu base real:

   ```bash
   python -m scripts.generar_migracion "agrega telefono a marcas" --rev-id 0002
   ```

3. **Revisa el archivo generado.** El autogenerate es un borrador, no un oráculo:

   | El autogenerate **no** detecta… | Qué hacer |
   |---|---|
   | ENUMs nuevos (los modelos usan `create_type=False`) | Agrega `postgresql.ENUM(...).create(op.get_bind(), checkfirst=True)` |
   | Valores nuevos en un ENUM existente | `op.execute("ALTER TYPE … ADD VALUE '…'")` |
   | Funciones, triggers, vistas | `op.execute("CREATE …")` en `upgrade` y su `DROP` en `downgrade` |
   | Renombres de tabla o columna (los ve como *drop + add*: **pérdida de datos**) | Reemplaza por `op.alter_column(..., new_column_name=...)` / `op.rename_table` |
   | Comentarios (`COMMENT ON`) | Están excluidos a propósito: agrégalos con `op.execute` |
   | Migración de **datos** (rellenar una columna nueva) | Escríbela con `op.execute("UPDATE …")` |

4. Corre los tests: `pytest tests/test_migraciones.py`. Verifican que el ciclo
   `downgrade base` → `upgrade head` funciona y que no queda deriva entre modelos y base.
   Si cambiaste el esquema, **actualiza también `init.sql`** (el test de equivalencia te
   lo recordará).

### 2.5 Migrar en un despliegue

```mermaid
flowchart LR
    A[CI verde] --> B["python -m alembic upgrade head<br/>(paso único, antes del deploy)"]
    B --> C[Desplegar la nueva versión de la API]
    C --> D[Verificar /salud y logs]
```

- Ejecuta las migraciones **como un paso aparte y una sola vez** (un job de CI/CD o un
  contenedor *init*), **no** al arrancar la app: con varios workers, cada uno intentaría
  migrar a la vez.
- Prefiere cambios **compatibles hacia atrás** (*expand/contract*). Por ejemplo, para
  renombrar una columna: (1) agrega la nueva y escribe en ambas; (2) despliega;
  (3) migra los datos; (4) en un despliegue posterior, borra la vieja. Así la versión
  anterior de la API sigue funcionando mientras conviven.
- **Rollback:** `python -m alembic downgrade -1`, y luego despliega la versión anterior
  del código. Un `downgrade` que borra columnas **borra sus datos**: haz backup antes.

---

## 3. Rate limiting

### 3.1 Dos capas complementarias

| Capa | Qué cuenta | Clave | Frena | Variable |
|---|---|---|---|---|
| **Por IP** (slowapi) | **Todas** las peticiones | IP del cliente | Ráfagas desde un mismo origen | `RATE_LIMIT_LOGIN`, `RATE_LIMIT_SEGUIMIENTO` |
| **Por recurso** | Solo los **intentos fallidos** | Usuario (login) / pedido (seguimiento) | Fuerza bruta **distribuida** (muchas IPs atacando lo mismo) | `RATE_LIMIT_FALLOS_LOGIN`, `RATE_LIMIT_FALLOS_SEGUIMIENTO` |

¿Por qué dos capas? Un atacante con una botnet de 10 000 IPs pasa por debajo de
cualquier límite por IP, pero **todas** sus peticiones apuntan al mismo pedido o al
mismo usuario, y ese contador sí lo detiene. A la inversa, el contador por recurso solo
suma **fallos**: un cliente que refresca su seguimiento con los dígitos correctos nunca
se bloquea.

Valores por defecto:

| Endpoint | Por IP | Fallos por recurso | Efecto |
|---|---|---|---|
| `POST /auth/login` | 5/minuto | 10/hora por usuario | Un diccionario de contraseñas avanza a 10 intentos por hora |
| `GET /pedidos/{id}` | 30/minuto | 10/día por pedido | Adivinar 4 dígitos (10 000 combinaciones) llevaría unos 1 000 días |

Cuando el recurso está bloqueado, **ni siquiera el intento correcto pasa** hasta que la
ventana libera cupo: así el atacante no puede saber si acertó.

### 3.2 Qué recibe el cliente

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 54
X-RateLimit-Limit: 5
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1791302460

{"detail": "Demasiadas solicitudes (5 per 1 minute); intente más tarde"}
```

En el bloqueo por fallos, el `detail` dice *"Demasiados intentos fallidos; espere antes
de reintentar"* y `Retry-After` indica los segundos que faltan. El frontend debe leer
`Retry-After` y deshabilitar el botón durante ese tiempo.

Se usa ventana **deslizante** (*moving window*): no existe el "doble cupo" que permite
una ventana fija al cruzar el borde del minuto.

### 3.3 Cómo ajustar los límites

Los límites se leen de la configuración **en cada petición**: basta con cambiar la
variable de entorno y reiniciar el proceso. La sintaxis es `N/unidad`, con unidad
`second`, `minute`, `hour` o `day` (también `N per M minutes`).

```bash
# Ataque de diccionario en curso: endurecer el login
RATE_LIMIT_LOGIN=3/minute
RATE_LIMIT_FALLOS_LOGIN=5/hour

# Campaña con mucho tráfico (clientes refrescando su pedido): relajar por IP,
# sin tocar el contador de fallos, que es el que protege los 4 dígitos
RATE_LIMIT_SEGUIMIENTO=120/minute

# Desactivar por completo (solo para diagnóstico, nunca en producción)
RATE_LIMIT_HABILITADO=false
```

> **Cuidado con el bloqueo de usuario:** `RATE_LIMIT_FALLOS_LOGIN` también permite que
> un atacante bloquee **a propósito** al administrador fallando 10 veces. Es un
> compromiso consciente (mejor bloqueado que comprometido). Si ocurre, desbloquéalo (3.5).

### 3.4 Requisitos de infraestructura

**Detrás de un proxy o balanceador** (Nginx, ALB, Cloudflare) la IP que ve la app es la
del proxy. **Todos los clientes compartirían el mismo cupo.** Arranca uvicorn así:

```bash
uvicorn main:app --proxy-headers --forwarded-allow-ips="10.0.0.0/8"
```

`--forwarded-allow-ips` debe listar **solo** las IPs de tus proxies. Con `"*"`,
cualquiera podría falsificar su IP con un header `X-Forwarded-For`.

**Con varios workers o servidores**, `memory://` da a cada proceso sus propios
contadores: con 4 workers, el límite real se multiplica por 4. Usa Redis:

```bash
pip install "limits[redis]"
RATE_LIMIT_STORAGE_URI=redis://redis.interno:6379/0
```

### 3.5 Desbloquear a un usuario o un pedido

- **`memory://`:** reiniciar el proceso borra todos los contadores.
- **Redis:** borra solo las claves afectadas. El formato es
  `LIMITS:LIMITER/<capa>/<ámbito>/<clave>/<límite>`:

  ```bash
  # Desbloquear al usuario "admin"
  redis-cli --scan --pattern 'LIMITS:LIMITER/fallos/login/admin/*' | xargs -r redis-cli del
  # Desbloquear un pedido
  redis-cli --scan --pattern 'LIMITS:LIMITER/fallos/seguimiento/<pedido_id>/*' | xargs -r redis-cli del
  ```

### 3.6 Qué vigilar en los logs

| Evento | Nivel | Significado |
|---|---|---|
| `rate_limit_excedido` | warning | Una IP superó el límite por IP (`limite`, `ip`, `ruta`) |
| `rate_limit_fallo_registrado` | info | Intento fallido contado (`ambito`, `clave`, `intentos_restantes`) |
| `rate_limit_bloqueo_por_fallos` | warning | Recurso bloqueado (`ambito`, `clave`, `reintentar_en_s`) |
| `login_fallido` | warning | Credenciales incorrectas (`usuario`) |

**Señal de ataque:** muchos `rate_limit_bloqueo_por_fallos` con `ambito=seguimiento` para
pedidos distintos indican una enumeración en curso. Varios `login_fallido` desde
`request_id` con IPs diferentes indican un diccionario distribuido.

---

## 4. Job de limpieza de carritos abandonados

### 4.1 Qué hace y cuándo

El checkout **reserva** stock al crear el pedido. Si el cliente nunca paga, ese stock
quedaría retenido para siempre. El job `liberar_stock_vencido`:

1. Busca pedidos en `pendiente_pago` con más de `PEDIDOS_VENCEN_HORAS` (48 h).
2. **Respeta** los que tienen un comprobante SINPE pendiente o aprobado (hay dinero en juego).
3. Los cancela y devuelve su stock, en lotes de 200 (`FOR UPDATE SKIP LOCKED`, sin
   estorbar al tráfico).

**Calendario:** primera corrida **1 minuto** después del arranque (un reinicio no espera
una hora entera) y luego cada `JOB_VENCIDOS_INTERVALO_MINUTOS` (60), con ±30 s de
*jitter* para que varias instancias no consulten la base en el mismo segundo.

Configuración del scheduler y su razón de ser:

| Opción | Valor | Por qué |
|---|---|---|
| `coalesce` | `True` | Si el proceso estuvo suspendido y se perdieron 3 ventanas, corre **una** vez, no tres |
| `max_instances` | `1` | Nunca dos ejecuciones simultáneas en el mismo proceso |
| `misfire_grace_time` | 300 s | Tolera hasta 5 min de retraso antes de saltarse una ventana |
| `BackgroundScheduler` | hilo propio | El job es síncrono (SQLAlchemy); no bloquea las requests |

### 4.2 Varias instancias, una sola ejecución

Con `--workers 4` o con 3 réplicas del contenedor hay **N schedulers**. Antes de
trabajar, el job pide un **advisory lock** de PostgreSQL:

```sql
SELECT pg_try_advisory_lock(7302001);   -- true solo para el primero
```

El ganador ejecuta; los demás registran `job_omitido` y salen. El lock se libera al
terminar o si el proceso muere (PostgreSQL lo suelta al cerrarse la conexión).

### 4.3 Cómo monitorearlo

**1. Endpoint de estado** (requiere token de administrador):

```bash
curl -H "Authorization: Bearer $TOKEN" https://api.mitienda.com/admin/sistema/jobs
```

```json
[{
  "id": "liberar_stock_vencido",
  "nombre": "Cancelar pedidos impagos vencidos y liberar su stock",
  "activo": true,
  "intervalo": "interval[1:00:00]",
  "proxima_ejecucion": "2026-10-06T07:50:25Z",
  "ejecuciones": 12,
  "ultimo_inicio": "2026-10-06T06:50:24Z",
  "ultimo_fin": "2026-10-06T06:50:24Z",
  "ultimo_resultado": "ok",
  "ultima_duracion_ms": 29.9,
  "ultimos_cancelados": 3,
  "total_cancelados": 41,
  "ultimo_error": null
}]
```

> El estado vive **en la memoria de cada proceso**: con varios workers, la respuesta
> muestra el del worker que atendió la petición (puede decir `omitido` si otro worker
> ganó el lock). Para la visión global, usa los logs (abajo).

**2. Ejecutarlo ahora** (por ejemplo, tras corregir un error):

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
     https://api.mitienda.com/admin/sistema/jobs/liberar_stock_vencido/ejecutar   # → 202
```

**3. Health check:** `GET /salud` responde `"scheduler": "activo" | "detenido" | "deshabilitado"`.

**4. Logs:** cada corrida emite:

| Evento | Campos | Lectura |
|---|---|---|
| `job_inicio` | `job`, `horas` | Esta instancia obtuvo el lock y empieza |
| `job_fin` | `cancelados`, `lotes`, `duracion_ms` | Terminó bien |
| `job_omitido` | `motivo` | Otra instancia lo está ejecutando (normal con varios workers) |
| `job_error` | traceback | Falló; se reintenta en la próxima ventana |
| `pedidos_vencidos_cancelados` | `cantidad`, `horas` | Un lote canceló pedidos |
| `stock_repuesto` | `variantes`, `unidades` | Unidades devueltas al inventario |

**5. Verificación directa en la base** (debería dar ~0 si el job funciona):

```sql
SELECT count(*) AS pedidos_vencidos_sin_cancelar
FROM pedidos p
WHERE p.estado_pedido = 'pendiente_pago'
  AND p.fecha_creacion < now() - interval '49 hours'
  AND NOT EXISTS (SELECT 1 FROM pagos_sinpe s
                  WHERE s.pedido_id = p.id AND s.estado_validacion <> 'rechazado');
```

**Alertas recomendadas:**
- Cualquier `job_error`.
- Ningún `job_fin` en las últimas 2 horas (el scheduler murió o ningún proceso tiene el lock).
- `cancelados` muy por encima de lo habitual (¿falla en el flujo de pagos? ¿bots creando pedidos?).

### 4.4 Desactivarlo o moverlo

`SCHEDULER_HABILITADO=false` desactiva el scheduler en ese proceso. Patrón recomendado
para producción con muchas réplicas: las réplicas web con `false` y **un** servicio
*worker* (misma imagen, 1 réplica) con `true`. Sin scheduler, la limpieza manual sigue
disponible en `POST /admin/pedidos/cancelar-vencidos?horas=48`.

---

## 5. Pruebas y CI/CD

### 5.1 La suite de pytest

```
tests/
├── conftest.py            # PostgreSQL de prueba (pgembed o TEST_POSTGRES_URI), Alembic, fixtures
├── ayudantes.py           # carrito(), comprar(), en_paralelo(), ClienteHttp
├── test_concurrencia.py   # FOR UPDATE, deadlocks, lock_timeout (+ sus logs)
├── test_idempotencia.py   # Idempotency-Key en sus 3 caminos (+ eventos idempotencia_*)
├── test_api.py            # HTTP real: JWT (5 tokens maliciosos), checkout, pagos, /salud
├── test_rate_limit.py     # límites por IP y bloqueo por fallos
├── test_scheduler.py      # job, advisory lock, endpoints de monitoreo
├── test_migraciones.py    # Alembic ≡ init.sql, sin deriva, downgrade/upgrade, SQL legado
├── test_catalogo.py       # imagen principal única, seed idempotente
└── test_logging.py        # formato JSON, request_id, sin query strings ni datos personales
```

**Siempre contra PostgreSQL real**, nunca SQLite: `FOR UPDATE`, JSONB, ENUMs e índices
parciales son parte de lo que se prueba. La base de pruebas se crea con
`alembic upgrade head`, la misma vía que producción.

Fixtures principales:

| Fixture | Alcance | Provee |
|---|---|---|
| `url_bd`, `motor`, `Sesion`, `db` | sesión / test | Base migrada y sesiones SQLAlchemy (pool de 60 para los hilos) |
| `fabrica` | sesión | `variante(stock=…)`, `stock(id)`, `vendidas(id)`, `envejecer_pedidos_de(id)` |
| `retardo_en_lock` | test | Pausa de 50 ms dentro de la sección crítica: fuerza los choques |
| `api`, `token_admin` | sesión | uvicorn real en un hilo + cliente HTTP + token JWT |
| `config` | test | `config(rate_limit_login="3/minute")`, revertido al terminar el test |
| `_rate_limit_limpio` | autouse | Contadores de rate limit en cero en cada test |

```bash
pytest                          # suite completa (~25 s)
pytest tests/test_api.py -v     # un archivo
pytest -k idempotencia          # por nombre
pytest -m "not lento"           # sin la prueba de lock_timeout (espera 5 s reales)
ruff check .                    # linter (ruff check . --fix corrige lo automático)
```

**Local:** `pgembed` levanta y destruye un PostgreSQL temporal; no necesitas instalar
nada. **Con un servidor propio:**
`TEST_POSTGRES_URI=postgresql://usuario:clave@host:5432/postgres pytest`. La suite crea
bases con nombre único y las borra al terminar.

### 5.2 El pipeline (`.github/workflows/backend.yml`)

```mermaid
flowchart LR
    P[push / PR] --> L["lint<br/>ruff check"]
    L -->|ok| T
    subgraph T["tests (postgres:17 como servicio)"]
        direction TB
        I[pip install -r requirements-dev.txt] --> S["alembic upgrade head --sql<br/>(las migraciones generan SQL válido)"]
        S --> PY["pytest --junitxml"]
    end
    T --> A[(Artefacto: junit.xml + migraciones.sql)]
```

- **`lint`** falla rápido (unos 15 s) si hay imports sin usar, nombres indefinidos,
  imports desordenados o líneas de más de 120 caracteres.
- **`tests`** usa un contenedor `postgres:17` oficial (vía `TEST_POSTGRES_URI`) en lugar
  de pgembed.
- `concurrency` cancela la corrida anterior de la misma rama si llega un push nuevo.
- El artefacto `reporte-pytest` guarda el JUnit y el SQL de las migraciones durante
  14 días: útil para revisar qué ejecutará un despliegue.

**Recomendado en GitHub:** *Settings → Branches → Branch protection* sobre `main`,
exigiendo los checks `Lint (ruff)` y `Tests (pytest + PostgreSQL 17)` antes de mergear.

---

## 6. Logs estructurados

### 6.1 Formato

Cada línea de stdout es **un objeto JSON**:

```json
{"recurso": "variantes_producto", "filas": 2, "espera_ms": 5003.1, "lock_timeout": "5s",
 "event": "lock_timeout", "request_id": "4552edcd7dd847d1a8826b4a92b19a46",
 "ruta": "/pedidos", "metodo": "POST", "level": "warning",
 "logger": "services.bloqueos", "timestamp": "2026-10-06T06:50:24.901387Z"}
```

| Campo | Siempre | Contenido |
|---|---|---|
| `event` | sí | Identificador **estable** en snake_case: se busca y se cuenta, no se "lee" |
| `level` | sí | `debug` / `info` / `warning` / `error` |
| `logger` | sí | Módulo emisor (`services.checkout`, `core.scheduler`, `api.acceso`…) |
| `timestamp` | sí | ISO-8601 en **UTC** |
| `request_id` | dentro de una request | Correlaciona **todos** los eventos de una misma petición |
| `ruta`, `metodo` | dentro de una request | Sin query string |

**Correlación:** el `request_id` se toma del header `X-Request-ID` si el proxy lo envía
(así se sigue una petición entre servicios) o se genera. Siempre se devuelve en la
respuesta: si un cliente reporta un error, pídele ese header y búscalo en los logs.

**Privacidad:** nunca se registran nombre, WhatsApp ni dirección del cliente,
contraseñas, tokens **ni query strings** (`?ultimos4=` viaja ahí). Las claves de
idempotencia solo aparecen truncadas (`clave_prefijo`). Un test lo verifica.

Los logs de librerías (uvicorn, APScheduler, SQLAlchemy) pasan por el mismo formateador
y también salen en JSON. El access log de uvicorn se reemplaza por el evento `request`.

Para desarrollo local, usa `LOG_FORMATO=consola`: legible y con colores.

### 6.2 Catálogo de eventos

| Evento | Nivel | Emisor | Campos clave | Qué significa / acción |
|---|---|---|---|---|
| `request` | info / error (5xx) | `api.acceso` | `status`, `duracion_ms`, `ip` | Una por petición. Base para latencias y tasas de error |
| `lock_espera_lenta` | info | `services.bloqueos` | `recurso`, `filas`, `espera_ms` | Se esperó un lock más de `LOG_UMBRAL_LOCK_LENTO_MS`: contención |
| **`lock_timeout`** | **warning** | `services.bloqueos` | `recurso`, `filas`, `espera_ms`, `lock_timeout` | Se agotaron los 5 s. Al cliente le llega un 409 con `Retry-After` |
| `lock_deadlock` | error | `services.bloqueos` | `recurso`, `espera_ms` | Deadlock: **no debería ocurrir** (orden global de locks). Investigar |
| **`idempotencia_colision`** | info | `services.checkout` | `pedido_id`, `clave_prefijo`, `fase` | Reintento o doble clic absorbido. `fase`: `previa` / `tras_espera_de_lock` / `colision_unique` |
| `idempotencia_clave_reutilizada` | warning | `services.checkout` | `pedido_id`, `fase` | El frontend reusó una clave con otro carrito: **bug del frontend** |
| `pedido_creado` | info | `services.checkout` | `pedido_id`, `unidades`, `monto_total`, `provincia` | Venta registrada |
| `checkout_stock_insuficiente` | info | `services.checkout` | `skus` | Demanda sin stock: dato útil para reabastecer |
| `pedido_estado_cambiado` | info | `services.pedidos` | `pedido_id`, `desde`, `hacia` | Auditoría de la máquina de estados |
| `stock_repuesto` / `pedidos_vencidos_cancelados` | info | `services.pedidos` | `unidades` / `cantidad` | Inventario devuelto |
| `pago_registrado` / `pago_conciliado` | info | `services.pagos` | `pago_id`, `resultado` | Flujo SINPE |
| `login_exitoso` / `login_fallido` | info / warning | `core.security` | `usuario` | Accesos administrativos |
| `token_rechazado` | info | `errores` | `motivo` | Token vencido, alterado o sin rol |
| `rate_limit_*` | warning / info | `core.rate_limit`, `errores` | ver sección 3.6 | Abuso o límites demasiado estrictos |
| `job_*` | info / error | `core.scheduler` | ver sección 4.3 | Job de limpieza |
| `bd_error_operacional` | error | `errores` | `sqlstate`, traceback | Base caída o red: el cliente recibe 503 |
| `seguridad_sin_configurar` | error | `errores` | `detalle` | Falta `JWT_SECRET_KEY` o las credenciales: `/admin` responde 503 |
| `admin_password_texto_plano` | warning | `core.security` | — | Se usa `ADMIN_PASSWORD`: migrar a `ADMIN_PASSWORD_HASH` |

### 6.3 Leer los logs con `jq`

```bash
# Seguir los logs en vivo, solo warnings y errores
docker logs -f api | jq -c 'select(.level == "warning" or .level == "error")'

# Todos los eventos de una petición concreta (request_id reportado por el cliente)
jq -c 'select(.request_id == "4552edcd7dd847d1a8826b4a92b19a46")' api.log

# Lock timeouts por recurso
jq -r 'select(.event == "lock_timeout") | .recurso' api.log | sort | uniq -c

# Espera máxima y promedio por lock lento
jq -s '[.[] | select(.event == "lock_espera_lenta") | .espera_ms]
       | {n: length, max: max, promedio: (add / length)}' api.log

# Colisiones de idempotencia por fase
jq -r 'select(.event == "idempotencia_colision") | .fase' api.log | sort | uniq -c

# Peticiones lentas (> 500 ms) por ruta
jq -r 'select(.event == "request" and .duracion_ms > 500) | .ruta' api.log | sort | uniq -c | sort -rn

# Respuestas 429 por minuto
jq -r 'select(.event == "request" and .status == 429) | .timestamp[0:16]' api.log | uniq -c
```

En PowerShell, el equivalente es `Get-Content api.log | ConvertFrom-Json | Where-Object event -eq 'lock_timeout'`.

### 6.4 Cómo interpretar las señales de concurrencia

- **`lock_espera_lenta` ocasional** es normal: dos clientes compraron lo mismo a la vez y
  uno esperó unos milisegundos.
- **`lock_espera_lenta` frecuente sobre pocas variantes** indica un producto "caliente"
  (lanzamiento, oferta). Es esperable; si las esperas crecen hacia los 5 s, revisa la
  latencia de la base.
- **`lock_timeout` aislado:** el cliente reintentó (409 + `Retry-After`).
  **`lock_timeout` sostenido:** alguna transacción retiene filas demasiado tiempo. Busca
  sesiones colgadas:

  ```sql
  SELECT pid, now() - xact_start AS duracion, state, left(query, 80)
  FROM pg_stat_activity
  WHERE state = 'idle in transaction' OR now() - xact_start > interval '5 seconds'
  ORDER BY duracion DESC;
  ```

- **`idempotencia_colision` con `fase=tras_espera_de_lock`:** dobles clics reales,
  absorbidos correctamente. **`fase=colision_unique`** debería ser rarísima.
  **`idempotencia_clave_reutilizada`** es siempre un bug del frontend: la clave debe
  generarse por intento de compra, no por sesión.

### 6.5 Llevar los logs a un agregador

La app solo escribe a **stdout**: no gestiona archivos ni rotación (*12-factor*). El
entorno se encarga de recolectarlos:

- **Docker / Kubernetes:** el runtime captura stdout; Promtail/Loki, Fluent Bit,
  Datadog Agent o CloudWatch Agent lo envían al agregador. Como ya es JSON, cada campo
  queda indexado sin escribir *parsers*.
- **systemd:** `journalctl -u motor-ecommerce -o cat | jq …`.

**Alertas mínimas sugeridas:** `level=error` (cualquiera), `lock_deadlock`, `job_error`,
tasa de `lock_timeout` > N/min, tasa de `status>=500` > 1 %, y
`rate_limit_bloqueo_por_fallos` con `ambito=login`.

---

## 7. Puesta en producción

### 7.1 Checklist

- [ ] `.env` de producción completo (ver sección 9), con `ADMIN_PASSWORD_HASH` (no texto
      plano) y un `JWT_SECRET_KEY` generado con `python -m core.security secreto`.
- [ ] `python -m alembic upgrade head` ejecutado como paso de despliegue.
- [ ] `python -m scripts.seed_catalogo` (solo la primera vez).
- [ ] `RATE_LIMIT_STORAGE_URI=redis://…` si hay más de un worker o servidor.
- [ ] uvicorn con `--proxy-headers --forwarded-allow-ips=<IPs del proxy>`.
- [ ] Health check del balanceador apuntando a `GET /salud`.
- [ ] Logs de stdout llegando al agregador, con las alertas de 6.5.
- [ ] `GET /admin/sistema/jobs` muestra el job con `proxima_ejecucion`.
- [ ] Branch protection exigiendo el CI en verde.

### 7.2 Arranque recomendado

```bash
uvicorn main:app \
  --host 0.0.0.0 --port 8000 \
  --workers 4 \
  --proxy-headers --forwarded-allow-ips="10.0.0.0/8" \
  --timeout-graceful-shutdown 30
```

- **Apagado ordenado:** ante un `SIGTERM` (deploy, escalado), FastAPI ejecuta el
  *lifespan*: `scheduler.shutdown(wait=True)` deja terminar el lote en curso del job
  antes de salir. `--timeout-graceful-shutdown` da margen a las requests activas.
- **`/salud`** responde **503** si la base no contesta, para que el balanceador saque esa
  instancia de rotación. `/` sigue siendo un *liveness* simple que no toca la base.

---

## 8. Runbook: síntomas, causas y acciones

| Síntoma | Causa probable | Acción |
|---|---|---|
| Muchos 409 *"Recurso ocupado…"* y `lock_timeout` en logs | Transacción colgada o base lenta | Consulta `pg_stat_activity` (6.4); termina la sesión con `SELECT pg_terminate_backend(pid)` si corresponde |
| Clientes legítimos reciben 429 en el seguimiento | `RATE_LIMIT_SEGUIMIENTO` bajo, o todos comparten IP (falta `--proxy-headers`) | Revisa el campo `ip` del evento `request`; si todas son iguales, configura el proxy (3.4) |
| El administrador recibe 429 al iniciar sesión | Bloqueo por fallos (¿ataque?) | Revisa `login_fallido`; desbloquea (3.5); considera endurecer los límites |
| El stock de pedidos abandonados no vuelve | El job no corre o falla | `GET /admin/sistema/jobs` (`ultimo_resultado`, `ultimo_error`); busca `job_error`; ejecútalo a mano (4.3) |
| `/admin/*` responde 503 | Falta configuración de seguridad | Busca `seguridad_sin_configurar` en los logs; completa el `.env` |
| `/salud` responde 503 | La base no está accesible | Busca `bd_error_operacional` / `salud_bd_error`; revisa red, credenciales y estado de PostgreSQL |
| El CI falla en `test_modelos_sin_deriva_respecto_de_la_base` | Se cambió `models/` sin migración | `python -m scripts.generar_migracion "…"` y revisa el archivo |
| El CI falla en `test_alembic_produce_el_mismo_esquema_que_init_sql` | Se migró sin actualizar `init.sql` (o al revés) | Sincroniza `init.sql` con la migración |
| `alembic upgrade` falla a mitad de camino | Error en una migración | Nada quedó aplicado (DDL transaccional). Corrige y reintenta |

---

## 9. Referencia de variables de entorno

Todas se leen del `.env` o del entorno (`core/config.py`). Plantilla: `.env.example`.

| Variable | Defecto | Descripción |
|---|---|---|
| `DATABASE_URL` | — (obligatoria) | `postgresql+psycopg://usuario:clave@host:5432/base` |
| `ADMIN_USER` | — | Usuario administrador |
| `ADMIN_PASSWORD_HASH` | — | Hash Argon2 (`python -m core.security hash`), entre comillas simples |
| `ADMIN_PASSWORD` | — | Solo desarrollo: texto plano |
| `JWT_SECRET_KEY` | — | ≥ 32 caracteres (`python -m core.security secreto`) |
| `JWT_EXPIRACION_MINUTOS` | `30` | Vida del token de acceso |
| `CORS_ORIGINS` | vacío | Orígenes del frontend, separados por comas |
| `RATE_LIMIT_HABILITADO` | `true` | Interruptor general |
| `RATE_LIMIT_STORAGE_URI` | `memory://` | `redis://…` con varios procesos |
| `RATE_LIMIT_LOGIN` | `5/minute` | Por IP en `POST /auth/login` |
| `RATE_LIMIT_SEGUIMIENTO` | `30/minute` | Por IP en `GET /pedidos/{id}` |
| `RATE_LIMIT_FALLOS_LOGIN` | `10/hour` | Fallos por usuario antes de bloquear |
| `RATE_LIMIT_FALLOS_SEGUIMIENTO` | `10/day` | Fallos por pedido antes de bloquear |
| `SCHEDULER_HABILITADO` | `true` | Arranca el scheduler en este proceso |
| `JOB_VENCIDOS_INTERVALO_MINUTOS` | `60` | Frecuencia del job de limpieza |
| `PEDIDOS_VENCEN_HORAS` | `48` | Antigüedad para considerar vencido un pedido impago |
| `LOG_NIVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `LOG_FORMATO` | `json` | `json` (producción) o `consola` (desarrollo) |
| `LOG_UMBRAL_LOCK_LENTO_MS` | `100` | Umbral para registrar `lock_espera_lenta` |
| `TEST_POSTGRES_URI` | — | Solo tests: servidor PostgreSQL externo en lugar de pgembed |

---

## 10. Limitaciones conocidas y próximos pasos

| Tema | Detalle | Propuesta |
|---|---|---|
| Estado del job por proceso | `GET /admin/sistema/jobs` muestra solo el worker que responde | Persistir las ejecuciones en una tabla `ejecuciones_job` |
| `slowapi` y Python 3.16 | slowapi 0.1.10 usa `asyncio.iscoroutinefunction`, que Python 3.16 elimina (hoy solo emite un aviso) | Actualizar slowapi cuando publique el arreglo, o migrar a `limits` directamente |
| Redis no se prueba en CI | Los tests usan `memory://` | Agregar un servicio `redis` al workflow y un test con `RATE_LIMIT_STORAGE_URI=redis://…` |
| Desbloqueo manual | Requiere `redis-cli` o reiniciar | Endpoint `DELETE /admin/sistema/rate-limit/{ambito}/{clave}` |
| Métricas | Hoy todo se deriva de logs | Exponer `/metrics` (Prometheus): latencias, 429, `lock_timeout`, stock reservado |
| Un solo administrador | Credenciales en `.env` | Tabla `usuarios` con roles, refresh tokens y revocación por `jti` |
| Despliegue | Sin Dockerfile ni CD | Dockerfile multi-stage + job de CD que corra `alembic upgrade head` antes de publicar |
