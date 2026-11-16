"""
Genera el dataset simulado de ventas de "Almacén Online Ejemplo" (empresa ficticia).

El archivo resultante imita una exportación real "sucia" de un sistema de ventas:
- filas duplicadas
- fechas en varios formatos
- montos con formato argentino ("$ 1.234,50") mezclados con números
- nombres de provincia y categoría escritos de distintas formas
- valores faltantes y algunos errores de carga (cantidades negativas, montos absurdos)

Uso:
    python src/generar_datos.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEMILLA = 42
N_PEDIDOS = 5000
SALIDA = Path(__file__).resolve().parents[1] / "data" / "raw" / "ventas_crudas.csv"

rng = np.random.default_rng(SEMILLA)

PROVINCIAS = {
    "Buenos Aires": 0.38, "CABA": 0.20, "Córdoba": 0.12, "Santa Fe": 0.10,
    "Mendoza": 0.06, "Tucumán": 0.04, "Entre Ríos": 0.04, "Salta": 0.03,
    "Neuquén": 0.03,
}
# Variantes "mal escritas" que aparecen en exportaciones reales
VARIANTES_PROV = {
    "Buenos Aires": ["Buenos Aires", "BUENOS AIRES", "Bs As", "Bs. As.", "buenos aires"],
    "CABA": ["CABA", "Capital Federal", "C.A.B.A.", "Ciudad de Buenos Aires"],
    "Córdoba": ["Córdoba", "Cordoba", "CORDOBA", "córdoba "],
    "Santa Fe": ["Santa Fe", "Santa fe", "SANTA FE"],
    "Mendoza": ["Mendoza", "mendoza"],
    "Tucumán": ["Tucumán", "Tucuman"],
    "Entre Ríos": ["Entre Ríos", "Entre Rios"],
    "Salta": ["Salta"],
    "Neuquén": ["Neuquén", "Neuquen"],
}

PRODUCTOS = {
    # categoría: [(producto, precio_base_ars)]
    "Almacén": [("Yerba 1kg", 4200), ("Aceite girasol 1.5L", 3900), ("Fideos 500g", 1300),
                ("Arroz 1kg", 1700), ("Café molido 500g", 7800)],
    "Bebidas": [("Gaseosa 2.25L", 2900), ("Agua 2L", 1200), ("Vino Malbec 750ml", 6500),
                ("Cerveza lata x6", 7200)],
    "Limpieza": [("Detergente 750ml", 2100), ("Lavandina 2L", 1500), ("Jabón polvo 3kg", 9800)],
    "Perfumería": [("Shampoo 400ml", 4300), ("Desodorante", 3100), ("Pasta dental", 2000)],
}
VARIANTES_CAT = {
    "Almacén": ["Almacén", "Almacen", "ALMACEN"],
    "Bebidas": ["Bebidas", "bebidas", "BEBIDAS"],
    "Limpieza": ["Limpieza", "limpieza"],
    "Perfumería": ["Perfumería", "Perfumeria"],
}
MEDIOS_PAGO = ["Mercado Pago", "Tarjeta de crédito", "Tarjeta de débito", "Transferencia", "Efectivo"]
PESOS_PAGO = [0.40, 0.25, 0.15, 0.15, 0.05]


def formato_fecha(fecha: pd.Timestamp) -> str:
    """Devuelve la fecha en uno de varios formatos, como pasa al unir exportaciones distintas."""
    opcion = rng.choice(4, p=[0.55, 0.25, 0.15, 0.05])
    if opcion == 0:
        return fecha.strftime("%Y-%m-%d")
    if opcion == 1:
        return fecha.strftime("%d/%m/%Y")
    if opcion == 2:
        return fecha.strftime("%d-%m-%Y")
    return fecha.strftime("%d/%m/%y")


def formato_monto(valor: float) -> str:
    """Mezcla números simples con montos en formato argentino."""
    if rng.random() < 0.35:
        entero, dec = f"{valor:,.2f}".split(".")
        return "$ " + entero.replace(",", ".") + "," + dec
    return f"{valor:.2f}"


def main() -> None:
    fechas = pd.date_range("2025-01-01", "2025-12-31", freq="D")
    # Más ventas en diciembre y de viernes a domingo
    peso_mes = np.array([0.9, 0.85, 0.95, 1.0, 1.0, 0.95, 1.05, 1.0, 0.95, 1.05, 1.15, 1.45])
    pesos = peso_mes[fechas.month - 1] * np.where(fechas.dayofweek >= 4, 1.25, 1.0)
    pesos = pesos / pesos.sum()

    # Inflación mensual simulada aproximada: los precios suben a lo largo del año
    indice_precio = np.cumprod(np.r_[1.0, np.full(11, 1.025)])

    filas = []
    totales_reales = []
    for i in range(N_PEDIDOS):
        fecha = fechas[rng.choice(len(fechas), p=pesos)]
        prov = rng.choice(list(PROVINCIAS), p=list(PROVINCIAS.values()))
        cat = rng.choice(list(PRODUCTOS), p=[0.40, 0.30, 0.18, 0.12])
        prod, precio_base = PRODUCTOS[cat][rng.integers(len(PRODUCTOS[cat]))]
        cantidad = int(rng.choice([1, 1, 1, 2, 2, 3, 4, 6]))
        precio = precio_base * indice_precio[fecha.month - 1] * rng.uniform(0.95, 1.05)
        total = round(precio * cantidad, 2)
        totales_reales.append(total)

        filas.append({
            "id_pedido": f"P{10000 + i}",
            "fecha": formato_fecha(fecha),
            "cliente_id": f"C{rng.integers(1, 1400):04d}",
            "provincia": rng.choice(VARIANTES_PROV[prov]),
            "categoria": rng.choice(VARIANTES_CAT[cat]),
            "producto": prod,
            "cantidad": cantidad,
            "precio_unitario": round(precio, 2),
            "total": formato_monto(total),
            "medio_pago": rng.choice(MEDIOS_PAGO, p=PESOS_PAGO),
        })

    df = pd.DataFrame(filas)

    # --- Ensuciar los datos como en una exportación real ---
    n = len(df)
    # Faltantes
    for col, frac in [("provincia", 0.03), ("medio_pago", 0.04), ("cliente_id", 0.02), ("precio_unitario", 0.02)]:
        idx = rng.choice(n, int(n * frac), replace=False)
        df.loc[idx, col] = np.nan
    # Errores de carga: cantidades negativas o cero
    idx = rng.choice(n, 25, replace=False)
    df.loc[idx, "cantidad"] = rng.choice([-1, -2, 0], 25)
    # Totales que perdieron la coma decimal al importarse: "5042,21" quedó como 504221
    idx = rng.choice(n, 8, replace=False)
    for j in idx:
        df.loc[j, "total"] = f"{round(totales_reales[j] * 100):d}"
    # Espacios extra en texto
    idx = rng.choice(n, 150, replace=False)
    df.loc[idx, "producto"] = "  " + df.loc[idx, "producto"] + " "
    # Duplicados exactos (se exportó dos veces el mismo pedido)
    dup = df.sample(120, random_state=SEMILLA)
    df = pd.concat([df, dup], ignore_index=True).sample(frac=1, random_state=SEMILLA).reset_index(drop=True)

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(SALIDA, index=False, encoding="utf-8")
    print(f"Generado {SALIDA} con {len(df)} filas")


if __name__ == "__main__":
    main()
