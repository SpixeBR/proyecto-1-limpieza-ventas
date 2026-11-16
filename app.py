"""
Dashboard interactivo de ventas (Streamlit).

Ejecutar:
    streamlit run app.py

Lee data/processed/ventas_limpias.csv (generado por src/limpiar_datos.py).
"""
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

RUTA_DATOS = Path(__file__).parent / "data" / "processed" / "ventas_limpias.csv"
AZUL, GRIS = "#2a78d6", "#c9c8c2"
MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

st.set_page_config(page_title="Dashboard de ventas", page_icon="📊", layout="wide")


def pesos(valor: float) -> str:
    """Formato argentino: $ 1.234.567"""
    return "$ " + f"{valor:,.0f}".replace(",", ".")


@st.cache_data
def cargar_datos(ruta: Path) -> pd.DataFrame:
    df = pd.read_csv(ruta, parse_dates=["fecha"])
    df["mes"] = df["fecha"].dt.to_period("M").dt.to_timestamp()
    return df


def estilo(fig, formato_x: str | None = None, formato_y: str | None = None):
    """Estilo común: fondo limpio, sin leyenda, grilla suave y números en formato argentino."""
    fig.update_layout(margin={"l": 10, "r": 10, "t": 10, "b": 10}, height=340, showlegend=False,
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", bargap=0.3,
                      separators=",.")  # coma decimal, punto de miles
    fig.update_xaxes(showgrid=False, title=None, tickformat=formato_x)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.2)", title=None, tickformat=formato_y)
    return fig


# ------------------------------------------------------------------ datos y filtros
if not RUTA_DATOS.exists():
    st.error("No se encontró `data/processed/ventas_limpias.csv`. Ejecutá primero:\n\n"
             "`python src/limpiar_datos.py data/raw/ventas_crudas.csv data/processed/ventas_limpias.csv`")
    st.stop()

datos = cargar_datos(RUTA_DATOS)
meses_disp = list(pd.DatetimeIndex(datos["mes"].unique()).sort_values())
etiqueta_mes = {m: f"{MESES[pd.Timestamp(m).month - 1]} {pd.Timestamp(m).year}" for m in meses_disp}

with st.sidebar:
    st.header("Filtros")
    desde, hasta = st.select_slider("Período", options=meses_disp, value=(meses_disp[0], meses_disp[-1]),
                                    format_func=lambda m: etiqueta_mes[m])
    provincias = sorted(datos["provincia"].unique(), key=lambda p: (p == "Sin dato", p))
    elegidas = st.multiselect("Provincias", provincias, default=provincias)
    st.caption("Datos simulados de un e-commerce ficticio (2025).")

df = datos[(datos["mes"] >= desde) & (datos["mes"] <= hasta) & (datos["provincia"].isin(elegidas))]

st.title("Ventas 2025 · Almacén Online Ejemplo")
if df.empty:
    st.warning("No hay ventas con estos filtros.")
    st.stop()

# ------------------------------------------------------------------ KPIs
c1, c2, c3, c4 = st.columns(4)
c1.metric("Facturación", pesos(df["total"].sum()))
c2.metric("Pedidos", f"{len(df):,}".replace(",", "."))
c3.metric("Unidades", f"{df['cantidad'].sum():,}".replace(",", "."))
c4.metric("Ticket promedio", pesos(df["total"].mean()))

# ------------------------------------------------------------------ gráficos
izq, der = st.columns(2)

with izq:
    st.subheader("Evolución mensual")
    metrica = st.radio("Métrica", ["Facturación", "Unidades"], horizontal=True, label_visibility="collapsed",
                       help="La facturación está en pesos corrientes e incluye aumentos de precio; las unidades muestran el volumen real.")
    col = "total" if metrica == "Facturación" else "cantidad"
    mensual = df.groupby("mes", as_index=False)[col].sum()
    mensual["etiqueta"] = mensual["mes"].map(lambda m: etiqueta_mes[m])
    # Eje x con los nombres de mes en español (el formato de fecha de Plotly los muestra en inglés)
    fig = px.line(mensual, x="etiqueta", y=col, markers=True)
    fig.update_traces(line={"color": AZUL, "width": 2.5}, marker={"size": 7},
                      hovertemplate="%{x}<br>" + ("$ %{y:,.0f}" if col == "total" else "%{y:,} unidades") + "<extra></extra>")
    fig.update_yaxes(rangemode="tozero")
    st.plotly_chart(estilo(fig, formato_y="$,.2s" if col == "total" else ",d"))

with der:
    st.subheader("Top productos")
    n_top = st.slider("Cantidad de productos", 5, 15, 8, label_visibility="collapsed")
    top = df.groupby("producto", as_index=False)["total"].sum().nlargest(n_top, "total").sort_values("total")
    fig = px.bar(top, x="total", y="producto", orientation="h")
    fig.update_traces(marker_color=AZUL, hovertemplate="%{y}<br>$ %{x:,.0f}<extra></extra>")
    st.plotly_chart(estilo(fig, formato_x="$,.2s"))

izq, der = st.columns(2)

with izq:
    st.subheader("Facturación por provincia")
    prov = df.groupby("provincia", as_index=False)["total"].sum().sort_values("total")
    prov["participacion"] = prov["total"] / prov["total"].sum()
    fig = px.bar(prov, x="total", y="provincia", orientation="h", custom_data=["participacion"],
                 text=prov["participacion"].map(lambda p: f"{p:.0%}"))
    fig.update_traces(marker_color=[GRIS if p == "Sin dato" else AZUL for p in prov["provincia"]],
                      textposition="outside", cliponaxis=False,
                      hovertemplate="%{y}<br>$ %{x:,.0f} · %{customdata[0]:.1%}<extra></extra>")
    st.plotly_chart(estilo(fig, formato_x="$,.2s"))

with der:
    st.subheader("Medios de pago")
    pago = df.groupby("medio_pago").agg(pedidos=("id_pedido", "count"), ticket=("total", "mean")).reset_index()
    pago["porcentaje"] = pago["pedidos"] / pago["pedidos"].sum()
    pago = pago.sort_values("pedidos")
    fig = px.bar(pago, x="porcentaje", y="medio_pago", orientation="h", custom_data=["pedidos", "ticket"],
                 text=pago["porcentaje"].map(lambda p: f"{p:.0%}"))
    fig.update_traces(marker_color=[GRIS if m == "Sin dato" else AZUL for m in pago["medio_pago"]],
                      textposition="outside", cliponaxis=False,
                      hovertemplate="%{y}<br>%{x:.1%} de los pedidos (%{customdata[0]:,})"
                                    "<br>Ticket promedio $ %{customdata[1]:,.0f}<extra></extra>")
    st.plotly_chart(estilo(fig, formato_x=".0%"))

# ------------------------------------------------------------------ detalle
with st.expander("Ver datos filtrados"):
    st.dataframe(df.drop(columns="mes"), hide_index=True)
    st.download_button("Descargar CSV", df.drop(columns="mes").to_csv(index=False).encode("utf-8"),
                       file_name="ventas_filtradas.csv", mime="text/csv")
