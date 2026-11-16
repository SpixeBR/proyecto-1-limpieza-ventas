"""
Pipeline de limpieza de ventas.

Toma la exportación cruda de ventas y devuelve un dataset limpio y validado,
junto con un log que explica cada cambio (filas antes/después y motivo).

Uso desde la terminal:
    python src/limpiar_datos.py data/raw/ventas_crudas.csv data/processed/ventas_limpias.csv
    python src/limpiar_datos.py entrada.csv salida.csv --log log_limpieza.csv

Uso desde Python:
    from limpiar_datos import limpiar_ventas
    limpio, log = limpiar_ventas(pd.read_csv("ventas_crudas.csv", dtype=str))
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger("limpiar_datos")

COLUMNAS_REQUERIDAS: tuple[str, ...] = (
    "id_pedido", "fecha", "cliente_id", "provincia", "categoria",
    "producto", "cantidad", "precio_unitario", "total", "medio_pago",
)
FORMATOS_FECHA: tuple[str, ...] = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y")
TOLERANCIA_TOTAL = 0.01  # 1% de diferencia aceptada entre total y precio x cantidad
FACTOR_ATIPICO = 5      # un precio 5 veces mayor (o menor) que el habitual del producto es un error
MILES_SIN_DECIMALES = re.compile(r"\d{1,3}(\.\d{3})+")  # "1.234" o "1.234.567"

PROVINCIAS: tuple[str, ...] = (
    "Buenos Aires", "CABA", "Catamarca", "Chaco", "Chubut", "Córdoba", "Corrientes", "Entre Ríos",
    "Formosa", "Jujuy", "La Pampa", "La Rioja", "Mendoza", "Misiones", "Neuquén", "Río Negro", "Salta",
    "San Juan", "San Luis", "Santa Cruz", "Santa Fe", "Santiago del Estero", "Tierra del Fuego", "Tucumán",
)
# Formas alternativas frecuentes (ya normalizadas: sin acentos, espacios ni puntos)
ALIAS_PROVINCIAS: dict[str, str] = {
    "bsas": "Buenos Aires", "pba": "Buenos Aires", "provinciadebuenosaires": "Buenos Aires",
    "capitalfederal": "CABA", "ciudaddebuenosaires": "CABA", "ciudadautonomadebuenosaires": "CABA",
    "capital": "CABA", "sgodelestero": "Santiago del Estero", "tierradelfuegoaeias": "Tierra del Fuego",
}
MAPA_CATEGORIAS: dict[str, str] = {
    "almacen": "Almacén", "bebidas": "Bebidas", "limpieza": "Limpieza", "perfumeria": "Perfumería",
}


class ErrorDeDatos(ValueError):
    """El archivo de entrada no tiene la estructura esperada."""


@dataclass
class LogLimpieza:
    """Registro de cada paso de la limpieza, para poder auditarla."""
    pasos: list[dict] = field(default_factory=list)

    def registrar(self, paso: str, antes: int, despues: int, detalle: str = "") -> None:
        self.pasos.append({"paso": paso, "filas_antes": antes, "filas_despues": despues, "detalle": detalle})
        logger.info("%s: %s", paso, detalle or f"{antes} -> {despues} filas")

    def a_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(self.pasos)


# ------------------------------------------------------------------ conversiones

def parsear_fecha(texto: object) -> pd.Timestamp:
    """Convierte una fecha en cualquiera de los formatos conocidos. Devuelve NaT si no puede."""
    if pd.isna(texto):
        return pd.NaT
    for formato in FORMATOS_FECHA:
        try:
            return pd.to_datetime(str(texto).strip(), format=formato)
        except (ValueError, TypeError):
            continue
    return pd.NaT


def parsear_monto(texto: object) -> float:
    """Convierte '1234.50', '$ 1.234,50', '$ 1.234' o 1234.5 a float. Devuelve NaN si no puede."""
    if pd.isna(texto):
        return np.nan
    if isinstance(texto, (int, float)):
        return float(texto)
    limpio = str(texto).strip().replace("$", "").replace(" ", "")
    if "," in limpio:  # formato argentino: punto de miles, coma decimal
        limpio = limpio.replace(".", "").replace(",", ".")
    elif MILES_SIN_DECIMALES.fullmatch(limpio):  # "1.234" en formato argentino son mil doscientos
        limpio = limpio.replace(".", "")
    try:
        return float(limpio)
    except ValueError:
        return np.nan


def clave_texto(texto: str) -> str:
    """'Bs. As.' -> 'bsas', 'Córdoba ' -> 'cordoba': minúsculas, sin acentos, espacios ni puntos."""
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", sin_acentos.lower())


MAPA_PROVINCIAS: dict[str, str] = {clave_texto(p): p for p in PROVINCIAS} | ALIAS_PROVINCIAS


def normalizar_texto(serie: pd.Series, mapa: dict[str, str]) -> pd.Series:
    """Unifica variantes de escritura ('Bs As', 'BUENOS AIRES') con un mapa de claves normalizadas."""
    return serie.map(lambda v: mapa.get(clave_texto(v)) if isinstance(v, str) else np.nan)


# ------------------------------------------------------------------ pasos

def validar_columnas(df: pd.DataFrame) -> None:
    faltantes = [c for c in COLUMNAS_REQUERIDAS if c not in df.columns]
    if faltantes:
        raise ErrorDeDatos(f"Faltan columnas en el archivo: {faltantes}")
    if df.empty:
        raise ErrorDeDatos("El archivo no tiene filas.")


def eliminar_duplicados(df: pd.DataFrame, log: LogLimpieza) -> pd.DataFrame:
    antes = len(df)
    df = df.drop_duplicates().reset_index(drop=True)
    log.registrar("Eliminar duplicados exactos", antes, len(df), f"{antes - len(df)} filas repetidas")
    repetidos = df["id_pedido"].duplicated().sum()
    if repetidos:  # mismo pedido con datos distintos: no se puede decidir solo cuál es correcto
        logger.warning("%d id_pedido repetidos con datos distintos; se conserva la primera aparición", repetidos)
        antes = len(df)
        df = df.drop_duplicates(subset="id_pedido").reset_index(drop=True)
        log.registrar("Resolver id_pedido repetidos", antes, len(df), f"{repetidos} conflictos, se conserva el primero")
    return df


def normalizar_columnas_texto(df: pd.DataFrame, log: LogLimpieza) -> pd.DataFrame:
    df = df.copy()
    for col in ("producto", "medio_pago", "cliente_id"):
        df[col] = df[col].str.strip()

    originales = df["provincia"].notna()
    df["provincia"] = normalizar_texto(df["provincia"], MAPA_PROVINCIAS)
    sin_mapa = (originales & df["provincia"].isna()).sum()

    originales_cat = df["categoria"].notna()
    df["categoria"] = normalizar_texto(df["categoria"], MAPA_CATEGORIAS)
    sin_mapa += (originales_cat & df["categoria"].isna()).sum()

    detalle = "provincias y categorías unificadas"
    if sin_mapa:
        detalle += f"; {sin_mapa} valores desconocidos quedan como faltantes (agregarlos al mapa)"
        logger.warning("%d valores de provincia/categoría no reconocidos", sin_mapa)
    log.registrar("Unificar nombres", len(df), len(df), detalle)
    return df


def convertir_tipos(df: pd.DataFrame, log: LogLimpieza) -> pd.DataFrame:
    df = df.copy()
    df["fecha"] = df["fecha"].apply(parsear_fecha)
    df["total"] = df["total"].apply(parsear_monto)
    df["precio_unitario"] = df["precio_unitario"].apply(parsear_monto)
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce")

    antes = len(df)
    invalidas = df["fecha"].isna() | df["cantidad"].isna() | df["total"].isna()
    df = df[~invalidas].copy()
    df["cantidad"] = df["cantidad"].astype(int)
    log.registrar("Convertir fechas y montos", antes, len(df),
                  f"{invalidas.sum()} filas con fecha, cantidad o total ilegibles" if invalidas.any() else "4 formatos de fecha y montos '$ 1.234,50' convertidos")
    return df


def excluir_cantidades_invalidas(df: pd.DataFrame, log: LogLimpieza) -> pd.DataFrame:
    antes = len(df)
    invalidas = df["cantidad"] <= 0
    df = df[~invalidas].copy()
    log.registrar("Excluir cantidades <= 0", antes, len(df), f"{invalidas.sum()} pedidos con error de carga")
    return df


def precio_referencia(df: pd.DataFrame) -> pd.Series:
    """Precio unitario habitual de cada producto (mediana), para detectar valores imposibles."""
    return df.groupby("producto")["precio_unitario"].transform("median")


def completar_precios(df: pd.DataFrame, log: LogLimpieza) -> pd.DataFrame:
    """Completa el precio faltante como total / cantidad, salvo que ese precio sea imposible."""
    df = df.copy()
    referencia = precio_referencia(df)
    falta = df["precio_unitario"].isna()
    implicito = df["total"] / df["cantidad"]
    atipico = falta & ((implicito / referencia > FACTOR_ATIPICO) | (referencia / implicito > FACTOR_ATIPICO))

    df.loc[falta & ~atipico, "precio_unitario"] = implicito[falta & ~atipico].round(2)
    # Si el total también está mal, se usa el precio habitual del producto y se recalcula el total
    df.loc[atipico, "precio_unitario"] = referencia[atipico].round(2)
    df.loc[atipico, "total"] = (df.loc[atipico, "precio_unitario"] * df.loc[atipico, "cantidad"]).round(2)

    detalle = f"{(falta & ~atipico).sum()} precios calculados como total/cantidad"
    if atipico.any():
        detalle += f"; {atipico.sum()} con total imposible, se usa el precio habitual del producto"
    log.registrar("Completar precio unitario", len(df), len(df), detalle)
    return df


def corregir_totales(df: pd.DataFrame, log: LogLimpieza) -> pd.DataFrame:
    """Corrige filas donde total no coincide con precio x cantidad.

    Para decidir cuál de los dos valores está mal se compara cada uno con el precio
    habitual del producto: se conserva el que esté más cerca y se recalcula el otro.
    Así se corrigen tanto totales inflados (ej. coma decimal perdida) como precios mal cargados.
    """
    df = df.copy()
    esperado = df["precio_unitario"] * df["cantidad"]
    inconsistente = ((df["total"] / esperado) - 1).abs() > TOLERANCIA_TOTAL

    # Precio habitual calculado solo con filas consistentes, para que los errores no lo contaminen
    mediana_ok = df[~inconsistente].groupby("producto")["precio_unitario"].median()
    referencia = df["producto"].map(mediana_ok).fillna(precio_referencia(df))
    implicito = df["total"] / df["cantidad"]
    distancia_precio = np.log(df["precio_unitario"] / referencia).abs()
    distancia_total = np.log(implicito / referencia).abs()
    total_mal = inconsistente & (distancia_precio <= distancia_total)
    precio_mal = inconsistente & ~total_mal

    diferencia = (df.loc[total_mal, "total"] - esperado[total_mal]).sum()
    df.loc[total_mal, "total"] = esperado[total_mal].round(2)
    df.loc[precio_mal, "precio_unitario"] = implicito[precio_mal].round(2)

    detalle = f"{total_mal.sum()} totales recalculados (diferencia de $ {diferencia:,.0f})".replace(",", ".")
    if precio_mal.any():
        detalle += f"; {precio_mal.sum()} precios unitarios corregidos"
    log.registrar("Corregir totales inconsistentes", len(df), len(df), detalle)
    return df


def marcar_faltantes(df: pd.DataFrame, log: LogLimpieza) -> pd.DataFrame:
    df = df.copy()
    for col in ("provincia", "categoria", "medio_pago"):
        n = df[col].isna().sum()
        if n:
            # astype(object): una columna 100% vacía llega como float64 y
            # pandas no admite rellenar float64 con texto.
            df[col] = df[col].astype("object").fillna("Sin dato")
            log.registrar(f"Marcar {col} faltante", len(df), len(df), f"{n} valores como 'Sin dato'")
    n_cli = df["cliente_id"].isna().sum()
    log.registrar("Cliente faltante", len(df), len(df), f"{n_cli} pedidos sin cliente (se mantienen)")
    return df


def validar_resultado(df: pd.DataFrame) -> None:
    """Controles de calidad finales. Lanza ErrorDeDatos si algo no cierra."""
    problemas = []
    if not df["id_pedido"].is_unique:
        problemas.append("hay id_pedido repetidos")
    if df["fecha"].isna().any():
        problemas.append("hay fechas vacías")
    if (df["cantidad"] <= 0).any():
        problemas.append("hay cantidades <= 0")
    # Misma tolerancia que en la corrección, para no rechazar diferencias de redondeo
    if ((df["total"] / (df["precio_unitario"] * df["cantidad"]) - 1).abs() > TOLERANCIA_TOTAL).any():
        problemas.append("hay totales que no coinciden con precio x cantidad")
    if problemas:
        raise ErrorDeDatos("Validación final fallida: " + "; ".join(problemas))


# ------------------------------------------------------------------ pipeline

def limpiar_ventas(crudo: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Ejecuta todo el pipeline. Devuelve (datos_limpios, log_de_cambios)."""
    validar_columnas(crudo)
    log = LogLimpieza()
    df = crudo.copy()
    for paso in (eliminar_duplicados, normalizar_columnas_texto, convertir_tipos,
                 excluir_cantidades_invalidas, completar_precios, corregir_totales, marcar_faltantes):
        df = paso(df, log)
    df = df.sort_values(["fecha", "id_pedido"]).reset_index(drop=True)
    validar_resultado(df)
    return df[list(COLUMNAS_REQUERIDAS)], log.a_dataframe()


def leer_csv(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el archivo: {ruta}")
    for codificacion in ("utf-8-sig", "latin-1"):  # Excel en Windows suele exportar en latin-1
        try:
            # sep=None detecta solo si el separador es "," o ";" (Excel en español usa ";")
            return pd.read_csv(ruta, dtype=str, encoding=codificacion, sep=None, engine="python")
        except UnicodeDecodeError:
            continue
    raise ErrorDeDatos(f"No se pudo leer {ruta}: codificación desconocida")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Limpia una exportación de ventas y genera un CSV listo para analizar.")
    parser.add_argument("entrada", type=Path, help="CSV crudo")
    parser.add_argument("salida", type=Path, help="CSV limpio a generar")
    parser.add_argument("--log", type=Path, help="CSV opcional con el detalle de cada paso de limpieza")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    try:
        crudo = leer_csv(args.entrada)
        limpio, log = limpiar_ventas(crudo)
    except (FileNotFoundError, ErrorDeDatos) as e:
        logger.error(str(e))
        return 1

    args.salida.parent.mkdir(parents=True, exist_ok=True)
    limpio.to_csv(args.salida, index=False, date_format="%Y-%m-%d")
    if args.log:
        log.to_csv(args.log, index=False)
    logger.info("Listo: %d filas crudas -> %d pedidos limpios en %s", len(crudo), len(limpio), args.salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
