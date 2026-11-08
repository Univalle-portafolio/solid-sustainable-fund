"""
Solidez Sostenible Renta Variable — aplicación web.

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
import frontera_excel
import motor as M

st.set_page_config(page_title="Solidez Sostenible Renta Variable", page_icon="📈", layout="wide")
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


def _antes_despues(oficial, d_of, d_hoy, serie):
    """Compara el portafolio concentrado (método anterior, sin regla de sectores) con el fondo diversificado."""
    w_c = oficial.get("concentrado")
    if w_c is None:
        return None
    tabla, rf = oficial["tabla"], oficial["rf"]
    mu, S, _ = M.insumos(tabla, d_of, oficial["rf_local"], list(w_c.index))
    w_acc = w_c[mu.index] / w_c[mu.index].sum()
    s_acc = float(np.sqrt(w_acc @ S.values @ w_acc))
    e_c, s_c = M.ACC * float(w_acc @ mu) + M.PESO_LIQUIDEZ * rf, M.ACC * s_acc
    fondo_c = pd.DataFrame({"Mercado": tabla.loc[w_c.index, "Mercado"], "Peso": w_c})
    serie_c = M.serie_fondo_diaria({"pesos": w_c, "fondo": fondo_c, "resumen": {"Rf": rf}}, d_hoy)
    filas = {}
    for nombre, e, s, n, sec, mx, sr in [
        ("Antes: concentrado (máximo Sharpe sin regla de sectores)", e_c, s_c, len(w_c), tabla.loc[w_c.index, "Sector"].nunique(),
         w_c.groupby(tabla.loc[w_c.index, "Sector"]).sum().max(), serie_c["Fondo"]),
        ("Ahora: diversificado (5 sectores con igual peso)", oficial["resumen"]["E(R) anual"], oficial["resumen"]["Volatilidad anual"],
         len(oficial["pesos"]), oficial["fondo"]["Sector"].nunique(), oficial["fondo"].groupby("Sector")["Peso"].sum().max(),
         serie["Fondo"])]:
        m = M.metricas(sr, rf)
        per = M.rentabilidad_por_periodos(sr)
        filas[nombre] = {"Activos": str(n), "Sectores": str(sec), "Mayor peso en un sector": m_pct(mx),
                         "Rentabilidad esperada": m_pct(e), "Volatilidad esperada": m_pct(s), "Sharpe esperado": m_num((e - rf) / s),
                         "VaR 95 % a 1 mes": m_pct(M.var_mensual(s)),
                         f"Rentabilidad anual histórica ({M.VENTANA_ANIOS} años)": m_pct(m["Rentabilidad anual"]),
                         "Volatilidad histórica": m_pct(m["Volatilidad anual"]), "Máxima caída histórica": m_pct(m["Máxima caída"]),
                         "Rentabilidad del último mes": m_pct(per.loc["Rentabilidad del periodo", "Último mes"])}
    return pd.DataFrame(filas)


def m_pct(x):
    return "—" if pd.isna(x) else f"{x * 100:,.1f} %".replace(".", ",")


def m_num(x):
    return "—" if pd.isna(x) else f"{x:,.2f}".replace(".", ",")


@st.cache_data(ttl=3600, show_spinner="Ejecutando el motor: combinaciones de sectores y 54 escenarios (puede tardar un minuto)…")
def ejecutar(clave: str, consol: pd.DataFrame, indices: pd.DataFrame, px: pd.DataFrame):
    hoy = px.index.max()
    f_reb = M.fecha_rebalanceo(hoy, px.index)
    d_hoy = M.preparar(consol, indices, px)
    d_of = M.preparar(consol, indices, px, f_reb)
    oficial = M.seleccionar(consol, indices, d_of)
    try:
        sugerida, sug_error = M.seleccionar(consol, indices, d_hoy, con_robustez=False), None
    except ValueError as e:      # con los precios de hoy no se arma un portafolio: se mantiene el oficial
        sugerida, sug_error = oficial, str(e)
    serie = M.serie_fondo_diaria(oficial, d_hoy)
    comp = pd.DataFrame({c: M.metricas(serie[c], oficial["resumen"]["Rf"], serie["Índice compuesto"]) for c in serie.columns})
    orden = ["Fondo", "Índice compuesto"] + [c for c in comp.columns if c not in ("Fondo", "Índice compuesto")]
    comp = comp[orden]
    periodos = M.rentabilidad_por_periodos(serie["Fondo"])
    tec = pd.DataFrame({a: M.tecnico(d_hoy["diario_loc"][a]) if a in d_hoy["diario_loc"] else {"Lectura técnica": "Sin datos"}
                        for a in oficial["fondo"].index}).T
    try:
        antes = _antes_despues(oficial, d_of, d_hoy, serie)
    except Exception:
        antes = None
    return {"oficial": oficial, "sugerida": sugerida, "serie": serie, "comp": comp, "periodos": periodos, "tec": tec,
            "cambios": M.comparar_oficial_hoy(oficial, sugerida, d_hoy), "verif": M.verificar(oficial, comp),
            "verif_hoy": M.verificar(sugerida), "hoy": hoy, "rebalanceo": f_reb, "antes_despues": antes, "sug_error": sug_error,
            "excel": frontera_excel.generar(oficial, d_of)}


# ------------------------------------------------------------------ barra lateral
st.sidebar.title("Solidez Sostenible")
st.sidebar.markdown(f"*{M.ESLOGAN}*")
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
        st.title(M.NOMBRE_FONDO)
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
    if isinstance(e, M.SectoresInsuficientes):
        st.subheader("Diagnóstico por sector")
        st.markdown("Empresas de cada sector que pasan cada filtro, de forma acumulada (datos del rebalanceo mensual). "
                    "La última columna debe tener al menos 1 empresa en 5 sectores.")
        st.dataframe(M.diagnostico_sectores(pre, e.tabla), width="stretch")
    st.stop()

of, sug = R["oficial"], R["sugerida"]
f = of["fondo"]
st.sidebar.markdown(f"**Precios al:** {ficha_pdf.fecha_larga(R['hoy'])}  \n**Portafolio oficial:** rebalanceo del "
                    f"{ficha_pdf.fecha_larga(R['rebalanceo'])}")
st.sidebar.caption(fuente_txt + (f" · fundamentales al {ficha_pdf.fecha_larga(pd.Timestamp(fecha_uni))}" if fecha_uni else ""))
pdf_bytes = ficha_pdf.generar(of, R["serie"], R["periodos"], R["comp"], R["verif"])
st.sidebar.download_button("Descargar ficha técnica (PDF)", pdf_bytes, file_name="Ficha_tecnica_Solidez_Sostenible_Renta_Variable.pdf",
                           mime="application/pdf", width="stretch", type="primary")
st.sidebar.download_button("Descargar frontera eficiente (Excel)", R["excel"], file_name="Frontera_eficiente_Solidez_Sostenible.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
st.sidebar.caption("Ejercicio académico · Gestión de Portafolios · Universidad del Valle")

# ------------------------------------------------------------------ encabezado
st.title(M.NOMBRE_FONDO)
st.markdown(f"#### *{M.ESLOGAN}*")
st.markdown("Invertimos en empresas líderes de **Estados Unidos, Taiwán y Corea del Sur** que cumplen criterios ASG, tienen "
            "**buena salud financiera**, superan a **su propio índice** y están en **tendencia alcista de largo plazo** (compramos en los retrocesos). El fondo se "
            "reparte en **5 sectores con igual peso**; dentro de cada sector los pesos se definen con Markowitz y el riesgo se "
            "limita a un **VaR mensual de 8 %**. Los precios se actualizan cada vez que usted entra.")
c = st.columns(5)
rs = of["resumen"]
c[0].metric("Rentabilidad esperada", pct(rs["E(R) anual"]))
c[1].metric("Volatilidad esperada", pct(rs["Volatilidad anual"]))
c[2].metric("Sharpe esperado", num(rs["Sharpe"]))
c[3].metric(f"VaR 95 % · 1 mes ({usd(rs['VaR 95 % 1 mes (USD)'])})", pct(rs["VaR 95 % 1 mes (%)"]))
c[4].metric("Activos · sectores", f"{len(f)} · {f['Sector'].nunique()}")

n_cambios = (R["cambios"]["Acción sugerida"] != "Mantener").sum()
if R.get("sug_error"):
    st.info(f"Con los precios de hoy no se puede armar una selección nueva ({R['sug_error']}); se mantiene el portafolio "
            "oficial del mes. El diagnóstico por sector está en la pestaña *Selección y rebalanceo*.")
elif n_cambios:
    st.warning(f"**{n_cambios} cambio(s) sugerido(s) frente al portafolio oficial** con los precios de hoy. "
               "Revise la pestaña *Selección y rebalanceo*.")
else:
    st.success("Con los precios de hoy, el portafolio oficial se mantiene: no hay cambios sugeridos.")

tabs = st.tabs(["Ficha del fondo", "Selección y rebalanceo", "Activos frente a su índice", "Frontera eficiente", "Metodología",
                "Sostenibilidad (ASG)"])

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
| **Perfil de riesgo** | Arriesgado: 95 % en acciones y ≥ 50 % en alto riesgo (β > 1) · VaR 95 % mensual ≤ 8 % |
| **Asignación** | 5 sectores con igual peso (19 % cada uno), hasta 2 empresas por sector |
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
        "Técnico al seleccionar": f["Lectura técnica"], "Técnico hoy": R["tec"]["Lectura técnica"].reindex(f.index)})
    st.dataframe(t, width="stretch")
    st.caption(f"Liquidez: {pct(M.PESO_LIQUIDEZ)}. Pesos sobre el valor total del fondo.")

    st.subheader(f"Evolución de USD 100.000 invertidos hace {M.VENTANA_ANIOS} años")
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
        ref = M.rentabilidad_por_periodos(R["serie"]["Índice compuesto"]).loc[["Rentabilidad E.A."]].apply(lambda col: col.map(pct))
        ref.index = ["Índice compuesto (E.A.)"]
        st.dataframe(pd.concat([p, ref]), width="stretch")
        st.caption("Los plazos menores a un año se anualizan (E.A.), como exige el formato de ficha técnica; la fila "
                   "«Rentabilidad del periodo» muestra la variación efectiva sin anualizar.")
    with b:
        st.subheader("El fondo frente a los índices")
        cm = R["comp"].copy()
        out = pd.DataFrame(index=cm.index, columns=cm.columns, dtype=object)
        for k in cm.index:
            out.loc[k] = [usd(x) if "USD" in k else (num(x) if k.startswith(("Sharpe", "Beta", "Treynor", "Information")) else pct(x))
                          for x in cm.loc[k]]
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
                                    "Técnico y Q de Tobin (pasan todos los filtros)",
                                    f"Candidatas (hasta 2 por sector · {len(sug['sectores_disponibles'])} sectores)",
                                    "En el portafolio (5 sectores)"],
                          "Empresas": [len(pre), int((pre["Criterio ASG"] == "Cumple").sum()),
                                       int(pre["Pasa a bursatilidad"].sum()), int(tab["Supera a su índice"].sum()),
                                       int(tab["Elegible"].sum()), int(tab["Candidato"].sum()), len(sug["pesos"])]})
    ch = alt.Chart(pasos).mark_bar(color=AZUL).encode(x=alt.X("Empresas:Q"), y=alt.Y("Etapa:N", sort=None, title=None),
                                                      tooltip=["Etapa", "Empresas"]).properties(height=260)
    st.altair_chart(ch + ch.mark_text(align="left", dx=4).encode(text="Empresas:Q"), width="stretch")

    st.subheader("Diagnóstico por sector")
    st.markdown("Cuántas empresas de cada sector pasan cada filtro (acumulado) con los precios de hoy, y cuántas quedan en la "
                "selección sugerida. Cada sector elegido pesa 19 %; si solo una empresa cumple todo, lleva el peso completo.")
    st.dataframe(M.diagnostico_sectores(pre, tab, sug["sectores"]), width="stretch")

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
    st.markdown(f"Las empresas de EE. UU. se comparan con el **S&P 500**, las de Taiwán con el **TAIEX** y las de Corea con el "
                "**KOSPI**, en moneda local y con la tasa libre de riesgo de cada país (últimos {M.VENTANA_ANIOS} años).")
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
                  f"({num(r['PER relativo al sector'])} veces la mediana de su sector); Q de Tobin {num(r.get('Q de Tobin (P/VL)'), 1)} "
                  f"({num(r.get('Q de Tobin relativa al sector'))} veces su sector); dividend yield {pct(r.get('Dividend yield'))}.\n"
                f"- **Bursatilidad:** Sharpe {num(r['Sharpe'])} frente a {num(r['Sharpe del índice'])} del "
                f"{M.NOMBRE_INDICE.get(r['Índice local'], r['Índice local'])}; alfa de Jensen {pct(r['Alfa de Jensen'])} anual; "
                f"beta {num(r['Beta local'])} ({'alto riesgo' if r['Alto riesgo'] else 'riesgo moderado'}).\n"
                f"- **Técnico:** al seleccionar ({ficha_pdf.fecha_larga(of['fin'])}) {r['Lectura técnica'].lower()}; "
                f"hoy {tk.get('Lectura técnica', 'Sin datos').lower()}"
                + (f" · RSI {num(tk.get('RSI 14'), 0)} · {pct(tk.get('Distancia al máximo 52 semanas'))} frente al máximo de 52 semanas"
                   if 'RSI 14' in tk and pd.notna(tk.get('RSI 14')) else "") + ".\n"
                f"- **En el portafolio:** aporta {pct(r['Contribución al riesgo'])} del riesgo; robustez {pct(r['Robustez'], 0)}.\n"
                f"- **ASG:** {r['Criterio ASG']}. {r['Nota ASG']}")

# ------------------------------------------------------------------ 4. frontera eficiente
with tabs[3]:
    fr = of["frontera"]
    st.subheader("Frontera eficiente de Markowitz")
    st.markdown("Siguiendo el proceso de *asset allocation* del curso: (1) escogencia de activos, (2) proyección del retorno "
                "esperado, (3) **frontera eficiente** y (4) selección del portafolio según las restricciones de la política. "
                "Las fronteras se calculan sin ventas en corto, con rendimientos mensuales en USD de los últimos "
                f"{M.VENTANA_ANIOS} años y la rentabilidad esperada del modelo (½ histórica + ½ CAPM).")
    pc, pf = fr["candidatas"]["puntos"], fr["fondo"]["puntos"]
    capas = []
    lin = []
    if len(pc):
        lin.append(pc[["Volatilidad", "Rentabilidad"]].assign(Serie="Frontera con todas las candidatas"))
    if len(pf):
        lin.append(pf[["Volatilidad", "Rentabilidad"]].assign(Serie="Frontera con los 10 activos del fondo"))
    msc = fr["candidatas"]["max_sharpe"]
    ymax = max(float(pc["Rentabilidad"].max()) if len(pc) else 0.3, float(f["E(R) anual USD"].max())) * 1.1
    xcml = min((ymax - of["rf"]) / msc["Sharpe"], msc["Volatilidad"] * 1.8) if msc["Sharpe"] > 0 else msc["Volatilidad"]
    lin.append(pd.DataFrame({"Volatilidad": [0, xcml], "Rentabilidad": [of["rf"], of["rf"] + msc["Sharpe"] * xcml],
                             "Serie": "Línea del mercado de capitales"}))
    lin = pd.concat(lin)
    escala = alt.Scale(domain=["Frontera con todas las candidatas", "Frontera con los 10 activos del fondo",
                               "Línea del mercado de capitales"], range=["#9aa9b1", AZUL, "#9aa9b1"])
    capas.append(alt.Chart(lin).mark_line().encode(
        x=alt.X("Volatilidad:Q", axis=alt.Axis(format="%"), title="Volatilidad anual (USD)"),
        y=alt.Y("Rentabilidad:Q", axis=alt.Axis(format="%"), title="Rentabilidad esperada anual"),
        color=alt.Color("Serie:N", scale=escala, legend=alt.Legend(orient="bottom", title=None, labelLimit=320)),
        strokeDash=alt.condition(alt.datum.Serie == "Línea del mercado de capitales", alt.value([5, 4]), alt.value([1, 0]))))
    act = pd.DataFrame({"Activo": f.index, "Empresa": f["Empresa"], "Sector": f["Sector"],
                        "Volatilidad": f["Volatilidad anual USD"], "Rentabilidad": f["E(R) anual USD"]})
    capas.append(alt.Chart(act).mark_circle(size=60, color="#5a6f7a").encode(
        x="Volatilidad:Q", y="Rentabilidad:Q", tooltip=["Activo", "Empresa", "Sector", alt.Tooltip("Volatilidad:Q", format=".1%"),
                                                         alt.Tooltip("Rentabilidad:Q", format=".1%")]))
    capas.append(alt.Chart(act).mark_text(align="left", dx=6, fontSize=10, color="#5a6f7a").encode(
        x="Volatilidad:Q", y="Rentabilidad:Q", text="Activo:N"))
    w_acc = of["pesos"] / of["pesos"].sum()
    s_acc = float(np.sqrt(w_acc @ of["S"].loc[w_acc.index, w_acc.index].values @ w_acc))
    e_acc = float(w_acc @ of["mu"][w_acc.index])
    pts = pd.DataFrame([
        {"Portafolio": "Fondo (parte en acciones)", "Volatilidad": s_acc, "Rentabilidad": e_acc, "Sharpe": (e_acc - of["rf"]) / s_acc},
        {"Portafolio": "Mínima varianza", **{k: fr["fondo"]["min_varianza"][k] for k in ("Volatilidad", "Rentabilidad")},
         "Sharpe": (fr["fondo"]["min_varianza"]["Rentabilidad"] - of["rf"]) / fr["fondo"]["min_varianza"]["Volatilidad"]},
        {"Portafolio": "Máximo Sharpe (10 activos)", **{k: fr["fondo"]["max_sharpe"][k] for k in ("Volatilidad", "Rentabilidad", "Sharpe")}},
        {"Portafolio": "Máximo Sharpe (todas las candidatas)", **{k: msc[k] for k in ("Volatilidad", "Rentabilidad", "Sharpe")}}])
    forma = alt.Scale(domain=list(pts["Portafolio"]), range=["diamond", "square", "triangle-up", "triangle-up"])
    colp = alt.Scale(domain=list(pts["Portafolio"]), range=[ARENA, AZUL, AZUL, "#9aa9b1"])
    capas.append(alt.Chart(pts).mark_point(size=170, filled=True).encode(
        x="Volatilidad:Q", y="Rentabilidad:Q", shape=alt.Shape("Portafolio:N", scale=forma, legend=alt.Legend(orient="bottom", title=None, labelLimit=320)),
        color=alt.Color("Portafolio:N", scale=colp, legend=None),
        tooltip=["Portafolio", alt.Tooltip("Volatilidad:Q", format=".1%"), alt.Tooltip("Rentabilidad:Q", format=".1%"),
                 alt.Tooltip("Sharpe:Q", format=".2f")]))
    st.altair_chart(alt.layer(*capas).resolve_scale(color="independent", shape="independent").properties(height=430),
                    width="stretch")
    t = pts.copy()
    t["Volatilidad"], t["Rentabilidad"], t["Sharpe"] = t["Volatilidad"].map(pct), t["Rentabilidad"].map(pct), t["Sharpe"].map(num)
    st.dataframe(t.set_index("Portafolio"), width="stretch")
    st.caption("El fondo queda por debajo de la frontera porque la política exige 5 sectores con igual peso, mínimo 5 % por activo, "
               "≥ 50 % en alto riesgo, Asia ≤ 35 % y VaR ≤ 8 %. Esa distancia es el costo, en Sharpe, de diversificar.")
    st.download_button("Descargar el Excel con los cálculos de la frontera", R["excel"],
                       file_name="Frontera_eficiente_Solidez_Sostenible.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    if R.get("antes_despues") is not None:
        st.subheader("Antes y después de diversificar por sectores")
        st.markdown("Mismo universo, mismos filtros y mismos datos. **Antes:** máximo Sharpe con las 5 mejores empresas de cada "
                    "mercado y pesos de 10 % a 20 % (método anterior). **Ahora:** 5 sectores con igual peso, hasta 2 empresas por sector "
                    "y VaR ≤ 8 %.")
        st.dataframe(R["antes_despues"], width="stretch", height=36 * (len(R["antes_despues"]) + 1) + 4)

    st.subheader("Correlaciones en los meses de caída del mercado")
    cc = of["correlacion_caidas"]
    st.markdown(f"Correlación de los rendimientos mensuales en USD en los **{of['meses_caida']} meses** en que cayó el índice "
                f"compuesto. Meta de la política: ≤ {num(M.POLITICA['max_correlacion_caidas'], 1)} entre cada par. "
                f"Máxima observada: **{num(of['max_correlacion_caidas'])}**"
                + (f" ({of['par_max_correlacion'][0]} y {of['par_max_correlacion'][1]})." if of["par_max_correlacion"][0] else "."))
    hm = cc.reset_index(names="A").melt("A", var_name="B", value_name="Correlación")
    base = alt.Chart(hm).encode(x=alt.X("B:N", sort=list(cc.columns), title=None), y=alt.Y("A:N", sort=list(cc.columns), title=None))
    st.altair_chart((base.mark_rect().encode(color=alt.Color("Correlación:Q", scale=alt.Scale(domain=[-1, 1], scheme="blueorange"),
                                                                    legend=alt.Legend(title="ρ")),
                                             tooltip=["A", "B", alt.Tooltip("Correlación:Q", format=".2f")])
                     + base.mark_text(fontSize=10).encode(text=alt.Text("Correlación:Q", format=".2f"))).properties(height=380),
                    width="stretch")

# ------------------------------------------------------------------ 5. metodología
with tabs[4]:
    st.subheader("Cómo se eligen los activos")
    st.markdown("""
0. **Universo.** Todas las empresas del S&P 500 y las mayores de las bolsas de Taiwán y Corea del Sur (cerca de 600). Sus
   fundamentales se descargan de Yahoo Finance cada noche, de modo que cualquier empresa nueva que cumpla los criterios puede entrar.
1. **Criterios ASG.** Se excluyen armas controvertidas, tabaco y carbón térmico (por nombre, sector e industria). Es una
   restricción de «circunstancias únicas» de la política de inversión (guía AMV).
2. **Filtro 1 · salud financiera (fundamentales).** Semáforo de ROA (> 6 %), ROE (> 12 %), liquidez corriente (> 1,5x) y
   endeudamiento (< 50 %). Cada indicador vale 2, 1 o 0 puntos; solo pasan las empresas con promedio ≥ 1,5 (nivel Bueno).
   En bancos y aseguradoras solo cuentan ROA y ROE. También se excluyen PER ≤ 0, patrimonio negativo y empresas con una
   Q de Tobin (precio / valor en libros) mayor a 3 veces la mediana de su sector.
3. **Filtro 2 · bursatilidad frente al índice local.** Con 3 años de precios mensuales en moneda local, cada empresa debe tener
   un Sharpe mayor que el de su índice (S&P 500, TAIEX o KOSPI) y alfa de Jensen positivo. Se ordenan, con igual peso, por
   Sharpe y rentabilidad frente al índice y por PER y Q de Tobin frente a su sector. Alto riesgo: β local > 1.
4. **Filtro 3 · criterio técnico de compra: retroceso dentro de una tendencia alcista.** Condición obligatoria: el precio debe
   estar sobre su media móvil de 200 días (tendencia de largo plazo alcista). Además se revisan tres señales: media de 50 días
   sobre la de 200, MACD sobre su señal y RSI (14) entre 30 y 50 (la acción tuvo un retroceso, sin llegar a sobreventa, y se
   compra a mejor precio). Con 2 o 3 señales la lectura es Favorable, con 1 Neutral y con 0, o con el precio bajo la media de
   200 días, Desfavorable. No se compran acciones con lectura Desfavorable. El RSI mide impulso, no valoración: si una acción
   está cara o barata lo indican el PER y la Q de Tobin frente a su sector.
5. **Asignación por sectores.** En cada sector se toman sus 2 mejores empresas; si solo una cumple todos los criterios,
   esa empresa lleva el peso completo del sector (ningún filtro se relaja). Se prueban **todas las combinaciones de 5
   sectores**; cada sector recibe el mismo peso (19 % del fondo) y, dentro del sector, los pesos se fijan con Markowitz (máximo
   Sharpe, mínimo 5 % por activo). Entre las combinaciones que cumplen la política (≥ 50 % en alto riesgo, Taiwán + Corea ≤ 35 %,
   VaR 95 % a 1 mes ≤ 8 %) se elige la de **mayor Sharpe**.
6. **Riesgo.** VaR = N · σ · Z · √t con Z al 95 % y t = 1 mes. La rentabilidad esperada es ½ histórica en USD + ½ CAPM local
   llevado a USD por paridad de tasas; la matriz de covarianzas usa rendimientos mensuales en USD.
7. **Robustez.** El proceso se repite en 54 escenarios (ventanas de 5, 3 y 2 años × 2 métodos de rentabilidad × 3 pisos por
   activo × 3 tasas libres de riesgo) y se informa en cuántos aparece cada activo.
8. **Rebalanceo.** La selección oficial se renueva cada mes con los datos al cierre del mes anterior; entre revisiones, un peso
   se ajusta si se desvía más de 3 puntos o si el activo deja de cumplir un filtro.
""")
    st.markdown(f"En la selección oficial se evaluaron **{of['combinaciones_evaluadas']} combinaciones** de 5 sectores entre "
                f"{len(of['sectores_disponibles'])} sectores con candidatas; **{of['combinaciones_factibles']}** cumplieron la "
                f"política. Sectores elegidos: **{', '.join(of['sectores'])}**. La misma combinación ganó en "
                f"{pct(of['robustez_combinacion'], 0)} de los escenarios de robustez.")
    if not of["var_cumple"]:
        st.warning("Ninguna combinación cumplió el VaR de 8 % junto con las demás reglas; se eligió la combinación de menor riesgo.")
    st.subheader("Verificación del portafolio oficial")
    st.dataframe(R["verif"], width="stretch", hide_index=True)

# ------------------------------------------------------------------ 6. ASG
with tabs[5]:
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
