"""
Solid & Sustainable Equity Fund — aplicación web.

Cada vez que alguien entra, descarga los precios del momento (Yahoo Finance) y ejecuta el motor de selección:
  · Portafolio oficial: selección con datos al último cierre de mes (rebalanceo mensual). Es el de la ficha técnica.
  · Selección sugerida hoy: el mismo motor con los precios de hoy; muestra qué entraría o saldría.
Ejecutar localmente:  streamlit run app.py
"""
import glob
import hashlib
import os

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import ficha_pdf
import motor as M

st.set_page_config(page_title="Solid & Sustainable Equity Fund", page_icon="📈", layout="wide")
AQUI = os.path.dirname(os.path.abspath(__file__))
MERCADO_ES = {"EEUU": "EE. UU.", "Taiwan": "Taiwán", "Corea": "Corea del Sur"}
AZUL, ARENA = "#1d5f78", "#c08424"


# ------------------------------------------------------------------ formato
def pct(x, d=1):
    return "—" if pd.isna(x) else f"{x * 100:,.{d}f} %".replace(",", "X").replace(".", ",").replace("X", ".")


def num(x, d=2):
    return "—" if pd.isna(x) else f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def usd(x):
    return "—" if pd.isna(x) else "USD " + f"{x:,.0f}".replace(",", ".")


# ------------------------------------------------------------------ datos
def ruta_ranking():
    c = sorted(glob.glob(os.path.join(AQUI, "data", "ranking*.xlsx")) + glob.glob(os.path.join(AQUI, "ranking*.xlsx")))
    return c[0] if c else None


def ruta_universo():
    for r in (os.path.join(AQUI, "data", "universo.csv"), os.path.join(AQUI, "universo.csv")):
        if os.path.exists(r):
            return r
    return None


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def universo_en_vivo(dia: str):
    """Construye el universo desde la aplicación (solo si aún no existe data/universo.csv). Tarda varios minutos."""
    import universo as U
    barra = st.progress(0.0, text="Descargando fundamentales del universo…")
    u = U.construir_universo(lambda i, n, t: barra.progress(i / n, text=f"Fundamentales {i}/{n} · {t}"), pausa=0.1)
    barra.empty()
    return u


@st.cache_data(ttl=3600, show_spinner="Descargando precios de Yahoo Finance…")
def precios(tickers: tuple, dia: str):
    return M.descargar_precios(list(tickers))


@st.cache_data(ttl=24 * 3600, show_spinner="Actualizando fundamentales desde Yahoo Finance…")
def fundamentales(tickers: tuple, dia: str):
    return M.fundamentales_yahoo(list(tickers))


@st.cache_data(ttl=3600, show_spinner="Ejecutando el motor de selección (54 escenarios)…")
def ejecutar(clave: str, consol: pd.DataFrame, indices: pd.DataFrame, px: pd.DataFrame):
    hoy = px.index.max()
    f_reb = M.fecha_rebalanceo(hoy, px.index)
    d_hoy = M.preparar(consol, indices, px)
    d_of = M.preparar(consol, indices, px, f_reb)
    oficial = M.seleccionar(consol, indices, d_of)
    sugerida = M.seleccionar(consol, indices, d_hoy)
    serie = M.serie_fondo_diaria(oficial, d_hoy)
    comp = pd.DataFrame({c: M.metricas(serie[c], oficial["resumen"]["Rf"], serie["Índice compuesto"]) for c in serie.columns})
    orden = ["Fondo", "Índice compuesto"] + [c for c in comp.columns if c not in ("Fondo", "Índice compuesto")]
    comp = comp[orden]
    periodos = M.rentabilidad_por_periodos(serie["Fondo"])
    tec = pd.DataFrame({a: M.tecnico(d_hoy["diario_loc"][a]) if a in d_hoy["diario_loc"] else {"Lectura técnica": "Sin datos"}
                        for a in oficial["fondo"].index}).T
    return {"oficial": oficial, "sugerida": sugerida, "serie": serie, "comp": comp, "periodos": periodos, "tec": tec,
            "cambios": M.comparar_oficial_hoy(oficial, sugerida, d_hoy), "verif": M.verificar(oficial),
            "verif_hoy": M.verificar(sugerida), "hoy": hoy, "rebalanceo": f_reb}


# ------------------------------------------------------------------ barra lateral
st.sidebar.title("Solid & Sustainable")
st.sidebar.markdown("*Invest with strength, grow with purpose.*")
st.sidebar.caption("Renta variable · EE. UU., Taiwán y Corea del Sur · Perfil arriesgado")
dia = pd.Timestamp.today().strftime("%Y-%m-%d")
r_uni, r_rank = ruta_universo(), ruta_ranking()
usar_fund, fecha_uni = False, None
if r_uni:
    universo, indices, fecha_uni = M.cargar_universo(r_uni)
    fuente_txt = f"Universo automático: {len(universo)} empresas (S&P 500 + Taiwán + Corea)"
else:
    st.sidebar.warning("Aún no existe el universo automático (data/universo.csv).")
    construir = st.sidebar.button("Construir universo ahora (5 a 10 min)", width="stretch")
    subido = None if r_rank else st.sidebar.file_uploader("…o cargue un ranking en Excel (hojas Consolidado e Indices)", type="xlsx")
    if construir or st.session_state.get("universo_en_vivo"):
        st.session_state["universo_en_vivo"] = True
        import universo as U
        universo, indices, fecha_uni = universo_en_vivo(dia), U.INDICES.copy(), dia
        fuente_txt = f"Universo construido en la aplicación: {len(universo)} empresas"
    elif r_rank or subido:
        universo, indices = M.cargar_ranking(r_rank or subido)
        fuente_txt = f"Ranking en Excel (respaldo): {len(universo)} empresas"
        usar_fund = st.sidebar.toggle("Actualizar fundamentales desde Yahoo Finance", value=False,
                                      help="Reemplaza ROA, ROE, liquidez, deuda/capital y PER del ranking por los más recientes de Yahoo.")
        if usar_fund:
            universo = M.aplicar_fundamentales(universo, fundamentales(tuple(universo.index), dia))
    else:
        st.title("Solid & Sustainable Equity Fund")
        st.info("Para iniciar, ejecute la tarea **Actualizar universo de empresas** en la pestaña *Actions* de GitHub "
                "(crea `data/universo.csv`), o use el botón **Construir universo ahora** de la barra lateral.")
        st.stop()
if st.sidebar.button("Actualizar precios ahora", width="stretch"):
    st.cache_data.clear()

# Filtros sin precios (ASG, salud financiera, PER) sobre todo el universo; solo las que pasan van a bursatilidad
consol, pre = M.prefiltro(universo)
if consol.empty:
    st.error("Ninguna empresa del universo pasó los criterios ASG y de salud financiera.")
    st.stop()
tickers = tuple(list(consol.index) + list(indices["Índice"]) + list(M.FX_YF.values()) + ["^IRX"])
try:
    px = precios(tickers, dia)
except Exception as e:
    st.error(f"No fue posible descargar precios de Yahoo Finance ({type(e).__name__}). Intente de nuevo en unos minutos.")
    st.stop()

clave = hashlib.md5((str(px.index.max()) + str(px.shape) + str(usar_fund) + str(consol.values.tobytes()[:2000])).encode()).hexdigest()
try:
    R = ejecutar(clave, consol, indices, px)
except ValueError as e:
    st.error(f"El motor no pudo construir el portafolio: {e}")
    st.stop()

of, sug = R["oficial"], R["sugerida"]
f = of["fondo"]
st.sidebar.markdown(f"**Precios al:** {ficha_pdf.fecha_larga(R['hoy'])}  \n**Portafolio oficial:** rebalanceo del "
                    f"{ficha_pdf.fecha_larga(R['rebalanceo'])}")
st.sidebar.caption(fuente_txt + (f" · fundamentales al {ficha_pdf.fecha_larga(pd.Timestamp(fecha_uni))}" if fecha_uni else ""))
pdf_bytes = ficha_pdf.generar(of, R["serie"], R["periodos"], R["comp"], R["verif"])
st.sidebar.download_button("Descargar ficha técnica (PDF)", pdf_bytes, file_name="Ficha_tecnica_Solid_Sustainable_Equity_Fund.pdf",
                           mime="application/pdf", width="stretch", type="primary")
st.sidebar.caption("Ejercicio académico · Gestión de Portafolios · Universidad del Valle")

# ------------------------------------------------------------------ encabezado
st.title("Solid & Sustainable Equity Fund")
st.markdown("#### *Invest with strength, grow with purpose.*")
st.markdown("Invertimos en empresas líderes de **Estados Unidos, Taiwán y Corea del Sur** que cumplen criterios ASG, tienen "
            "**buena salud financiera** y superan a **su propio índice**. Los pesos se definen con optimización de Markowitz "
            "y se prueban en 54 escenarios. Los precios se actualizan cada vez que usted entra.")
c = st.columns(5)
rs = of["resumen"]
c[0].metric("Rentabilidad esperada", pct(rs["E(R) anual"]))
c[1].metric("Volatilidad esperada", pct(rs["Volatilidad anual"]))
c[2].metric("Sharpe esperado", num(rs["Sharpe"]))
c[3].metric("VaR 95 % · 1 mes", usd(rs["VaR 95 % 1 mes (USD)"]))
c[4].metric(f"Activos ({f['Mercado'].nunique()} mercados)", f"{len(f)}")

n_cambios = (R["cambios"]["Acción sugerida"] != "Mantener").sum()
if n_cambios:
    st.warning(f"**{n_cambios} cambio(s) sugerido(s) frente al portafolio oficial** con los precios de hoy. "
               "Revise la pestaña *Selección y rebalanceo*.")
else:
    st.success("Con los precios de hoy, el portafolio oficial se mantiene: no hay cambios sugeridos.")

tabs = st.tabs(["Ficha del fondo", "Selección y rebalanceo", "Activos frente a su índice", "Metodología", "Sostenibilidad (ASG)"])

# ------------------------------------------------------------------ 1. ficha
with tabs[0]:
    a, b = st.columns([1.1, 1])
    with a:
        st.subheader("Características")
        st.markdown("""
| | |
|---|---|
| **Tipo** | Fondo de inversión colectiva abierto, sin pacto de permanencia |
| **Objetivo** | Crecimiento del capital a largo plazo (más de 5 años) |
| **Perfil de riesgo** | Arriesgado · clase 6 de 7 por volatilidad |
| **Mercados** | Estados Unidos, Taiwán y Corea del Sur |
| **Índice de referencia** | Índice compuesto: índices locales en USD ponderados por país |
| **Inversión mínima** | USD 1.000 · saldo mínimo USD 500 · preaviso de 3 días hábiles |
| **Comisiones** | Administración 2,50 % E.A. · sin comisión de éxito, entrada ni salida |
| **Liquidez** | 5 % · sin derivados ni apalancamiento |
""")
    with b:
        st.subheader("Composición por sector y por país")
        peso_s = f.groupby("Sector")["Peso"].sum().reset_index()
        peso_m = f.groupby("Mercado")["Peso"].sum().reset_index()
        peso_m["Mercado"] = peso_m["Mercado"].map(MERCADO_ES)
        for dfc, col in [(peso_s, "Sector"), (peso_m, "Mercado")]:
            ch = alt.Chart(dfc).mark_bar(color=AZUL).encode(
                x=alt.X("Peso:Q", axis=alt.Axis(format="%"), title=None), y=alt.Y(f"{col}:N", sort="-x", title=None),
                tooltip=[col, alt.Tooltip("Peso:Q", format=".1%")]).properties(height=34 * len(dfc) + 20)
            st.altair_chart(ch, width="stretch")

    st.subheader("Composición del portafolio oficial")
    t = pd.DataFrame({
        "Empresa": f["Empresa"], "Mercado": f["Mercado"].map(MERCADO_ES), "Sector": f["Sector"], "Peso": f["Peso"].map(pct),
        "Monto": f["Monto (USD)"].map(usd), "E(R) anual": f["E(R) anual USD"].map(pct),
        "Volatilidad": f["Volatilidad anual USD"].map(pct), "Beta local": f["Beta local"].map(num),
        "Contribución al riesgo": f["Contribución al riesgo"].map(pct), "Robustez": f["Robustez"].map(lambda x: pct(x, 0)),
        "Técnico": R["tec"]["Lectura técnica"].reindex(f.index)})
    st.dataframe(t, width="stretch")
    st.caption(f"Liquidez: {pct(M.PESO_LIQUIDEZ)}. Pesos sobre el valor total del fondo.")

    st.subheader("Evolución de USD 100.000 invertidos hace 5 años")
    v = (1 + R["serie"].fillna(0)).cumprod() * 100_000
    v = v.reset_index(names="Fecha").melt("Fecha", var_name="Serie", value_name="Valor (USD)")
    ch = alt.Chart(v).mark_line().encode(
        x=alt.X("Fecha:T", title=None), y=alt.Y("Valor (USD):Q", title="USD", axis=alt.Axis(format=",.0f")),
        color=alt.Color("Serie:N", legend=alt.Legend(orient="top", title=None)),
        strokeWidth=alt.condition(alt.datum.Serie == "Fondo", alt.value(2.6), alt.value(1.2)),
        tooltip=["Serie", alt.Tooltip("Fecha:T"), alt.Tooltip("Valor (USD):Q", format=",.0f")]).properties(height=330)
    st.altair_chart(ch, width="stretch")
    st.caption("Simulación con los pesos del portafolio oficial (rebalanceo diario aproximado) y el 5 % de liquidez a la tasa libre de riesgo.")

    a, b = st.columns(2)
    with a:
        st.subheader("Rentabilidad y volatilidad por periodo")
        p = R["periodos"].apply(lambda col: col.map(pct))
        p.index = ["Rentabilidad E.A.", "Volatilidad"]
        st.dataframe(p, width="stretch")
    with b:
        st.subheader("El fondo frente a los índices")
        cm = R["comp"].copy()
        out = pd.DataFrame(index=cm.index, columns=cm.columns, dtype=object)
        for k in cm.index:
            out.loc[k] = [usd(x) if "USD" in k else (num(x) if k.startswith(("Sharpe", "Beta")) else pct(x)) for x in cm.loc[k]]
        st.dataframe(out, width="stretch")
    st.caption("Índice compuesto: S&P 500, TAIEX y KOSPI en dólares, ponderados por el peso del fondo en cada país.")

# ------------------------------------------------------------------ 2. selección y rebalanceo
with tabs[1]:
    st.subheader("Portafolio oficial frente a la selección sugerida hoy")
    st.markdown(f"El **portafolio oficial** se seleccionó con datos al **{ficha_pdf.fecha_larga(R['rebalanceo'])}** "
                f"(rebalanceo mensual). La **selección sugerida** usa los precios al **{ficha_pdf.fecha_larga(R['hoy'])}**. "
                f"Un peso se rebalancea si se desvía más de {pct(M.POLITICA['rebalanceo_puntos'], 0)} de su objetivo.")
    ccc = R["cambios"].copy()
    for col in ["Peso oficial", "Peso actual (por precios)", "Peso sugerido hoy", "Desviación"]:
        ccc[col] = ccc[col].map(pct)
    st.dataframe(ccc, width="stretch")

    tab = sug["tabla"]
    st.subheader("Embudo de selección de hoy")
    pasos = pd.DataFrame({"Etapa": ["Universo", "Cumplen ASG", "Salud financiera Buena", "Superan a su índice (Sharpe y alfa)",
                                    f"Candidatas (mejores {sug.get('candidatos_por_mercado', 5)} por mercado)", "En el portafolio"],
                          "Empresas": [len(pre), int((pre["Criterio ASG"] == "Cumple").sum()),
                                       int(pre["Pasa a bursatilidad"].sum()),
                                       int(tab["Elegible"].sum()), int(tab["Candidato"].sum()), len(sug["pesos"])]})
    ch = alt.Chart(pasos).mark_bar(color=AZUL).encode(x=alt.X("Empresas:Q"), y=alt.Y("Etapa:N", sort=None, title=None),
                                                      tooltip=["Etapa", "Empresas"]).properties(height=230)
    st.altair_chart(ch + ch.mark_text(align="left", dx=4).encode(text="Empresas:Q"), width="stretch")

    st.subheader("Universo completo y motivo de exclusión")
    u = pre[["Empresa", "Mercado", "Sector", "Criterio ASG", "Nivel de salud", "Puntaje de salud"]].join(
        tab[["Sharpe", "Sharpe del índice", "Alfa de Jensen", "Puntaje de bursatilidad", "Candidato", "Motivo de exclusión"]], how="left")
    u["Motivo de exclusión"] = u["Motivo de exclusión"].fillna(pre["Motivo de exclusión"])
    u["Candidato"] = u["Candidato"].fillna(False).astype(bool)
    u = u.sort_values(["Candidato", "Puntaje de bursatilidad"], ascending=False)
    u["Mercado"] = u["Mercado"].map(MERCADO_ES)
    for col in ["Alfa de Jensen"]:
        u[col] = u[col].map(pct)
    for col in ["Puntaje de salud", "Sharpe", "Sharpe del índice", "Puntaje de bursatilidad"]:
        u[col] = u[col].map(num)
    filtro = st.multiselect("Mercado", list(MERCADO_ES.values()), default=list(MERCADO_ES.values()))
    st.dataframe(u[u["Mercado"].isin(filtro)], width="stretch", height=420)

# ------------------------------------------------------------------ 3. activos frente a su índice
with tabs[2]:
    st.subheader("Cada activo frente al índice de su propio mercado")
    st.markdown("Las empresas de EE. UU. se comparan con el **S&P 500**, las de Taiwán con el **TAIEX** y las de Corea con el "
                "**KOSPI**, en moneda local y con la tasa libre de riesgo de cada país (últimos 5 años).")
    ci = pd.DataFrame({
        "Índice": f["Índice local"].map(M.NOMBRE_INDICE), "Rentabilidad del activo": f["Rentabilidad anual"].map(pct),
        "Rentabilidad del índice": f["Rentabilidad del índice"].map(pct), "Sharpe del activo": f["Sharpe"].map(num),
        "Sharpe del índice": f["Sharpe del índice"].map(num), "Beta": f["Beta local"].map(num),
        "Alfa de Jensen": f["Alfa de Jensen"].map(pct), "t del alfa": f["t del alfa"].map(num)})
    st.dataframe(ci, width="stretch")

    st.subheader("Criterios de compra por activo")
    cols = st.columns(2)
    for i, (a, r) in enumerate(f.iterrows()):
        tk = R["tec"].loc[a] if a in R["tec"].index else pd.Series(dtype=object)
        financ = r["Sector"] == "Servicios financieros"
        with cols[i % 2].container(border=True):
            st.markdown(f"**{r['Empresa']}** · `{a}` · {pct(r['Peso'])} del fondo")
            st.markdown(
                f"- **Fundamental:** ROA {pct(r['ROA (Retorno Activos)'])}, ROE {pct(r['ROE (Retorno Capital)'])}"
                + ("" if financ else f", liquidez {num(r['Ratio Liquidez (Current Ratio)'])}x, endeudamiento {pct(r['Endeudamiento'])}")
                + f"; salud **{r['Nivel de salud']}**. PER {num(r['PER (Price/Earnings Ratio)'], 1)} "
                  f"({num(r['PER relativo al sector'])} veces la mediana de su sector).\n"
                f"- **Bursatilidad:** Sharpe {num(r['Sharpe'])} frente a {num(r['Sharpe del índice'])} del "
                f"{M.NOMBRE_INDICE.get(r['Índice local'], r['Índice local'])}; alfa de Jensen {pct(r['Alfa de Jensen'])} anual; "
                f"beta {num(r['Beta local'])} ({'alto riesgo' if r['Alto riesgo'] else 'riesgo moderado'}).\n"
                f"- **Técnico:** {tk.get('Lectura técnica', 'Sin datos')}"
                + (f" · RSI {num(tk.get('RSI 14'), 0)} · {pct(tk.get('Distancia al máximo 52 semanas'))} frente al máximo de 52 semanas"
                   if 'RSI 14' in tk and pd.notna(tk.get('RSI 14')) else "") + ".\n"
                f"- **En el portafolio:** aporta {pct(r['Contribución al riesgo'])} del riesgo; robustez {pct(r['Robustez'], 0)}.\n"
                f"- **ASG:** {r['Criterio ASG']}. {r['Nota ASG']}")

# ------------------------------------------------------------------ 4. metodología
with tabs[3]:
    st.subheader("Cómo se eligen los activos")
    st.markdown("""
0. **Universo.** Todas las empresas del S&P 500 y las mayores de las bolsas de Taiwán y Corea del Sur (cerca de 600). Sus
   fundamentales se descargan de Yahoo Finance cada noche, de modo que cualquier empresa nueva que cumpla los criterios puede entrar.
1. **Criterios ASG.** Se excluyen armas controvertidas, tabaco y carbón térmico (por nombre, sector e industria).
2. **Filtro 1 · salud financiera (fundamentales).** Semáforo de ROA (> 6 %), ROE (> 12 %), liquidez corriente (> 1,5x) y
   endeudamiento (< 50 %). Cada indicador vale 2, 1 o 0 puntos; solo pasan las empresas con promedio ≥ 1,5 (nivel Bueno).
   En bancos y aseguradoras solo cuentan ROA y ROE. También se excluyen PER ≤ 0 y patrimonio negativo.
3. **Filtro 2 · bursatilidad frente al índice local.** Con 5 años de precios mensuales en moneda local, cada empresa debe tener
   un Sharpe mayor que el de su índice (S&P 500, TAIEX o KOSPI) y alfa de Jensen positivo. Luego se ordenan, con igual peso, por
   Sharpe y rentabilidad frente al índice y por PER frente al sector; pasan las 5 mejores de cada mercado.
4. **Optimización.** Máximo Sharpe de Markowitz en USD, con rentabilidad esperada ½ histórica + ½ CAPM local llevado a USD
   por paridad de tasas, y la política del fondo.
5. **Robustez.** La optimización se repite en 54 escenarios (3 ventanas × 2 métodos × 3 topes × 3 tasas). El portafolio final
   usa solo activos que aparecen en al menos 80 % de ellos; si no alcanzan, se completa con los siguientes más robustos.
6. **Rebalanceo.** La selección oficial se renueva cada mes con los datos al cierre del mes anterior; entre revisiones, un peso
   se ajusta si se desvía más de 3 puntos o si el activo deja de cumplir un filtro.
""")
    st.subheader("Verificación del portafolio oficial")
    st.dataframe(R["verif"], width="stretch", hide_index=True)
    if of.get("candidatos_por_mercado", M.CANDIDATOS_POR_MERCADO) > M.CANDIDATOS_POR_MERCADO:
        st.info(f"Con las {M.CANDIDATOS_POR_MERCADO} mejores de cada mercado la política no era factible; el motor amplió las "
                f"candidatas a las {of['candidatos_por_mercado']} mejores de cada mercado, en orden del puntaje de bursatilidad.")
    if of["completados"]:
        st.info("Se completó con activos de robustez menor a 80 % para cumplir la política: " + ", ".join(of["completados"]))

# ------------------------------------------------------------------ 5. ASG
with tabs[4]:
    st.subheader("Política de sostenibilidad")
    st.markdown("""
- **Exclusiones:** armas controvertidas (minas, municiones de racimo, químicas y biológicas), tabaco y carbón térmico.
- **Transición energética:** la energía fósil no puede superar el 20 % del fondo.
- **Evaluación y seguimiento:** cada emisor se revisa antes de la compra; las notas de seguimiento quedan en la ficha.
- **Gobierno corporativo:** voto informado y diálogo con los emisores.
""")
    ex = pre.loc[pre["Criterio ASG"] != "Cumple", ["Empresa", "Mercado", "Sector", "Criterio ASG"]]
    st.markdown("**Empresas del universo excluidas por ASG**")
    st.dataframe(ex if len(ex) else pd.DataFrame({"Resultado": ["Ninguna empresa del universo cae en las exclusiones."]}),
                 width="stretch")
    notas = f.loc[f["Nota ASG"] != "", ["Empresa", "Nota ASG"]]
    if len(notas):
        st.markdown("**Notas de seguimiento**")
        st.dataframe(notas, width="stretch")

st.divider()
st.caption("Advertencia: ejercicio académico del curso Gestión de Portafolios, Universidad del Valle. Las rentabilidades esperadas y "
           "las simulaciones históricas no garantizan rentabilidades futuras. Fuente de precios: Yahoo Finance.")
