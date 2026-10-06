"""
Población inicial del catálogo (seed data) para una base recién creada con init.sql.

Idempotente: busca cada registro por su clave natural (slug o SKU) y solo crea
los que faltan; nunca sobrescribe datos existentes (precios o stock ajustados a
mano se respetan). Todo ocurre en una única transacción: o entra completo o nada.

Uso:
    venv/Scripts/python.exe -m scripts.seed_catalogo
"""
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from database import SessionLocal  # noqa: E402
from models import Categoria, ImagenProducto, Marca, Producto, VarianteProducto  # noqa: E402

# Placeholder: reemplazar por la URL real del CDN / bucket de imágenes.
CDN_IMAGENES = "https://cdn.example.com/productos"


# ============================================================================
# Datos semilla (precios en colones, IVA incluido, referencia de mercado CR)
# ============================================================================
CATEGORIAS = [
    {"nombre": "Proteínas", "slug": "proteinas"},
    {"nombre": "Creatinas", "slug": "creatinas"},
    {"nombre": "Pre-entrenos", "slug": "pre-entrenos"},
]

MARCAS = [
    {"nombre": "Optimum Nutrition", "slug": "optimum-nutrition"},
    {"nombre": "Dymatize", "slug": "dymatize"},
]


@dataclass
class VarianteSemilla:
    sku: str
    atributos: dict[str, str]
    precio: str
    stock: int


@dataclass
class ProductoSemilla:
    nombre: str
    slug: str
    categoria: str  # slug
    marca: str  # slug
    descripcion_html: str
    variantes: list[VarianteSemilla] = field(default_factory=list)


PRODUCTOS = [
    ProductoSemilla(
        nombre="Gold Standard 100% Whey",
        slug="gold-standard-100-whey",
        categoria="proteinas",
        marca="optimum-nutrition",
        descripcion_html=(
            "<p>Proteína de suero con <strong>24 g de proteína</strong> y 5,5 g de BCAA "
            "por porción. Aislado como ingrediente principal.</p>"
        ),
        variantes=[
            VarianteSemilla("ON-GSW-CHOC-2LB", {"sabor": "Double Rich Chocolate", "peso": "2 lb"}, "29900.00", 25),
            VarianteSemilla("ON-GSW-CHOC-5LB", {"sabor": "Double Rich Chocolate", "peso": "5 lb"}, "56900.00", 15),
            VarianteSemilla("ON-GSW-VAN-5LB", {"sabor": "Vanilla Ice Cream", "peso": "5 lb"}, "56900.00", 10),
        ],
    ),
    ProductoSemilla(
        nombre="ISO100 Hydrolyzed",
        slug="iso100-hydrolyzed",
        categoria="proteinas",
        marca="dymatize",
        descripcion_html=(
            "<p>Aislado de suero hidrolizado: <strong>25 g de proteína</strong>, "
            "menos de 1 g de azúcar y absorción rápida.</p>"
        ),
        variantes=[
            VarianteSemilla("DYM-ISO-FUDGE-1.6LB", {"sabor": "Fudge Brownie", "peso": "1.6 lb"}, "36900.00", 12),
            VarianteSemilla("DYM-ISO-FUDGE-5LB", {"sabor": "Fudge Brownie", "peso": "5 lb"}, "79900.00", 8),
            VarianteSemilla("DYM-ISO-VAN-5LB", {"sabor": "Gourmet Vanilla", "peso": "5 lb"}, "79900.00", 6),
        ],
    ),
    ProductoSemilla(
        nombre="Micronized Creatine Powder",
        slug="micronized-creatine-powder",
        categoria="creatinas",
        marca="optimum-nutrition",
        descripcion_html="<p>Creatina monohidratada micronizada, <strong>5 g por porción</strong>, sin sabor.</p>",
        variantes=[
            VarianteSemilla("ON-CREA-300G", {"sabor": "Sin sabor", "peso": "300 g"}, "17900.00", 30),
            VarianteSemilla("ON-CREA-600G", {"sabor": "Sin sabor", "peso": "600 g"}, "29900.00", 20),
        ],
    ),
    ProductoSemilla(
        nombre="Creatine Monohydrate",
        slug="dymatize-creatine-monohydrate",
        categoria="creatinas",
        marca="dymatize",
        descripcion_html="<p>Creatina monohidratada micronizada de alta pureza, 5 g por porción.</p>",
        variantes=[
            VarianteSemilla("DYM-CREA-500G", {"sabor": "Sin sabor", "peso": "500 g"}, "24900.00", 18),
        ],
    ),
    ProductoSemilla(
        nombre="Gold Standard Pre-Workout",
        slug="gold-standard-pre-workout",
        categoria="pre-entrenos",
        marca="optimum-nutrition",
        descripcion_html=(
            "<p>Pre-entreno con <strong>175 mg de cafeína</strong>, 3 g de creatina "
            "y 1,5 g de beta-alanina por porción.</p>"
        ),
        variantes=[
            VarianteSemilla("ON-PRE-BR-30", {"sabor": "Blue Raspberry", "porciones": "30"}, "24500.00", 14),
            VarianteSemilla("ON-PRE-FP-30", {"sabor": "Fruit Punch", "porciones": "30"}, "24500.00", 9),
        ],
    ),
]


# ============================================================================
# Lógica de inserción idempotente
# ============================================================================
@dataclass
class Resumen:
    creados: dict[str, int] = field(default_factory=dict)
    existentes: dict[str, int] = field(default_factory=dict)

    def contar(self, entidad: str, creado: bool) -> None:
        destino = self.creados if creado else self.existentes
        destino[entidad] = destino.get(entidad, 0) + 1


def _obtener_o_crear(db: Session, modelo, resumen: Resumen, filtro: dict, valores: dict):
    columna, valor = next(iter(filtro.items()))
    existente = db.scalars(select(modelo).where(getattr(modelo, columna) == valor)).one_or_none()
    resumen.contar(modelo.__tablename__, existente is None)
    if existente is not None:
        return existente
    nuevo = modelo(**filtro, **valores)
    db.add(nuevo)
    db.flush()  # obtiene el UUID generado por PostgreSQL para usarlo como FK
    return nuevo


def sembrar(db: Session) -> Resumen:
    resumen = Resumen()

    categorias = {
        c["slug"]: _obtener_o_crear(db, Categoria, resumen, {"slug": c["slug"]}, {"nombre": c["nombre"]})
        for c in CATEGORIAS
    }
    marcas = {
        m["slug"]: _obtener_o_crear(db, Marca, resumen, {"slug": m["slug"]}, {"nombre": m["nombre"]})
        for m in MARCAS
    }

    for p in PRODUCTOS:
        producto = _obtener_o_crear(
            db,
            Producto,
            resumen,
            {"slug": p.slug},
            {
                "nombre": p.nombre,
                "descripcion_html": p.descripcion_html,
                "categoria_id": categorias[p.categoria].id,
                "marca_id": marcas[p.marca].id,
            },
        )
        for v in p.variantes:
            _obtener_o_crear(
                db,
                VarianteProducto,
                resumen,
                {"sku": v.sku},
                {
                    "producto_id": producto.id,
                    "atributos": v.atributos,
                    "precio": Decimal(v.precio),
                    "stock_disponible": v.stock,
                },
            )
        _obtener_o_crear(
            db,
            ImagenProducto,
            resumen,
            {"url": f"{CDN_IMAGENES}/{p.slug}/principal.webp"},
            {"producto_id": producto.id, "is_principal": True, "orden": 0},
        )

    return resumen


def main() -> None:
    with SessionLocal() as db:
        try:
            resumen = sembrar(db)
            db.commit()
        except Exception:
            db.rollback()
            raise

    print("Seed del catálogo completado.")
    for entidad in sorted(set(resumen.creados) | set(resumen.existentes)):
        print(
            f"  {entidad:<20} creados: {resumen.creados.get(entidad, 0):>2}"
            f"   ya existían: {resumen.existentes.get(entidad, 0):>2}"
        )


if __name__ == "__main__":
    main()
