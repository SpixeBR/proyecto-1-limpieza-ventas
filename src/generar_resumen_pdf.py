"""
Genera docs/resumen_ejecutivo.pdf: una página para el dueño del negocio con los
números clave y tres recomendaciones. Las cifras se calculan desde los datos.

Uso:
    python src/generar_resumen_pdf.py
"""
import sys
from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
from limpiar_datos import limpiar_ventas, parsear_monto  # noqa: E402

AZUL = colors.HexColor("#1c5cab")
GRIS = colors.HexColor("#52514e")


def miles(v: float) -> str:
    return f"{v:,.0f}".replace(",", ".")


def calcular() -> dict:
    crudo = pd.read_csv(RAIZ / "data" / "raw" / "ventas_crudas.csv", dtype=str)
    df, _ = limpiar_ventas(crudo)
    sin_dup = crudo.drop_duplicates()
    cant = pd.to_numeric(sin_dup["cantidad"], errors="coerce")
    total_sin_corregir = sin_dup.loc[cant > 0, "total"].map(parsear_monto).sum()

    unidades_mes = df.groupby(df["fecha"].dt.month)["cantidad"].sum()
    prov = df.groupby("provincia")["total"].sum().drop("Sin dato", errors="ignore").sort_values(ascending=False)
    cat = df.groupby("categoria")["total"].sum()
    por_dia = df.groupby([df["fecha"].dt.date, df["fecha"].dt.dayofweek]).size().groupby(level=1).mean()
    pago = df["medio_pago"].value_counts(normalize=True)
    return {
        "filas_crudas": len(crudo), "pedidos": len(df), "facturacion": df["total"].sum(),
        "sobreestimacion": total_sin_corregir / df["total"].sum() - 1,
        "dic_vs_resto": unidades_mes[12] / unidades_mes.loc[1:11].mean() - 1,
        "top3": prov.head(3), "top3_share": prov.head(3).sum() / df["total"].sum(),
        "alm_beb": (cat["Almacén"] + cat["Bebidas"]) / cat.sum(),
        "finde": por_dia.loc[4:6].mean() / por_dia.loc[0:3].mean() - 1,
        "mp": pago["Mercado Pago"],
    }


def main() -> None:
    d = calcular()
    salida = RAIZ / "docs" / "resumen_ejecutivo.pdf"
    salida.parent.mkdir(exist_ok=True)

    titulo = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=18, leading=23, textColor=AZUL, spaceAfter=2)
    sub = ParagraphStyle("s", fontName="Helvetica", fontSize=9.5, textColor=GRIS, spaceAfter=14)
    h = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=11.5, spaceBefore=10, spaceAfter=4)
    p = ParagraphStyle("p", fontName="Helvetica", fontSize=10.2, leading=14.5)
    pie = ParagraphStyle("pie", fontName="Helvetica-Oblique", fontSize=8, textColor=GRIS)

    kpis = [["Facturación 2025", "Pedidos válidos", "Diciembre vs. promedio", "Top 3 provincias"],
            [f"$ {miles(d['facturacion'])}", miles(d["pedidos"]), f"+{d['dic_vs_resto']:.0%} unidades",
             f"{d['top3_share']:.0%} de la facturación"]]
    tabla = Table(kpis, colWidths=[4.25 * cm] * 4, hAlign="LEFT")
    tabla.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica", 8.5), ("TEXTCOLOR", (0, 0), (-1, 0), GRIS),
        ("FONT", (0, 1), (-1, 1), "Helvetica-Bold", 11.5),
        ("LINEABOVE", (0, 0), (-1, 0), 2, colors.HexColor("#2a78d6")),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))

    provs = ", ".join(d["top3"].index[:-1]) + " y " + d["top3"].index[-1]
    contenido = [
        Paragraph("Resumen ejecutivo · Ventas 2025", titulo),
        Paragraph("Almacén Online Ejemplo · caso de portfolio con datos simulados", sub),
        tabla, Spacer(1, 10),

        Paragraph("1. Los datos de ventas no son confiables tal como se cargan hoy", h),
        Paragraph(
            f"De {miles(d['filas_crudas'])} registros exportados, solo {miles(d['pedidos'])} son pedidos válidos: había "
            f"duplicados, cantidades negativas y totales que perdieron la coma decimal al importarse. Sin corregirlos, la facturación "
            f"anual aparece un <b>{d['sobreestimacion']:.0%} más alta</b> de lo que realmente es, y cualquier decisión "
            f"de compra o de precios se toma sobre un número falso. <b>Recomendación:</b> agregar validaciones en el "
            f"sistema de carga (cantidad mayor a cero, total igual a precio por cantidad, provincias de una lista "
            f"cerrada) y correr el script de limpieza cada mes antes de armar los reportes.", p),

        Paragraph("2. Planificar el año alrededor de diciembre y de los fines de semana", h),
        Paragraph(
            f"En diciembre se venden un <b>{d['dic_vs_resto']:.0%} más de unidades</b> que en el promedio del resto "
            f"del año, y noviembre ya muestra la suba. Además, de viernes a domingo entran un {d['finde']:.0%} más de "
            f"pedidos por día. <b>Recomendación:</b> reforzar stock y logística desde fines de octubre, concentrar "
            f"las promociones de fin de semana en los productos que más facturan y medir el crecimiento en unidades, "
            f"no solo en pesos, para que la inflación no oculte si el negocio crece de verdad.", p),

        Paragraph("3. Crecer fuera de los mercados donde ya estamos fuertes", h),
        Paragraph(
            f"{provs} concentran el <b>{d['top3_share']:.0%} de la facturación</b>, y Almacén y Bebidas generan el "
            f"{d['alm_beb']:.0%} de los ingresos. Esa concentración es una fortaleza, pero también un riesgo. Mercado "
            f"Pago ya es el medio de pago principal ({d['mp']:.0%} de los pedidos) y el ticket promedio es parecido "
            f"en todos los medios, así que no hace falta incentivar el cambio de forma de pago. <b>Recomendación:</b> "
            f"probar campañas segmentadas en el interior (Mendoza, Tucumán, Salta, Neuquén) y usar Limpieza y "
            f"Perfumería como productos complementarios en los pedidos de Almacén.", p),
        Spacer(1, 18),
        Paragraph("Cifras calculadas automáticamente desde los datos con src/generar_resumen_pdf.py. "
                  "Empresa y datos ficticios, creados para mostrar el proceso de análisis.", pie),
    ]
    SimpleDocTemplate(str(salida), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                      topMargin=1.8 * cm, bottomMargin=1.5 * cm, title="Resumen ejecutivo · Ventas 2025").build(contenido)
    print(f"PDF generado: {salida}")


if __name__ == "__main__":
    main()
