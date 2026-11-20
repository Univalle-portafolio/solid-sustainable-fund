"""
Solidez Sostenible Renta Variable — aplicación web.

  · Portafolio oficial: congelado en data/portafolio_oficial.csv (fecha de selección y pesos). La página no lo recalcula
    al entrar: con los datos de esa fecha calcula sus indicadores, la frontera, la robustez y la verificación.
  · Seguimiento: con los precios del día muestra cómo se movieron los pesos y si cada activo sigue cumpliendo los criterios
    fundamentales. La composición se revisa cada trimestre.
  · Prueba fuera de muestra: la misma metodología con datos hasta octubre de 2023, simulada hasta hoy.
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


def plural(n, singular, plural_):
    return f"{n} {singular if n == 1 else plural_}"


def m_pct(x):
    return "—" if pd.isna(x) else f"{x * 100:,.1f} %".replace(".", ",")


def m_num(x):
    return "—" if pd.isna(x) else f"{x:,.2f}".replace(".", ",")


def tabla_metricas(cm):
    out = pd.DataFrame(index=cm.index, columns=cm.columns, dtype=object)
    for k in cm.index:
        out.loc[k] = [usd(x) if "USD" in k else (num(x) if k.startswith(("Sharpe", "Beta", "Treynor", "Information")) else pct(x))
                      for x in cm.loc[k]]
    return out


def grafico_evolucion(serie, alto=330):
    v = (1 + serie.fillna(0)).cumprod() * 100_000
    v = v.reset_index(names="Fecha").melt("Fecha", var_name="Serie", value_name="Valor (USD)")
    return alt.Chart(v).mark_line().encode(
        x=alt.X("Fecha:T", title=None), y=alt.Y("Valor (USD):Q", title="USD", axis=alt.Axis(format=",.0f")),
        color=alt.Color("Serie:N", legend=alt.Legend(orient="top", title=None)),
        strokeWidth=alt.condition(alt.datum.Serie == "Fondo", alt.value(2.6), alt.value(1.2)),
        tooltip=["Serie", alt.Tooltip("Fecha:T"), alt.Tooltip("Valor (USD):Q", format=",.0f")]).properties(height=alto)


# ------------------------------------------------------------------ datos
def ruta_ranking():
    c = sorted(glob.glob(os.path.join(AQUI, "data", "ranking*.xlsx")) + glob.glob(os.path.join(AQUI, "ranking*.xlsx")))
    return c[0] if c else None


def ruta_datos(nombre):
    for r in (os.path.join(AQUI, "data", nombre), os.path.join(AQUI, nombre)):
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
                         "Rentabilidad esperada (bruta)": m_pct(e), "Volatilidad esperada": m_pct(s), "Sharpe esperado": m_num((e - rf) / s),
                         "VaR esperado 95 % a 1 mes": m_pct(M.var_mensual(s)),
                         f"Rentabilidad anual simulada ({M.VENTANA_ANIOS} años)": m_pct(m["Rentabilidad anual"]),
                         "Volatilidad histórica": m_pct(m["Volatilidad anual"]), "Máxima caída histórica": m_pct(m["Máxima caída"]),
                         "Rentabilidad del último mes": m_pct(per.loc["Rentabilidad del periodo", "Último mes"])}
    return pd.DataFrame(filas)


@st.cache_data(ttl=3600, show_spinner="Calculando el portafolio oficial, la robustez (54 escenarios) y la prueba fuera de muestra…")
def ejecutar(clave: str, consol: pd.DataFrame, indices: pd.DataFrame, px: pd.DataFrame, pesos_of, fecha_of):
    hoy = px.index.max()
    d_hoy = M.preparar(consol, indices, px)
    if pesos_of is not None:
        d_of = M.preparar(consol, indices, px, fecha_of)
        oficial = M.seleccionar(consol, indices, d_of, pesos_fijos=pesos_of)
    else:     # respaldo: sin archivo del portafolio oficial se selecciona con el último cierre de mes
        d_of = M.preparar(consol, indices, px, M.fecha_rebalanceo(hoy, px.index))
        oficial = M.seleccionar(consol, indices, d_of)
    tabla_hoy, _ = M.evaluar_universo(consol, indices, d_hoy)
    seg, seg_res = M.seguimiento(oficial, d_hoy, tabla_hoy)
    serie = M.serie_fondo_diaria(oficial, d_hoy)
    comp = pd.DataFrame({c: M.metricas(serie[c], oficial["resumen"]["Rf"], serie["Índice compuesto"]) for c in serie.columns})
    comp = comp[["Fondo", "Índice compuesto"] + [c for c in comp.columns if c not in ("Fondo", "Índice compuesto")]]
    periodos = M.rentabilidad_por_periodos(serie["Fondo"])
    periodos_ix = M.rentabilidad_por_periodos(serie["Índice compuesto"])
    tec = pd.DataFrame({a: M.tecnico(d_hoy["diario_loc"][a]) if a in d_hoy["diario_loc"] else {"Lectura técnica": "Sin datos"}
                        for a in oficial["fondo"].index}).T
    oos = M.prueba_fuera_de_muestra(consol, indices, px)
    try:
        antes = _antes_despues(oficial, d_of, d_hoy, serie)
    except Exception:
        antes = None
    return {"oficial": oficial, "serie": serie, "comp": comp, "periodos": periodos, "periodos_ix": periodos_ix, "tec": tec,
            "tabla_hoy": tabla_hoy, "seguimiento": seg, "seg_res": seg_res, "oos": oos,
            "verif": M.verificar(oficial, comp, oos), "hoy": hoy, "antes_despues": antes,
            "excel": frontera_excel.generar(oficial, d_of)}


# ------------------------------------------------------------------ barra lateral y carga de datos
st.sidebar.title("Solidez Sostenible")
st.sidebar.markdown(f"*{M.ESLOGAN}*")
dia = pd.Timestamp.today().strftime("%Y-%m-%d")
r_uni, r_rank, r_of = ruta_datos("universo.csv"), ruta_ranking(), ruta_datos("portafolio_oficial.csv")
pesos_of, fecha_of = None, None
if r_of:
    try:
        pesos_of, fecha_of = M.cargar_oficial(r_of)
    except Exception as e:
        st.sidebar.error(f"No se pudo leer data/portafolio_oficial.csv ({e}). Se usa la selección del último cierre de mes.")
usar_fund, fecha_uni = False, None
if r_uni:
    universo, indices, fecha_uni = M.cargar_universo(r_uni)
    fuente_txt = f"Universo analizado: {len(universo)} empresas (S&P 500 + Taiwán + Corea del Sur)"
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

# Filtros sin precios (ASG, salud financiera, PER) sobre todo el universo; solo las que pasan van a bursatilidad.
# Los activos del portafolio oficial siempre siguen, para hacerles seguimiento.
oficiales = tuple(pesos_of.index) if pesos_of is not None else ()
faltan = [a for a in oficiales if a not in universo.index]
if faltan:
    st.error(f"Los activos {', '.join(faltan)} del portafolio oficial no están en el universo. Revise data/portafolio_oficial.csv.")
    st.stop()
consol, pre = M.prefiltro(universo, incluir=oficiales)
if consol.empty:
    st.error("Ninguna empresa del universo pasó los criterios ASG y de salud financiera.")
    st.stop()
tickers = tuple(list(consol.index) + list(indices["Índice"]) + list(M.FX_YF.values()) + ["^IRX"])
try:
    px = precios(tickers, dia)
except Exception as e:
    st.error(f"No fue posible descargar precios de Yahoo Finance ({type(e).__name__}). Intente de nuevo en unos minutos.")
    st.stop()

clave = hashlib.md5((str(px.index.max()) + str(px.shape) + str(usar_fund) + str(consol.values.tobytes()[:2000])
                     + str(pesos_of) + str(fecha_of)).encode()).hexdigest()
try:
    R = ejecutar(clave, consol, indices, px, pesos_of, fecha_of)
except ValueError as e:
    st.error(f"El motor no pudo calcular el portafolio: {e}")
    if isinstance(e, M.SectoresInsuficientes):
        st.subheader("Diagnóstico por sector")
        st.dataframe(M.diagnostico_sectores(pre, e.tabla), width="stretch")
    st.stop()

of = R["oficial"]
f = of["fondo"]
rs = of["resumen"]
mercados_fondo = list(f.groupby("Mercado")["Peso"].sum().sort_values(ascending=False).index)
txt_mercados = M.mercados_texto(mercados_fondo)
txt_indices = M.indices_texto(mercados_fondo)
sin_inversion = [MERCADO_ES[m] for m in ("EEUU", "Taiwan", "Corea") if m in set(universo["Mercado"]) and m not in mercados_fondo]
fecha_sel = ficha_pdf.fecha_larga(of["fin"])

st.sidebar.caption(f"Renta variable · invierte en {txt_mercados} · perfil arriesgado")
st.sidebar.markdown(f"**Portafolio oficial:** seleccionado con datos al {fecha_sel} · revisión {M.REVISION}  \n"
                    f"**Seguimiento con precios al:** {ficha_pdf.fecha_larga(R['hoy'])}")
st.sidebar.caption(fuente_txt + (f" · fundamentales al {ficha_pdf.fecha_larga(pd.Timestamp(fecha_uni))}" if fecha_uni else ""))
pdf_bytes = ficha_pdf.generar(of, R["serie"], R["periodos"], R["comp"], R["verif"], oos=R["oos"], fecha_datos=R["hoy"],
                              universo_mercados=sorted(set(universo["Mercado"])))
st.sidebar.download_button("Descargar ficha técnica (PDF)", pdf_bytes, file_name="Ficha_tecnica_Solidez_Sostenible_Renta_Variable.pdf",
                           mime="application/pdf", width="stretch", type="primary")
st.sidebar.download_button("Descargar frontera eficiente (Excel)", R["excel"], file_name="Frontera_eficiente_Solidez_Sostenible.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
st.sidebar.caption("Ejercicio académico · Gestión de Portafolios · Universidad del Valle")

# ------------------------------------------------------------------ encabezado
st.title(M.NOMBRE_FONDO)
st.markdown(f"#### *{M.ESLOGAN}*")
st.markdown(f"Invertimos en empresas líderes de **{txt_mercados}** que cumplen criterios ASG, tienen **buena salud "
            "financiera**, superan a **su propio índice** y están en **tendencia alcista de largo plazo** (compramos en los "
            "retrocesos). El fondo se reparte en **5 sectores con igual peso**; dentro de cada sector los pesos se definen con "
            "Markowitz y el riesgo se limita a un **VaR mensual de 8 %**. "
            + (f"El universo analizado incluye también {' y '.join(sin_inversion)}, pero ninguna de sus empresas quedó en el "
               "portafolio. " if sin_inversion else ""))
c = st.columns(6)
c[0].metric("Rentabilidad esperada (bruta)", pct(rs["E(R) anual"]), help="Antes de la comisión de administración de 2,5 % E.A.")
c[1].metric("Neta de comisión", pct(rs["E(R) neta de comisión"]), help="(1 + bruta) / (1 + 2,5 %) − 1")
c[2].metric("Volatilidad esperada", pct(rs["Volatilidad anual"]))
c[3].metric("Sharpe esperado", num(rs["Sharpe"]))
c[4].metric(f"VaR esperado 95 % · 1 mes", pct(rs["VaR 95 % 1 mes (%)"]), help=f"{usd(rs['VaR 95 % 1 mes (USD)'])} con la volatilidad esperada")
c[5].metric("Alto riesgo", pct(rs["Alto riesgo por clase de activo"], 0), help="Renta variable, clase de activo de alto riesgo")
st.caption(f"{plural(len(f), 'activo', 'activos')} en {plural(f['Sector'].nunique(), 'sector', 'sectores')} · "
           f"{pct(rs['Alto riesgo por clase de activo'], 0)} en renta variable (alto riesgo por clase de activo) y "
           f"{pct(rs['Alto riesgo β > 1'])} en acciones con β > 1 · portafolio oficial seleccionado con datos al {fecha_sel}, "
           f"con revisión {M.REVISION} · seguimiento con precios al {ficha_pdf.fecha_larga(R['hoy'])}.")

tabs = st.tabs(["Ficha del fondo", "Seguimiento", "Activos frente a su índice", "Frontera eficiente", "Metodología",
                "Sostenibilidad (ASG)"])

# ------------------------------------------------------------------ 1. ficha
with tabs[0]:
    a, b = st.columns([1.1, 1])
    with a:
        st.subheader("Características")
        st.markdown(f"""
| | |
|---|---|
| **Tipo** | Fondo de inversión colectiva abierto, sin pacto de permanencia |
| **Objetivo** | Crecimiento del capital a largo plazo (más de 5 años) |
| **Perfil de riesgo** | Arriesgado: {pct(rs['Alto riesgo por clase de activo'], 0)} en renta variable, clase de activo de alto riesgo; además, {pct(rs['Alto riesgo β > 1'], 0)} en acciones con β > 1 · VaR 95 % mensual ≤ 8 % |
| **Asignación** | 5 sectores con igual peso (19 % cada uno), hasta 2 empresas por sector |
| **Mercados** | {txt_mercados}{f" (el universo analizado incluye {' y '.join(sin_inversion)})" if sin_inversion else ""} |
| **Índice de referencia** | {txt_indices} en USD, ponderados por el peso del fondo en cada país |
| **Revisión** | Composición {M.REVISION}: un activo sale si deja de cumplir los criterios fundamentales |
| **Inversión mínima** | USD 100 · saldo mínimo USD 50 · preaviso de 3 días hábiles |
| **Comisiones** | Administración 2,50 % E.A. · sin comisión de éxito, entrada ni salida |
| **Liquidez** | 5 % · sin derivados ni apalancamiento |
| **Riesgo cambiario** | Las acciones de Taiwán cotizan en dólares taiwaneses: su valor en USD cambia con la tasa de cambio |
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
    rango = f.apply(lambda r: "—" if pd.isna(r["Peso mínimo (escenarios)"]) else
                    f"{pct(r['Peso mínimo (escenarios)'], 0)} – {pct(r['Peso máximo (escenarios)'], 0)}", axis=1)
    t = pd.DataFrame({
        "Empresa": f["Empresa"].map(M.nombre_corto), "Mercado": f["Mercado"].map(MERCADO_ES), "Sector": f["Sector"],
        "Peso": f["Peso"].map(pct), "Monto": f["Monto (USD)"].map(usd), "E(R) anual": f["E(R) anual USD"].map(pct),
        "Volatilidad": f["Volatilidad anual USD"].map(pct), "Beta local (3 años)": f["Beta local"].map(num),
        "Beta local (5 años)": f["Beta local 5 años"].map(num),
        "β > 1": f["Alto riesgo"].astype(bool).map({True: "Sí", False: "No"}),
        "Contribución al riesgo": f["Contribución al riesgo"].map(pct), "Peso en los escenarios": rango,
        "Técnico al seleccionar": f["Lectura técnica"], "Técnico hoy": R["tec"]["Lectura técnica"].reindex(f.index)})
    st.dataframe(t, width="stretch")
    st.caption(f"Liquidez: {pct(M.PESO_LIQUIDEZ)}. Pesos sobre el valor total del fondo. Toda la renta variable es de alto "
               f"riesgo por clase de activo (monetario: bajo; renta fija: medio; renta variable: alto). Dentro de las acciones, "
               f"las de β > 1 suman {pct(rs['Alto riesgo β > 1'])}. «Peso en los escenarios»: rango del peso óptimo en las "
               "pruebas de robustez.")

    st.subheader(f"Evolución de USD 100.000 invertidos hace {M.VENTANA_ANIOS} años (simulación)")
    st.altair_chart(grafico_evolucion(R["serie"]), width="stretch")
    st.warning("**Simulación ilustrativa, dentro de muestra.** Las empresas se seleccionaron porque les fue mejor que a su "
               "índice en estos mismos años, así que el resultado sobrestima la rentabilidad que se habría obtenido en la "
               "realidad (sesgo de mirar hacia adelante). La prueba fuera de muestra, más abajo, corrige ese sesgo.")

    a, b = st.columns(2)
    with a:
        st.subheader("Rentabilidad y volatilidad por periodo")
        p = R["periodos"].apply(lambda col: col.map(pct))
        p.index = ["Fondo (E.A.)", "Fondo (del periodo)", "Fondo (volatilidad)"]
        pix = R["periodos_ix"].loc[["Rentabilidad E.A.", "Rentabilidad del periodo"]].apply(lambda col: col.map(pct))
        pix.index = ["Índice compuesto (E.A.)", "Índice compuesto (del periodo)"]
        st.dataframe(pd.concat([p, pix]), width="stretch")
        st.caption("Los plazos menores a un año se anualizan (E.A.), como exige el formato de ficha técnica: una variación de "
                   "un mes se amplifica al anualizarse. Las filas «del periodo» muestran la variación efectiva sin anualizar.")
    with b:
        st.subheader("El fondo frente a los índices")
        st.dataframe(tabla_metricas(R["comp"]), width="stretch")
    st.caption(f"Índice compuesto: {txt_indices} en dólares, ponderados por el peso del fondo en cada país. Rentabilidades "
               "en tasa compuesta anual con precios diarios en USD. El VaR histórico usa la volatilidad observada en estos "
               f"{M.VENTANA_ANIOS} años; el VaR del encabezado (esperado) usa la volatilidad esperada del modelo.")

    oos = R["oos"]
    st.subheader(f"Prueba fuera de muestra: selección con datos hasta {ficha_pdf.fecha_larga(oos['fecha'])}")
    if oos["error"]:
        st.info(f"No fue posible armar el portafolio con los datos de esa fecha: {oos['error']}")
    else:
        r0 = oos["res"]
        st.markdown(f"Se aplicó la misma metodología usando solo los precios disponibles hasta el "
                    f"**{ficha_pdf.fecha_larga(oos['fecha'])}** y se simuló ese portafolio desde entonces hasta hoy. Así se "
                    "evalúa el método con datos que no se usaron para escoger las empresas.")
        st.altair_chart(grafico_evolucion(oos["serie"], 300), width="stretch")
        a, b = st.columns([1.3, 1])
        with a:
            st.dataframe(tabla_metricas(oos["comp"]), width="stretch")
        with b:
            st.dataframe(pd.DataFrame({"Empresa": r0["fondo"]["Empresa"].map(M.nombre_corto), "Sector": r0["fondo"]["Sector"],
                                       "Peso": r0["fondo"]["Peso"].map(pct)}), width="stretch")
        st.caption("Limitaciones: los fundamentales (salud financiera, PER, Q de Tobin) y la lista de empresas del S&P 500 son "
                   "los de hoy, porque Yahoo Finance no publica su historia; por eso la prueba conserva algo de sesgo.")

# ------------------------------------------------------------------ 2. seguimiento
with tabs[1]:
    sr = R["seg_res"]
    st.subheader("Seguimiento del portafolio oficial")
    st.markdown(f"El portafolio oficial se seleccionó con datos al **{fecha_sel}** y **no se recalcula al entrar**. Aquí se "
                f"ve cómo se movieron los pesos con los precios al **{ficha_pdf.fecha_larga(R['hoy'])}** y si cada activo sigue "
                f"cumpliendo los criterios fundamentales. **Política de revisión ({M.REVISION}):** un activo sale si deja de "
                "cumplir los criterios fundamentales (ASG, salud financiera o bursatilidad frente a su índice); los pesos "
                f"vuelven a su objetivo si se desvían más de {pct(M.POLITICA['rebalanceo_puntos'], 0)}. El análisis técnico "
                "solo se usa para decidir cuándo comprar.")
    c = st.columns(3)
    c[0].metric("Renta variable hoy (alto riesgo)", pct(sr["renta_variable_hoy"]))
    c[1].metric("Acciones con β > 1 hoy", pct(sr["alto_riesgo_hoy"]), delta=f"{(sr['alto_riesgo_hoy'] - rs['Alto riesgo β > 1']) * 100:+.1f} pts".replace(".", ","))
    c[2].metric("Activos para revisar en el comité", str(int(R["seguimiento"]["Acción"].str.startswith("Revisar").sum())))
    st.caption("El peso de un activo cambia con su precio aunque no se venda nada. Al volver los pesos a su objetivo en la "
               f"revisión, las acciones con β > 1 regresan a {pct(rs['Alto riesgo β > 1'])}.")
    sg = R["seguimiento"].copy()
    for col in ["Peso objetivo", "Peso actual (por precios)", "Desviación", "Variación del precio (USD)"]:
        sg[col] = sg[col].map(pct)
    st.dataframe(sg, width="stretch")

    tab = R["tabla_hoy"]
    st.subheader("Embudo de selección con los precios de hoy")
    st.markdown("Referencia para la próxima revisión: cuántas empresas del universo pasan cada filtro hoy.")
    pasos = pd.DataFrame({"Etapa": ["Universo", "Cumplen ASG", "Salud financiera Buena", "Superan a su índice (Sharpe y alfa)",
                                    "Técnico y Q de Tobin (pasan todos los filtros)", "Candidatas (hasta 2 por sector)"],
                          "Empresas": [len(pre), int((pre["Criterio ASG"] == "Cumple").sum()),
                                       int(pre["Pasa a bursatilidad"].sum()),
                                       int(tab["Supera a su índice"].reindex(pre.index[pre["Pasa a bursatilidad"]]).fillna(False).sum()),
                                       int(tab["Elegible"].reindex(pre.index[pre["Pasa a bursatilidad"]]).fillna(False).sum()),
                                       int(tab["Candidato"].reindex(pre.index[pre["Pasa a bursatilidad"]]).fillna(False).sum())]})
    ch = alt.Chart(pasos).mark_bar(color=AZUL).encode(x=alt.X("Empresas:Q"), y=alt.Y("Etapa:N", sort=None, title=None),
                                                      tooltip=["Etapa", "Empresas"]).properties(height=230)
    st.altair_chart(ch + ch.mark_text(align="left", dx=4).encode(text="Empresas:Q"), width="stretch")

    st.subheader("Diagnóstico por sector (precios de hoy)")
    st.dataframe(M.diagnostico_sectores(pre, tab.reindex(pre.index[pre["Pasa a bursatilidad"]]).dropna(how="all"), of["sectores"]),
                 width="stretch")

    st.subheader("Universo completo y motivo de exclusión (hoy)")
    cols_pre = ["Empresa", "Mercado", "Sector", "Criterio ASG"] + ([M.COL_RIESGO_ASG] if M.COL_RIESGO_ASG in pre else []) + \
               ["Nivel de salud", "Puntaje de salud"]
    u = pre[cols_pre].join(tab[["Sharpe", "Sharpe del índice", "Alfa de Jensen", "Puntaje de bursatilidad", "Candidato",
                                "Motivo de exclusión"]], how="left")
    u["Motivo de exclusión"] = u["Motivo de exclusión"].where(pre["Pasa a bursatilidad"]).fillna(pre["Motivo de exclusión"])
    u["Candidato"] = (u["Candidato"].fillna(False).astype(bool) & pre["Pasa a bursatilidad"])
    u = u.sort_values(["Candidato", "Puntaje de bursatilidad"], ascending=False)
    u["Mercado"] = u["Mercado"].map(MERCADO_ES)
    u["Alfa de Jensen"] = u["Alfa de Jensen"].map(pct)
    for col in ["Puntaje de salud", "Sharpe", "Sharpe del índice", "Puntaje de bursatilidad"] + \
               ([M.COL_RIESGO_ASG] if M.COL_RIESGO_ASG in u else []):
        u[col] = u[col].map(num)
    filtro = st.multiselect("Mercado", list(MERCADO_ES.values()), default=list(MERCADO_ES.values()))
    st.dataframe(u[u["Mercado"].isin(filtro)], width="stretch", height=420)

# ------------------------------------------------------------------ 3. activos frente a su índice
with tabs[2]:
    st.subheader("Cada activo frente al índice de su propio mercado")
    st.markdown(f"Cada empresa se compara con el índice de su mercado (S&P 500 para EE. UU., TAIEX para Taiwán y KOSPI para "
                f"Corea del Sur), en moneda local y con la tasa libre de riesgo de cada país (últimos {M.VENTANA_ANIOS} años, "
                f"datos al {fecha_sel}).")
    ci = pd.DataFrame({
        "Índice": f["Índice local"].map(M.NOMBRE_INDICE), "Rentabilidad del activo": f["Rentabilidad anual"].map(pct),
        "Rentabilidad del índice": f["Rentabilidad del índice"].map(pct), "Sharpe del activo": f["Sharpe"].map(num),
        "Sharpe del índice": f["Sharpe del índice"].map(num), "Beta (3 años)": f["Beta local"].map(num),
        "Beta (5 años)": f["Beta local 5 años"].map(num),
        "Alfa de Jensen": f["Alfa de Jensen"].map(pct), "t del alfa": f["t del alfa"].map(num)})
    st.dataframe(ci, width="stretch")
    st.caption("Rentabilidades: promedio aritmético de los rendimientos mensuales en moneda local, anualizado (× 12). Por eso "
               "difieren de las tasas compuestas en USD de la ficha del fondo (por ejemplo, la del S&P 500).")

    st.subheader("Criterios de compra por activo")
    cols = st.columns(2)
    for i, (a, r) in enumerate(f.iterrows()):
        tk = R["tec"].loc[a] if a in R["tec"].index else pd.Series(dtype=object)
        financ = r["Sector"] == "Servicios financieros"
        pts = [f"ROA {num(r['Puntos ROA'], 0)}", f"ROE {num(r['Puntos ROE'], 0)}"] + \
              ([] if financ else [f"liquidez {num(r['Puntos Liquidez'], 0)}", f"endeudamiento {num(r['Puntos Endeudamiento'], 0)}"])
        notas = []
        if r["Activos en su sector"] == 1:
            quien = ("Es la única empresa de {} que pasó todos los filtros" if r["Elegibles en su sector"] <= 1
                     else "Es la única empresa de {} en el fondo").format(r["Sector"].lower())
            notas.append(f"{quien}, por eso lleva el peso completo del sector ({pct(r['Peso'], 0)}) y aporta "
                         f"{pct(r['Contribución al riesgo'])} del riesgo del fondo.")
        if pd.notna(r["Beta local"]) and r["Beta local"] < 0.3:
            notas.append(f"Beta baja ({num(r['Beta local'])} a 3 años; {num(r['Beta local 5 años'])} a 5 años): se mueve poco con "
                         "el mercado porque responde a otros factores (en defensa, la geopolítica y los presupuestos militares). "
                         "Aporta diversificación, pero el CAPM le asigna una prima de riesgo cercana a cero.")
        if a in M.NOTAS_ANALISIS:
            notas.append(M.NOTAS_ANALISIS[a])
        riesgo = r.get(M.COL_RIESGO_ASG)
        with cols[i % 2].container(border=True):
            st.markdown(f"**{M.nombre_corto(r['Empresa'], 40)}** · `{a}` · {pct(r['Peso'])} del fondo")
            st.markdown(
                f"- **Fundamental:** ROA {pct(r['ROA (Retorno Activos)'])}, ROE {pct(r['ROE (Retorno Capital)'])}"
                + ("" if financ else f", liquidez {num(r['Ratio Liquidez (Current Ratio)'])}x, endeudamiento {pct(r['Endeudamiento'])}")
                + f"; puntos: {', '.join(pts)} → promedio {num(r['Puntaje de salud'])}, salud **{r['Nivel de salud']}**. "
                  f"PER {num(r['PER (Price/Earnings Ratio)'], 1)} ({num(r['PER relativo al sector'])} veces la mediana de su sector); "
                  f"Q de Tobin {num(r.get('Q de Tobin (P/VL)'), 1)} ({num(r.get('Q de Tobin relativa al sector'))} veces su sector); "
                  f"dividend yield {pct(r.get('Dividend yield'))}.\n"
                f"- **Bursatilidad:** Sharpe {num(r['Sharpe'])} frente a {num(r['Sharpe del índice'])} del "
                f"{M.NOMBRE_INDICE.get(r['Índice local'], r['Índice local'])}; alfa de Jensen {pct(r['Alfa de Jensen'])} anual; "
                f"beta {num(r['Beta local'])} ({'alto riesgo' if r['Alto riesgo'] else 'riesgo moderado'}).\n"
                f"- **Técnico:** al seleccionar ({fecha_sel}) {str(r['Lectura técnica']).lower()}; "
                f"hoy {str(tk.get('Lectura técnica', 'Sin datos')).lower()}"
                + (f" · RSI {num(tk.get('RSI 14'), 0)} · {pct(tk.get('Distancia al máximo 52 semanas'))} frente al máximo de 52 semanas"
                   if 'RSI 14' in tk and pd.notna(tk.get('RSI 14')) else "") + ".\n"
                f"- **En el portafolio:** aporta {pct(r['Contribución al riesgo'])} del riesgo"
                + ("" if pd.isna(r["Peso mínimo (escenarios)"]) else
                   f"; en los escenarios de robustez su peso va de {pct(r['Peso mínimo (escenarios)'], 0)} a "
                   f"{pct(r['Peso máximo (escenarios)'], 0)}") + ".\n"
                f"- **ASG:** {r['Criterio ASG']}"
                + ("" if pd.isna(riesgo) else f"; riesgo ASG {num(riesgo, 1)} ({M.nivel_riesgo_asg(riesgo)}, Sustainalytics)")
                + (f". {r['Nota ASG']}" if r["Nota ASG"] else "."))
            for n in notas:
                st.caption(n)

# ------------------------------------------------------------------ 4. frontera eficiente
with tabs[3]:
    fr = of["frontera"]
    misma = fr.get("mismas_empresas", False)
    n_el = fr.get("n_elegibles", 0)
    st.subheader("Frontera eficiente de Markowitz")
    st.markdown("Siguiendo el proceso de *asset allocation* del curso: (1) escogencia de activos, (2) proyección del retorno "
                "esperado, (3) **frontera eficiente** y (4) selección del portafolio según las restricciones de la política. "
                "Las fronteras se calculan sin ventas en corto, con rendimientos mensuales en USD de los últimos "
                f"{M.VENTANA_ANIOS} años y la rentabilidad esperada del modelo (½ histórica + ½ CAPM).")
    pc, pf = fr["candidatas"]["puntos"], fr["fondo"]["puntos"]
    n_txt = f"Frontera con las {n_el} empresas que pasaron todos los filtros"
    f_txt = f"Frontera con los {len(f)} activos del fondo"
    lin = []
    if len(pc) and not misma:
        lin.append(pc[["Volatilidad", "Rentabilidad"]].assign(Serie=n_txt))
    if len(pf):
        lin.append(pf[["Volatilidad", "Rentabilidad"]].assign(Serie=f_txt))
    msc = fr["candidatas"]["max_sharpe"]
    ymax = max(float(pc["Rentabilidad"].max()) if len(pc) else 0.3, float(f["E(R) anual USD"].max())) * 1.1
    xcml = min((ymax - of["rf"]) / msc["Sharpe"], msc["Volatilidad"] * 1.8) if msc["Sharpe"] > 0 else msc["Volatilidad"]
    lin.append(pd.DataFrame({"Volatilidad": [0, xcml], "Rentabilidad": [of["rf"], of["rf"] + msc["Sharpe"] * xcml],
                             "Serie": "Línea del mercado de capitales"}))
    lin = pd.concat(lin)
    dom = ([] if misma else [n_txt]) + [f_txt, "Línea del mercado de capitales"]
    rng = (["#9aa9b1"] if not misma else []) + [AZUL, "#9aa9b1"]
    capas = [alt.Chart(lin).mark_line().encode(
        x=alt.X("Volatilidad:Q", axis=alt.Axis(format="%"), title="Volatilidad anual (USD)"),
        y=alt.Y("Rentabilidad:Q", axis=alt.Axis(format="%"), title="Rentabilidad esperada anual"),
        color=alt.Color("Serie:N", scale=alt.Scale(domain=dom, range=rng), legend=alt.Legend(orient="bottom", title=None, labelLimit=360)),
        strokeDash=alt.condition(alt.datum.Serie == "Línea del mercado de capitales", alt.value([5, 4]), alt.value([1, 0])))]
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
    filas_pts = [
        {"Portafolio": "Fondo (parte en acciones)", "Volatilidad": s_acc, "Rentabilidad": e_acc, "Sharpe": (e_acc - of["rf"]) / s_acc},
        {"Portafolio": f"Mínima varianza ({len(f)} activos)", **{k: fr["fondo"]["min_varianza"][k] for k in ("Volatilidad", "Rentabilidad")},
         "Sharpe": (fr["fondo"]["min_varianza"]["Rentabilidad"] - of["rf"]) / fr["fondo"]["min_varianza"]["Volatilidad"]},
        {"Portafolio": f"Máximo Sharpe ({len(f)} activos)", **{k: fr["fondo"]["max_sharpe"][k] for k in ("Volatilidad", "Rentabilidad", "Sharpe")}}]
    if not misma:
        filas_pts.append({"Portafolio": f"Máximo Sharpe ({n_el} empresas que pasaron los filtros)",
                          **{k: msc[k] for k in ("Volatilidad", "Rentabilidad", "Sharpe")}})
    pts = pd.DataFrame(filas_pts)
    forma = alt.Scale(domain=list(pts["Portafolio"]), range=["diamond", "square", "triangle-up", "triangle-down"][:len(pts)])
    colp = alt.Scale(domain=list(pts["Portafolio"]), range=[ARENA, AZUL, AZUL, "#9aa9b1"][:len(pts)])
    capas.append(alt.Chart(pts).mark_point(size=170, filled=True).encode(
        x="Volatilidad:Q", y="Rentabilidad:Q",
        shape=alt.Shape("Portafolio:N", scale=forma, legend=alt.Legend(orient="bottom", title=None, labelLimit=360)),
        color=alt.Color("Portafolio:N", scale=colp, legend=None),
        tooltip=["Portafolio", alt.Tooltip("Volatilidad:Q", format=".1%"), alt.Tooltip("Rentabilidad:Q", format=".1%"),
                 alt.Tooltip("Sharpe:Q", format=".2f")]))
    st.altair_chart(alt.layer(*capas).resolve_scale(color="independent", shape="independent").properties(height=430),
                    width="stretch")
    t = pts.copy()
    t["Volatilidad"], t["Rentabilidad"], t["Sharpe"] = t["Volatilidad"].map(pct), t["Rentabilidad"].map(pct), t["Sharpe"].map(num)
    st.dataframe(t.set_index("Portafolio"), width="stretch")
    notas_fr = ["El fondo queda por debajo de la frontera porque la política exige 5 sectores con igual peso, mínimo 5 % por "
                "activo, ≥ 50 % en acciones con β > 1, Asia ≤ 35 % y VaR ≤ 8 %. Esa distancia es el costo, en Sharpe, de diversificar.",
                f"Aquí se muestra solo la parte en acciones (volatilidad {pct(s_acc)}, rentabilidad {pct(e_acc)}); el encabezado "
                f"incluye el 5 % de liquidez ({pct(rs['Volatilidad anual'])} y {pct(rs['E(R) anual'])})."]
    if misma:
        notas_fr.insert(0, f"Con los datos al {fecha_sel} solo estas {len(f)} empresas pasaron todos los filtros, así que la "
                           "frontera con todas las elegibles es la misma frontera del fondo: ningún activo que quedó por fuera "
                           "habría mejorado el Sharpe.")
    for n in notas_fr:
        st.caption(n)
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
    par = of["par_max_correlacion"]
    st.markdown(f"Correlación de los rendimientos mensuales en USD en los **{of['meses_caida']} meses** en que cayó el índice "
                f"compuesto. **Meta** de la política (no es un límite): ≤ {num(M.POLITICA['max_correlacion_caidas'], 1)} entre "
                f"cada par. Máxima observada: **{num(of['max_correlacion_caidas'])}**"
                + (f" ({par[0]} y {par[1]})." if par[0] else "."))
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
    st.markdown(f"""
0. **Universo analizado.** Todas las empresas del S&P 500 y las mayores de las bolsas de Taiwán y Corea del Sur (cerca de
   600). Sus fundamentales se descargan de Yahoo Finance cada noche. Que una empresa de un país esté en el universo no
   significa que el fondo invierta en ese país: el fondo invierte hoy en {txt_mercados}.
1. **Criterios ASG.** Se excluyen armas controvertidas, tabaco y carbón térmico (por nombre, sector e industria) y las
   empresas con **riesgo ASG severo** (ESG Risk Score de Sustainalytics ≥ {M.RIESGO_ASG_MAX:.0f}, publicado por Yahoo
   Finance; sin dato no se excluye). La energía fósil no puede superar el 20 % del fondo. Es una restricción de
   «circunstancias únicas» de la política de inversión (guía AMV).
2. **Filtro 1 · salud financiera (fundamentales).** Semáforo de ROA (> 6 %), ROE (> 12 %), liquidez corriente (> 1,5x) y
   endeudamiento (< 50 %). Cada indicador vale 2 puntos si supera el umbral, 1 si es aceptable (ROA y ROE positivos;
   liquidez de 1,0x a 1,5x; endeudamiento de 50 % a 70 %) y 0 si no. Solo pasan las empresas con promedio ≥ 1,5 (nivel
   Bueno). En bancos y aseguradoras solo cuentan ROA y ROE. También se excluyen PER ≤ 0, patrimonio negativo y empresas con
   una Q de Tobin (precio / valor en libros) mayor a 3 veces la mediana de su sector.
3. **Filtro 2 · bursatilidad frente al índice local.** Con 3 años de precios mensuales en moneda local, cada empresa debe tener
   un Sharpe mayor que el de su índice (S&P 500, TAIEX o KOSPI) y alfa de Jensen positivo. Se ordenan, con igual peso, por
   Sharpe y rentabilidad frente al índice y por PER y Q de Tobin frente a su sector. Más sensibles al mercado: β local > 1.
4. **Filtro 3 · criterio técnico de compra: retroceso dentro de una tendencia alcista.** Condición obligatoria: el precio debe
   estar sobre su media móvil de 200 días. Además se revisan tres señales: media de 50 días sobre la de 200, MACD sobre su
   señal y RSI (14) entre 30 y 50. Con 2 o 3 señales la lectura es Favorable, con 1 Neutral y con 0, o con el precio bajo la
   media de 200 días, Desfavorable. No se compran acciones con lectura Desfavorable. El técnico decide **cuándo comprar**; no
   saca a un activo del portafolio.
5. **Asignación por sectores.** En cada sector se toman sus 2 mejores empresas; si solo una cumple todos los criterios,
   esa empresa lleva el peso completo del sector (ningún filtro se relaja). Cada uno de los 5 sectores recibe el mismo peso
   (19 % del fondo) y, dentro del sector, los pesos se fijan con Markowitz (máximo Sharpe, mínimo 5 % por activo). Si hay
   más de 5 sectores con candidatas, se elige la combinación de mayor Sharpe que cumpla la política (≥ 50 % en acciones con
   β > 1, Taiwán + Corea ≤ 35 %, VaR 95 % a 1 mes ≤ 8 %).
6. **Riesgo y rentabilidad esperada.** VaR = N · σ · Z · √t con Z al 95 % y t = 1 mes. La rentabilidad esperada es ½
   histórica en USD + ½ CAPM local llevado a USD por paridad de tasas; es **bruta**: la neta descuenta la comisión de 2,5 %
   E.A. La mitad histórica hereda parte del sesgo de selección (ver la prueba fuera de muestra).
7. **Robustez.** Con los activos del fondo se recalculan los pesos óptimos en {M.N_ESCENARIOS} escenarios (ventanas de 5, 3
   y 2 años × 2 métodos de rentabilidad × 3 pisos por activo × 3 tasas libres de riesgo); se informa en cuántos la estructura
   cumple la política y el rango del peso de cada activo.
8. **Revisión ({M.REVISION}) y rebalanceo.** El portafolio oficial queda congelado entre revisiones. Un activo sale si deja de
   cumplir un criterio fundamental (ASG, salud financiera o bursatilidad); un peso vuelve a su objetivo si se desvía más de
   3 puntos.
9. **Alto riesgo.** Toda la renta variable es de alto riesgo por clase de activo (monetario: bajo; renta fija: medio; renta
   variable: alto), así que el fondo tiene {pct(rs['Alto riesgo por clase de activo'], 0)} en alto riesgo. Como exigencia
   adicional, al seleccionar, al menos el 50 % debe estar en acciones con β > 1.
""")
    n_sec = len(of["sectores_disponibles"])
    if n_sec == M.N_SECTORES:
        txt_comb = (f"Con los datos al {fecha_sel} solo {n_sec} sectores tuvieron empresas que cumplieran todos los filtros "
                    f"({', '.join(of['sectores'])}), por lo que la combinación de sectores quedó determinada por los filtros.")
    elif n_sec > M.N_SECTORES:
        txt_comb = (f"Con los datos al {fecha_sel}, {n_sec} sectores tuvieron empresas que cumplieran todos los filtros. "
                    f"Sectores del fondo: {', '.join(of['sectores'])}.")
        if pd.notna(of.get("robustez_combinacion")):
            txt_comb += f" La misma combinación ganó en {pct(of['robustez_combinacion'], 0)} de los escenarios."
    else:
        txt_comb = (f"Con los datos al {fecha_sel}, {plural(n_sec, 'sector tuvo', 'sectores tuvieron')} empresas que cumplieran "
                    f"todos los filtros. Sectores del fondo: {', '.join(of['sectores'])}.")
    st.markdown(txt_comb)
    if of.get("escenarios_total"):
        st.markdown(f"**Robustez:** la estructura del fondo cumple la política en **{of['escenarios_validos']} de "
                    f"{of['escenarios_total']} escenarios**. Rango del peso de cada activo:")
        rp = of["robustez_pesos"]
        if len(rp):
            st.dataframe(pd.DataFrame({"Peso oficial": of["pesos"].map(pct), "Mínimo": rp.min().map(pct),
                                       "Promedio": rp.mean().map(pct), "Máximo": rp.max().map(pct)}).T, width="stretch")
    if not of["var_cumple"]:
        st.warning("El portafolio no cumple el VaR de 8 % con los datos de la fecha de selección.")
    st.subheader("Verificación del portafolio oficial")
    st.dataframe(R["verif"], width="stretch", hide_index=True)
    st.caption("«Informativo»: dato que se reporta sin ser una regla obligatoria. La correlación en meses de caída es una meta "
               "de diversificación, no un límite.")

# ------------------------------------------------------------------ 6. ASG
with tabs[5]:
    st.subheader("Política de sostenibilidad")
    st.markdown(f"""
- **Exclusiones:** armas controvertidas (minas antipersonal, municiones de racimo, armas químicas y biológicas), tabaco y
  carbón térmico.
- **Riesgo ASG:** se excluyen las empresas con riesgo ASG severo (ESG Risk Score de Sustainalytics ≥ {M.RIESGO_ASG_MAX:.0f}).
  Escala: insignificante (< 10), bajo (10-20), medio (20-30), alto (30-40) y severo (≥ 40).
- **Transición energética:** la energía fósil no puede superar el 20 % del fondo.
- **Evaluación y seguimiento:** cada emisor se revisa antes de la compra y en cada revisión {M.REVISION}; las notas del
  comité quedan en la ficha.
- **Gobierno corporativo:** voto informado y diálogo con los emisores.
""")
    if M.COL_RIESGO_ASG in f:
        ra = pd.DataFrame({"Empresa": f["Empresa"].map(M.nombre_corto), "Riesgo ASG": f[M.COL_RIESGO_ASG].map(lambda v: num(v, 1)),
                           "Nivel": f[M.COL_RIESGO_ASG].map(M.nivel_riesgo_asg)})
        st.markdown("**Riesgo ASG de los activos del fondo (Sustainalytics, vía Yahoo Finance)**")
        st.dataframe(ra, width="stretch")
    ex = pre.loc[pre["Criterio ASG"] != "Cumple", ["Empresa", "Mercado", "Sector", "Criterio ASG"]]
    st.markdown(f"**Empresas del universo excluidas por ASG** ({len(ex)} de {len(pre)})")
    st.dataframe(ex if len(ex) else pd.DataFrame({"Resultado": ["Ninguna empresa del universo cae en las exclusiones."]}),
                 width="stretch")
    notas = f.loc[f["Nota ASG"] != "", ["Empresa", "Nota ASG"]]
    if len(notas):
        st.markdown("**Notas del comité**")
        st.dataframe(notas, width="stretch")

st.divider()
st.caption("Advertencia: ejercicio académico del curso Gestión de Portafolios, Universidad del Valle. Las rentabilidades esperadas y "
           "las simulaciones históricas no garantizan rentabilidades futuras. Fuente de precios: Yahoo Finance.")
