"""Tests del pipeline de limpieza. Ejecutar con:  pytest -q"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from limpiar_datos import (
    ErrorDeDatos,
    leer_csv,
    limpiar_ventas,
    parsear_fecha,
    parsear_monto,
    validar_columnas,
)


def fila(**cambios) -> dict:
    base = {"id_pedido": "P1", "fecha": "2025-03-01", "cliente_id": "C0001", "provincia": "Córdoba",
            "categoria": "Almacén", "producto": "Yerba 1kg", "cantidad": "2", "precio_unitario": "1000",
            "total": "2000", "medio_pago": "Mercado Pago"}
    base.update(cambios)
    return base


# ---- conversiones

@pytest.mark.parametrize("texto, esperado", [
    ("1234.50", 1234.50), ("$ 1.234,50", 1234.50), ("$ 18.336,70", 18336.70), ("500", 500.0), (750, 750.0),
    ("$ 1.234", 1234.0), ("1.234.567", 1234567.0), ("$1.234,5", 1234.5),
])
def test_parsear_monto(texto, esperado):
    assert parsear_monto(texto) == pytest.approx(esperado)


def test_parsear_monto_invalido_devuelve_nan():
    assert np.isnan(parsear_monto("no es un número"))
    assert np.isnan(parsear_monto(None))


@pytest.mark.parametrize("texto", ["2025-08-06", "06/08/2025", "06-08-2025", "06/08/25"])
def test_parsear_fecha_todos_los_formatos(texto):
    assert parsear_fecha(texto) == pd.Timestamp("2025-08-06")


def test_parsear_fecha_invalida_devuelve_nat():
    assert pd.isna(parsear_fecha("32/13/2025"))


# ---- pipeline

def test_elimina_duplicados_exactos():
    crudo = pd.DataFrame([fila(), fila(), fila(id_pedido="P2")])
    limpio, _ = limpiar_ventas(crudo)
    assert len(limpio) == 2
    assert limpio["id_pedido"].is_unique


def test_unifica_provincias():
    crudo = pd.DataFrame([fila(id_pedido="P1", provincia="Bs As"), fila(id_pedido="P2", provincia="BUENOS AIRES"),
                          fila(id_pedido="P3", provincia="Capital Federal")])
    limpio, _ = limpiar_ventas(crudo)
    assert set(limpio["provincia"]) == {"Buenos Aires", "CABA"}


@pytest.mark.parametrize("texto, esperado", [
    ("Bs. As.", "Buenos Aires"), ("C.A.B.A.", "CABA"), ("cordoba ", "Córdoba"), ("LA RIOJA", "La Rioja"),
    ("Rio Negro", "Río Negro"), ("Tierra del Fuego", "Tierra del Fuego"), ("Narnia", "Sin dato"),
])
def test_normaliza_todas_las_provincias(texto, esperado):
    limpio, _ = limpiar_ventas(pd.DataFrame([fila(provincia=texto)]))
    assert limpio.loc[0, "provincia"] == esperado


def test_excluye_cantidades_invalidas():
    crudo = pd.DataFrame([fila(id_pedido="P1"), fila(id_pedido="P2", cantidad="-1"), fila(id_pedido="P3", cantidad="0")])
    limpio, _ = limpiar_ventas(crudo)
    assert list(limpio["id_pedido"]) == ["P1"]


def test_corrige_total_con_cero_de_mas():
    crudo = pd.DataFrame([fila(total="20000")])  # 2 x 1000 debería ser 2000
    limpio, log = limpiar_ventas(crudo)
    assert limpio.loc[0, "total"] == 2000
    assert "1 totales recalculados" in " ".join(log["detalle"])


def test_corrige_precio_mal_cargado_y_conserva_total():
    # El total coincide con el precio habitual del producto: lo que está mal es el precio unitario
    crudo = pd.DataFrame([fila(id_pedido="P1"), fila(id_pedido="P2"),
                          fila(id_pedido="P3", precio_unitario="100000", total="2000")])
    limpio, _ = limpiar_ventas(crudo)
    p3 = limpio.set_index("id_pedido").loc["P3"]
    assert p3["precio_unitario"] == 1000
    assert p3["total"] == 2000


def test_precio_faltante_con_total_imposible_usa_precio_habitual():
    crudo = pd.DataFrame([fila(id_pedido="P1"), fila(id_pedido="P2"),
                          fila(id_pedido="P3", precio_unitario=None, total="200000")])
    limpio, _ = limpiar_ventas(crudo)
    p3 = limpio.set_index("id_pedido").loc["P3"]
    assert p3["precio_unitario"] == 1000
    assert p3["total"] == 2000


def test_lee_csv_con_punto_y_coma(tmp_path):
    ruta = tmp_path / "export.csv"
    pd.DataFrame([fila(total="$ 2.000,00")]).to_csv(ruta, sep=";", index=False)
    crudo = leer_csv(ruta)
    assert list(crudo.columns)[:2] == ["id_pedido", "fecha"]
    limpio, _ = limpiar_ventas(crudo)
    assert limpio.loc[0, "total"] == 2000


def test_completa_precio_faltante():
    crudo = pd.DataFrame([fila(precio_unitario=None, total="$ 3.000,00", cantidad="3")])
    limpio, _ = limpiar_ventas(crudo)
    assert limpio.loc[0, "precio_unitario"] == 1000


def test_marca_faltantes_como_sin_dato():
    crudo = pd.DataFrame([fila(provincia=None, medio_pago=None)])
    limpio, _ = limpiar_ventas(crudo)
    assert limpio.loc[0, "provincia"] == "Sin dato"
    assert limpio.loc[0, "medio_pago"] == "Sin dato"


def test_falla_si_faltan_columnas():
    with pytest.raises(ErrorDeDatos):
        validar_columnas(pd.DataFrame({"fecha": ["2025-01-01"]}))


def test_dataset_real_cumple_controles():
    crudo = pd.read_csv(RAIZ / "data" / "raw" / "ventas_crudas.csv", dtype=str)
    limpio, _ = limpiar_ventas(crudo)
    assert limpio["id_pedido"].is_unique
    assert limpio["fecha"].notna().all()
    assert (limpio["cantidad"] > 0).all()
    assert ((limpio["total"] - limpio["precio_unitario"] * limpio["cantidad"]).abs() < 0.05).all()
