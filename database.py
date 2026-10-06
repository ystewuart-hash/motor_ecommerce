import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Cargar variables del archivo .env
load_dotenv()

# Obtener la URL de la base de datos
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

if not SQLALCHEMY_DATABASE_URL:
    raise RuntimeError("Falta la variable de entorno DATABASE_URL")

# Crear el motor de conexión.
# pool_pre_ping descarta conexiones muertas (reinicio de PostgreSQL, timeouts de red)
# antes de entregarlas, en lugar de fallar en la primera consulta de una request.
engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)

# Fábrica de sesiones para interactuar con la BD
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Clase base de la que heredarán todos nuestros modelos
Base = declarative_base()

# Dependencia para inyectar la sesión en los endpoints de FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
