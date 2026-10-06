import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from core.config import get_settings
from core.logs import configurar_logging, middleware_logging
from core.rate_limit import limiter
from core.scheduler import crear_scheduler
from database import engine
from errores import registrar_manejadores
from routers import admin_catalogo, admin_pedidos, admin_sistema, auth, catalogo, checkout
from schemas.sistema import SaludResponse

_cfg = get_settings()
# Primero el logging: todo lo que ocurra al importar/arrancar ya sale estructurado.
configurar_logging(nivel=_cfg.log_nivel, formato=_cfg.log_formato)
logger = structlog.get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Arranque y apagado ordenado de los componentes de fondo."""
    app.state.scheduler = None
    if _cfg.scheduler_habilitado:
        scheduler = crear_scheduler()
        scheduler.start()
        app.state.scheduler = scheduler
        logger.info("scheduler_iniciado", jobs=[job.id for job in scheduler.get_jobs()])
    logger.info("api_iniciada", rate_limit=_cfg.rate_limit_habilitado,
                rate_limit_storage=_cfg.rate_limit_storage_uri.split("://")[0])
    yield
    if app.state.scheduler is not None:
        # wait=True: si el job está corriendo, termina su lote antes de apagar.
        app.state.scheduler.shutdown(wait=True)
        logger.info("scheduler_detenido")
    logger.info("api_detenida")


# Inicializar la aplicación FastAPI
app = FastAPI(
    title="Motor E-Commerce Headless",
    description="API transaccional y catálogo de productos",
    version="1.0.0",
    lifespan=lifespan,
)

# slowapi busca el limiter en app.state para inyectar los headers X-RateLimit-*.
app.state.limiter = limiter

# Logging por request (request_id, duración, status). Se registra antes que CORS
# para que también cubra las respuestas a preflight.
app.middleware("http")(middleware_logging)

# CORS: el frontend headless vive en otro origen. Lista separada por comas en
# CORS_ORIGINS (ej. "http://localhost:3000,https://mitienda.com"); vacío = ninguno.
origenes_permitidos = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if origenes_permitidos:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origenes_permitidos,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "Idempotency-Key", "X-Request-ID"],
        expose_headers=[
            "Idempotent-Replayed", "X-Request-ID", "Retry-After",
            "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset",
        ],
    )

registrar_manejadores(app)

app.include_router(catalogo.router)
app.include_router(checkout.router)
app.include_router(auth.router)
app.include_router(admin_catalogo.router)
app.include_router(admin_pedidos.router)
app.include_router(admin_sistema.router)


@app.get("/")
def health_check():
    return {
        "status": "online",
        "mensaje": "El motor E-Commerce está funcionando correctamente"
    }


@app.get("/salud", response_model=SaludResponse, tags=["Sistema"],
         responses={503: {"description": "Base de datos inaccesible"}})
def salud(request: Request):
    """
    Health check para balanceadores y orquestadores (readiness probe).
    Responde 503 si la base de datos no contesta, para sacar la instancia de rotación.
    """
    try:
        with engine.connect() as conexion:
            conexion.execute(text("SELECT 1"))
        base_de_datos = "ok"
    except Exception:  # noqa: BLE001 - cualquier fallo de conexión cuenta como caída
        logger.exception("salud_bd_error")
        base_de_datos = "error"

    scheduler = request.app.state.scheduler
    if scheduler is None:
        estado_scheduler = "deshabilitado"
    else:
        estado_scheduler = "activo" if scheduler.running else "detenido"

    cuerpo = SaludResponse(
        status="ok" if base_de_datos == "ok" else "degradado",
        base_de_datos=base_de_datos,
        scheduler=estado_scheduler,
    )
    if base_de_datos != "ok":
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=cuerpo.model_dump())
    return cuerpo
