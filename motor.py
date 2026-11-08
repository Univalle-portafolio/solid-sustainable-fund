"""
Motor de selección de activos del fondo Solidez Sostenible Renta Variable.

Implementa la misma metodología del cuaderno Motor_ajustado_v5:
  1. Criterios ASG (exclusión de armas controvertidas, tabaco y carbón térmico).
  2. Filtro 1: salud financiera (semáforo de ROA, ROE, liquidez corriente y endeudamiento).
  3. Filtro 2: bursatilidad frente al índice local (Sharpe y alfa de Jensen > 0; orden por Sharpe y rentabilidad
     frente al índice, PER y Q de Tobin frente a su sector).
  4. Filtro 3: técnico de compra: precio sobre su media de 200 días (obligatorio) y lectura técnica no desfavorable
     (media de 50 sobre la de 200, MACD sobre su señal y RSI entre 30 y 50: retroceso dentro de una tendencia alcista).
  5. Asignación: 5 sectores con igual peso (19 % cada uno) y sus 2 mejores empresas; entre todas las combinaciones de
     5 sectores que cumplen la política (alto riesgo, Asia, VaR ≤ 8 %) se elige la de mayor Sharpe, con Markowitz
     dentro de cada sector.
  6. Robustez en 54 escenarios, frontera eficiente y verificación.

Todas las funciones reciben los datos como argumentos: no dependen de Streamlit y se pueden probar solas.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import linprog, minimize
from scipy.stats import norm

# ----------------------------------------------------------------------------------------------
# Parámetros del fondo (modifíquelos aquí)
# ----------------------------------------------------------------------------------------------
NOMBRE_FONDO = "Solidez Sostenible Renta Variable"
NOMBRE_FORMAL = "Fondo de Inversión Colectiva Solidez Sostenible Renta Variable"
ESLOGAN = "Invertir con solidez, crecer con propósito."
INVERSION = 1_000_000                     # USD
CANDIDATOS_POR_MERCADO = 5
VENTANA_ANIOS = 3                         # ventana de análisis (años), como en las valoraciones de las empresas
VENTANAS_ROBUSTEZ = (5, 3, 2)              # ventanas alternativas de la prueba de robustez
TECNICO_EXCLUIDO = "Desfavorable"          # filtro técnico de compra: no se compra con lectura técnica desfavorable
PESO_LIQUIDEZ = 0.05

N_SECTORES = 5                            # sectores del fondo, con igual peso cada uno
ACTIVOS_POR_SECTOR = 2                    # mejores empresas de cada sector
RSI_RANGO = (30, 50)                      # retroceso dentro de la tendencia alcista (sin sobreventa)
Q_TOBIN_MAX_RELATIVA = 3.0                # se excluye si la Q de Tobin supera 3 veces la mediana de su sector
Z_95 = 1.6448536269514722                 # Z al 95 % (VaR = N · σ · Z · √t)
POLITICA = {
    "min_activos": 5, "max_activos": 10,      # enunciado del trabajo final
    "min_alto_riesgo": 0.50,                  # enunciado: β local > 1
    "piso": 0.10, "tope": 0.20,               # por activo (método anterior, solo para la comparación)
    "piso_activo": 0.05,                      # mínimo por activo dentro de su sector (sobre el fondo total)
    "max_var_mensual": 0.08,                  # VaR 95 % a 1 mes ≤ 8 % del fondo
    "max_correlacion_caidas": 0.50,           # meta (se informa): correlación entre pares en meses de caída
    "max_tecnologia": 0.50,
    "max_asia": 0.35,                         # Taiwán + Corea
    "max_energia": 0.20,                      # ASG: transición energética
    "min_anios_historia": 2,
    "robustez_minima": 0.80,
    "rebalanceo_puntos": 0.03,                # desviación que activa un rebalanceo
}

ASG = {
    "excluir_tickers": {"033780.KS": "tabaco (KT&G)"},
    "armas_controvertidas": {},               # tickers de listas oficiales (p. ej., Consejo de Ética de Noruega)
    "palabras_excluidas": {"tobacco": "tabaco", "tabaco": "tabaco", "cigar": "tabaco",
                           "coal": "carbón térmico", "carbón": "carbón térmico"},
    # Industrias de Yahoo Finance que se excluyen o se revisan cuando el universo se descarga automáticamente
    "industrias_excluidas": {"tobacco": "tabaco", "thermal coal": "carbón térmico"},
    "industrias_revision": {"aerospace & defense": "defensa: verificar que no fabrique armas controvertidas"},
    "notas": {"012450.KS": "Defensa convencional, permitida: Hanwha Corp dejó de producir municiones de racimo "
                           "y Noruega revocó su exclusión en 2021."},
}

UMBRAL_SALUD = {"ROA": 0.06, "ROE": 0.12, "liq_bueno": 1.5, "liq_prec": 1.0,
                "end_bueno": 0.50, "end_prec": 0.70, "nivel_bueno": 1.5, "nivel_prec": 1.0}

FX_YF = {"TWD": "TWD=X", "KRW": "KRW=X"}
MONEDA_MERCADO = {"EEUU": "USD", "Taiwan": "TWD", "Corea": "KRW"}
NOMBRE_INDICE = {"^GSPC": "S&P 500", "^TWII": "TAIEX", "^KS11": "KOSPI"}

ACC = 1 - PESO_LIQUIDEZ
LIM = {k: POLITICA[k] / ACC for k in ("piso", "tope", "min_alto_riesgo", "max_tecnologia", "max_asia", "max_energia")}


# ----------------------------------------------------------------------------------------------
# Datos
# ----------------------------------------------------------------------------------------------
def cargar_ranking(ruta: str):
    consol = pd.read_excel(ruta, sheet_name="Consolidado").set_index("Ticker")
    indices = pd.read_excel(ruta, sheet_name="Indices").set_index("Mercado")
    return consol, indices


def cargar_universo(ruta: str):
    """Universo descargado automáticamente (data/universo.csv). Devuelve el universo, los índices y la fecha de actualización."""
    import universo as U
    u = pd.read_csv(ruta, index_col="Ticker")
    fecha = str(u["Fecha de actualización"].iloc[0]) if "Fecha de actualización" in u else None
    return u, U.INDICES.copy(), fecha


def prefiltro(universo: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Filtros que no necesitan precios (ASG, salud financiera Buena y PER positivo).
    Devuelve (empresas que siguen, tabla del universo completo con el resultado). La mediana del PER por sector se
    calcula sobre el universo completo, para que el PER relativo no dependa de qué empresas pasaron el filtro."""
    d = salud_financiera(universo)
    d["Criterio ASG"] = criterio_asg(d)
    per = d["PER (Price/Earnings Ratio)"].where(d["PER (Price/Earnings Ratio)"] > 0)
    d["Mediana PER del sector"] = per.groupby(d["Sector"]).transform("median")
    if "Q de Tobin (P/VL)" in d:
        q = d["Q de Tobin (P/VL)"].where(d["Q de Tobin (P/VL)"] > 0)
        d["Mediana Q del sector"] = q.groupby(d["Sector"]).transform("median")
    pasa = d["Criterio ASG"].eq("Cumple") & d["Nivel de salud"].eq("Bueno") & (d["PER (Price/Earnings Ratio)"] > 0)
    motivo = pd.Series("", index=d.index)
    motivo[d["Criterio ASG"] != "Cumple"] += "ASG: " + d["Criterio ASG"].str.replace("Excluida: ", "", regex=False) + "; "
    motivo[d["Nivel de salud"] != "Bueno"] += "salud " + d["Nivel de salud"].str.lower() + "; "
    motivo[~(d["PER (Price/Earnings Ratio)"] > 0)] += "PER no positivo; "
    d["Motivo de exclusión"] = motivo.str.rstrip("; ")
    d["Pasa a bursatilidad"] = pasa
    extra = {c: d.loc[pasa, c] for c in ("Mediana PER del sector", "Mediana Q del sector") if c in d}
    return universo.loc[pasa].assign(**extra), d


def descargar_precios(tickers, inicio="2015-01-01", fin=None) -> pd.DataFrame:
    """Precios diarios de cierre ajustados (Yahoo Finance)."""
    import yfinance as yf
    fin = pd.Timestamp.today().normalize() if fin is None else pd.Timestamp(fin)
    raw = yf.download(list(tickers), start=inicio, end=fin + pd.Timedelta(days=1), auto_adjust=True,
                      progress=False, threads=True)
    raw = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]].rename(columns={"Close": tickers[0]})
    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    return raw.dropna(how="all", axis=1).sort_index()


def fundamentales_yahoo(tickers) -> pd.DataFrame:
    """ROA, ROE, liquidez corriente, deuda/capital y PER más recientes de Yahoo Finance (si están disponibles)."""
    import yfinance as yf
    filas = {}
    for t in tickers:
        try:
            info = yf.Ticker(t).info
        except Exception:
            continue
        de = info.get("debtToEquity")
        filas[t] = {"ROA (Retorno Activos)": info.get("returnOnAssets"),
                    "ROE (Retorno Capital)": info.get("returnOnEquity"),
                    "Ratio Liquidez (Current Ratio)": info.get("currentRatio"),
                    "Ratio Deuda/Capital (Debt/Equity)": None if de is None else de / 100,   # Yahoo lo da en %
                    "PER (Price/Earnings Ratio)": info.get("trailingPE")}
    return pd.DataFrame.from_dict(filas, orient="index").apply(pd.to_numeric, errors="coerce")


def aplicar_fundamentales(consol: pd.DataFrame, nuevos: pd.DataFrame) -> pd.DataFrame:
    """Reemplaza los fundamentales del ranking por los de Yahoo donde existan."""
    d = consol.copy()
    for c in nuevos.columns:
        if c in d.columns:
            v = nuevos[c].reindex(d.index)
            d[c] = v.where(v.notna(), d[c])
    return d


def preparar(consol, indices, diario, fin=None):
    """Recorta los precios a `fin` y arma rendimientos mensuales en moneda local y en USD."""
    fin = diario.index.max() if fin is None else min(pd.Timestamp(fin), diario.index.max())
    d = diario[diario.index <= fin].ffill(limit=5)
    mensual = d.resample("ME").last()
    mensual.index = [min(x, fin) for x in mensual.index]            # el mes en curso queda con fecha `fin`
    mercado = consol["Mercado"].to_dict()
    idx_local = indices["Índice"].to_dict()
    moneda_t = {t: MONEDA_MERCADO.get(m, "USD") for t, m in mercado.items()}
    for m, ix in idx_local.items():
        moneda_t[ix] = MONEDA_MERCADO.get(m, "USD")

    def a_usd(df):
        out = pd.DataFrame(index=df.index)
        for t in df.columns:
            mon = moneda_t.get(t)
            if mon is None:
                continue
            if mon == "USD":
                out[t] = df[t]
            elif FX_YF[mon] in df.columns:
                out[t] = df[t] / df[FX_YF[mon]]
        return out

    m_usd, d_usd = a_usd(mensual), a_usd(d)
    rf_us = None
    if "^IRX" in d.columns and d["^IRX"].notna().any():
        rf_us = d["^IRX"].dropna()
    return {"fin": fin, "diario_loc": d, "diario_usd": d_usd,
            "R_loc": mensual.pct_change(fill_method=None).iloc[1:], "R_usd": m_usd.pct_change(fill_method=None).iloc[1:],
            "mercado": mercado, "indice_local": idx_local, "rf_us_diaria": rf_us}


def tasas_libres(indices, datos):
    """Tasa libre de riesgo anual por mercado. EE. UU. usa el último T-bill (^IRX) si está disponible."""
    rf = indices["Rf usada"].astype(float).to_dict()
    if datos["rf_us_diaria"] is not None:
        rf["EEUU"] = float(datos["rf_us_diaria"].iloc[-1]) / 100
    return rf


# ----------------------------------------------------------------------------------------------
# Filtros: ASG, salud financiera, bursatilidad
# ----------------------------------------------------------------------------------------------
def _puntos(v, bueno, prec, mayor_mejor=True):
    if pd.isna(v):
        return np.nan
    if mayor_mejor:
        return 2.0 if v > bueno else (1.0 if v >= prec else 0.0)
    return 2.0 if v < bueno else (1.0 if v <= prec else 0.0)


def criterio_asg(d: pd.DataFrame) -> pd.Series:
    texto = (d["Empresa"].astype(str) + " " + d["Sector"].astype(str)).str.lower()
    industria = d["Industria"].fillna("").astype(str).str.lower() if "Industria" in d else pd.Series("", index=d.index)
    asg = pd.Series("Cumple", index=d.index)
    for t, motivo in {**ASG["excluir_tickers"], **{k: "armas controvertidas" for k in ASG["armas_controvertidas"]}}.items():
        if t in asg.index:
            asg[t] = "Excluida: " + motivo
    for pal, motivo in ASG["palabras_excluidas"].items():
        asg[texto.str.contains(pal, regex=False) & asg.eq("Cumple")] = "Excluida: " + motivo
    for ind, motivo in ASG["industrias_excluidas"].items():
        asg[industria.str.contains(ind, regex=False) & asg.eq("Cumple")] = "Excluida: " + motivo
    return asg


def notas_asg(d: pd.DataFrame) -> pd.Series:
    """Observaciones ASG que no excluyen (p. ej., defensa convencional) para revisión del comité."""
    industria = d["Industria"].fillna("").astype(str).str.lower() if "Industria" in d else pd.Series("", index=d.index)
    n = pd.Series("", index=d.index)
    for ind, txt in ASG["industrias_revision"].items():
        n[industria.str.contains(ind, regex=False)] = txt
    for t, txt in ASG["notas"].items():
        if t in n.index:
            n[t] = txt
    return n


def salud_financiera(d: pd.DataFrame) -> pd.DataFrame:
    u = UMBRAL_SALUD
    d = d.copy()
    de = d["Ratio Deuda/Capital (Debt/Equity)"]
    d["Endeudamiento"] = (de / (1 + de)).where(de >= 0)
    pts = pd.DataFrame({
        "ROA": d["ROA (Retorno Activos)"].map(lambda v: _puntos(v, u["ROA"], 0)),
        "ROE": d["ROE (Retorno Capital)"].map(lambda v: _puntos(v, u["ROE"], 0)),
        "Liquidez": d["Ratio Liquidez (Current Ratio)"].map(lambda v: _puntos(v, u["liq_bueno"], u["liq_prec"])),
        "Endeudamiento": d["Endeudamiento"].map(lambda v: _puntos(v, u["end_bueno"], u["end_prec"], False)),
    })
    pts.loc[d["Sector"].eq("Servicios financieros"), ["Liquidez", "Endeudamiento"]] = np.nan
    d["Puntaje de salud"] = pts.mean(axis=1).where(pts.notna().sum(axis=1) >= 2)
    s = d["Puntaje de salud"]
    d["Nivel de salud"] = np.where(s.isna(), "Sin datos", np.where(s >= u["nivel_bueno"], "Bueno",
                                   np.where(s >= u["nivel_prec"], "Precaución", "Crítico")))
    return d


def stats_locales(datos, rf_local, activos, anios=VENTANA_ANIOS):
    """Cada activo frente a su índice local, en moneda local: rentabilidad, volatilidad, Sharpe, beta, alfa."""
    R = datos["R_loc"]
    R = R[R.index > R.index.max() - pd.DateOffset(years=anios)]
    filas = {}
    for a in activos:
        m = datos["mercado"].get(a)
        ix = datos["indice_local"].get(m)
        if a not in R.columns or ix not in R.columns:
            continue
        z = R[[a, ix]].dropna()
        if len(z) < 12 * POLITICA["min_anios_historia"] or len(z) < 0.9 * len(R):
            continue
        rf_m = rf_local[m] / 12
        ea, ei = z[a] - rf_m, z[ix] - rf_m
        beta = np.cov(ea, ei)[0, 1] / np.var(ei, ddof=1)
        a_m = ea.mean() - beta * ei.mean()
        res = ea - (a_m + beta * ei)
        n = len(z)
        se = np.sqrt((res ** 2).sum() / (n - 2) * (1 / n + ei.mean() ** 2 / ((ei - ei.mean()) ** 2).sum()))
        vol_a, vol_i = z[a].std() * np.sqrt(12), z[ix].std() * np.sqrt(12)
        filas[a] = {"Mercado": m, "Índice local": ix,
                    "Rentabilidad anual": z[a].mean() * 12, "Rentabilidad del índice": z[ix].mean() * 12,
                    "Volatilidad anual": vol_a, "Sharpe": ea.mean() * 12 / vol_a, "Sharpe del índice": ei.mean() * 12 / vol_i,
                    "Beta local": beta, "Alfa de Jensen": a_m * 12, "t del alfa": a_m / se if se > 0 else np.nan}
    return pd.DataFrame.from_dict(filas, orient="index")


def lectura_tecnica_compra(datos, activos) -> pd.Series:
    """Filtro técnico de compra: lectura técnica de cada activo con los precios hasta la fecha de selección.
    Condición obligatoria: precio > media de 200 días (tendencia alcista de largo plazo). Señales: media 50 > media 200,
    MACD > señal y RSI 14 entre 30 y 50. Favorable (2-3 señales), Neutral (1) o Desfavorable (0 o precio bajo la media 200)."""
    p = datos["diario_loc"]
    return pd.Series({a: (tecnico(p[a])["Lectura técnica"] if a in p.columns else "Sin datos") for a in activos}, dtype=object)


def evaluar_universo(consol, indices, datos):
    """Aplica ASG, salud financiera y bursatilidad al universo. Devuelve la tabla y la lista de candidatos."""
    rf_local = tasas_libres(indices, datos)
    d = salud_financiera(consol)
    d["Criterio ASG"] = criterio_asg(d)
    per = d["PER (Price/Earnings Ratio)"].where(d["PER (Price/Earnings Ratio)"] > 0)
    med = d["Mediana PER del sector"] if "Mediana PER del sector" in d else per.groupby(d["Sector"]).transform("median")
    d["PER relativo al sector"] = per / med
    if "Q de Tobin (P/VL)" in d:
        q = d["Q de Tobin (P/VL)"].where(d["Q de Tobin (P/VL)"] > 0)
        medq = d["Mediana Q del sector"] if "Mediana Q del sector" in d else q.groupby(d["Sector"]).transform("median")
        d["Q de Tobin relativa al sector"] = q / medq
    else:
        d["Q de Tobin relativa al sector"] = np.nan
    est = stats_locales(datos, rf_local, list(d.index))
    if est.empty:
        raise ValueError("No hay precios suficientes para comparar las empresas con sus índices. Revise la conexión con Yahoo Finance.")
    est = est.drop(columns=["Mercado"])
    d = d.drop(columns=[c for c in est.columns if c in d.columns]).join(est, how="left")
    d["Sharpe frente al índice"] = d["Sharpe"] - d["Sharpe del índice"]
    d["Rentabilidad frente al índice"] = d["Rentabilidad anual"] - d["Rentabilidad del índice"]
    d["Supera a su índice"] = (d["Sharpe frente al índice"] > 0) & (d["Alfa de Jensen"] > 0)
    d["Lectura técnica"] = lectura_tecnica_compra(datos, d.index)

    motivo = pd.Series("", index=d.index)
    motivo[d["Criterio ASG"] != "Cumple"] += "ASG: " + d["Criterio ASG"].str.replace("Excluida: ", "", regex=False) + "; "
    motivo[d["Nivel de salud"] != "Bueno"] += "salud " + d["Nivel de salud"].str.lower() + "; "
    motivo[~(d["PER (Price/Earnings Ratio)"] > 0)] += "PER no positivo; "
    motivo[d["Ratio Deuda/Capital (Debt/Equity)"] < 0] += "patrimonio negativo; "
    motivo[d["Sharpe"].isna()] += "sin precios suficientes; "
    motivo[d["Sharpe"].notna() & ~(d["Sharpe frente al índice"] > 0)] += "Sharpe menor que el de su índice; "
    motivo[d["Sharpe"].notna() & ~(d["Alfa de Jensen"] > 0)] += "alfa de Jensen negativo; "
    motivo[d["Q de Tobin relativa al sector"] > Q_TOBIN_MAX_RELATIVA] += "Q de Tobin mayor a 3 veces la de su sector; "
    motivo[d["Sharpe"].notna() & d["Lectura técnica"].eq(TECNICO_EXCLUIDO)] += "lectura técnica desfavorable; "
    d["Motivo de exclusión"] = motivo.str.rstrip("; ")
    d["Elegible"] = d["Motivo de exclusión"] == ""

    # Puntaje de bursatilidad: promedio de percentiles (igual peso) entre todas las elegibles. Sharpe y rentabilidad
    # frente al índice local son comparables entre mercados; PER y Q de Tobin se miden frente a su sector.
    componentes = [("Sharpe frente al índice", True), ("Rentabilidad frente al índice", True), ("PER relativo al sector", False)]
    if d["Q de Tobin relativa al sector"].notna().any():
        componentes.append(("Q de Tobin relativa al sector", False))
    pct = [d[c].where(d["Elegible"]).rank(pct=True, ascending=asc).fillna(0.5) for c, asc in componentes]
    d["Puntaje de bursatilidad"] = (100 * sum(pct) / len(pct)).where(d["Elegible"])
    d["Puesto en su mercado"] = d.groupby("Mercado")["Puntaje de bursatilidad"].rank(ascending=False, method="first")
    d["Puesto en su sector"] = d.groupby("Sector")["Puntaje de bursatilidad"].rank(ascending=False, method="first")
    d["Candidato"] = d["Elegible"] & (d["Puesto en su sector"] <= ACTIVOS_POR_SECTOR)
    d["Alto riesgo"] = d["Beta local"] > 1
    return d, rf_local


# ----------------------------------------------------------------------------------------------
# Optimización con la política del fondo
# ----------------------------------------------------------------------------------------------
def _grupos(tabla, activos):
    h = np.array([1.0 if bool(tabla.loc[a, "Alto riesgo"]) else 0.0 for a in activos])
    tec = np.array([1.0 if tabla.loc[a, "Sector"] == "Tecnología" else 0.0 for a in activos])
    asia = np.array([1.0 if tabla.loc[a, "Mercado"] in ("Taiwan", "Corea") else 0.0 for a in activos])
    ene = np.array([1.0 if tabla.loc[a, "Sector"] == "Energía" else 0.0 for a in activos])
    return [-h, tec, asia, ene], [-LIM["min_alto_riesgo"], LIM["max_tecnologia"], LIM["max_asia"], LIM["max_energia"]]


def _resolver(tabla, mu, S, rf, lb, ub):
    n = len(mu)
    A, b = _grupos(tabla, list(mu.index))
    lp = linprog(np.zeros(n), A_ub=A, b_ub=b, A_eq=[np.ones(n)], b_eq=[1.0], bounds=list(zip(lb, ub)), method="highs")
    if not lp.success:
        return None
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1}] + \
           [{"type": "ineq", "fun": lambda w, a=a, bb=bb: bb - a @ w} for a, bb in zip(A, b)]
    f = lambda w: -(w @ mu.values - rf) / np.sqrt(w @ S.values @ w)
    mejor = None
    for x0 in (lp.x, 0.5 * lp.x + 0.5 * np.clip(np.full(n, 1 / n), lb, ub)):
        r = minimize(f, x0, bounds=list(zip(lb, ub)), constraints=cons, method="SLSQP",
                     options={"maxiter": 1000, "ftol": 1e-10})
        ok = r.success and abs(r.x.sum() - 1) < 1e-6 and all(a @ r.x <= bb + 1e-6 for a, bb in zip(A, b))
        if ok and (mejor is None or r.fun < mejor.fun):
            mejor = r
    return None if mejor is None else pd.Series(np.clip(mejor.x, lb, ub), index=mu.index)


def pesos_politica(tabla, mu, S, rf, tope=None, piso=None):
    tope = LIM["tope"] if tope is None else tope
    piso = LIM["piso"] if piso is None else piso
    w0 = _resolver(tabla, mu, S, rf, np.zeros(len(mu)), np.full(len(mu), tope))
    if w0 is None:
        raise ValueError("Las restricciones de la política no son factibles con estos candidatos.")

    def cabe(sel):
        A_, b_ = _grupos(tabla, sel)
        return all(piso * a_.sum() <= bb_ + 1e-9 for a_, bb_ in zip(A_[1:], b_[1:]))

    orden = []
    for a in w0.sort_values(ascending=False).index:
        if cabe(orden + [a]):
            orden.append(a)
    k_max = min(POLITICA["max_activos"], int(1 / piso + 1e-9), len(orden))
    k = int(np.clip((w0 >= piso / 2).sum(), max(POLITICA["min_activos"], int(np.ceil(1 / tope - 1e-9))), k_max))
    while k <= k_max:
        sel = orden[:k]
        w = _resolver(tabla, mu[sel], S.loc[sel, sel], rf, np.full(k, piso), np.full(k, tope))
        if w is not None:
            return w / w.sum()
        k += 1
    raise ValueError("No existe un portafolio de 5 a 10 activos que cumpla la política con estos candidatos.")


def insumos(tabla, datos, rf_local, activos, anios=VENTANA_ANIOS, metodo="mezcla", desplaz_rf=0.0):
    Ru, Rl = datos["R_usd"], datos["R_loc"]
    ini = Ru.index.max() - pd.DateOffset(years=anios)
    Ru, Rl = Ru[Ru.index > ini], Rl[Rl.index > ini]
    act = [a for a in activos if a in Ru.columns and Ru[a].notna().all() and Rl[a].notna().all()]
    mu_h = Ru[act].mean() * 12
    capm = {}
    for a in act:
        m = tabla.loc[a, "Mercado"]
        ix = datos["indice_local"][m]
        rf_m = rf_local[m] + desplaz_rf
        ex, exm = Rl[a] - rf_m / 12, Rl[ix] - rf_m / 12
        beta = np.cov(ex, exm)[0, 1] / np.var(exm, ddof=1)
        capm[a] = rf_m + beta * (Rl[ix].mean() * 12 - rf_m) + (rf_local["EEUU"] - rf_local[m])
    capm = pd.Series(capm, dtype=float)
    mu = {"historica": mu_h, "capm": capm, "mezcla": (mu_h + capm) / 2}[metodo]
    return mu, Ru[act].cov() * 12, rf_local["EEUU"] + desplaz_rf


# ----------------------------------------------------------------------------------------------
# Asignación por sectores: 5 sectores con igual peso y Markowitz dentro de cada sector
# ----------------------------------------------------------------------------------------------
SIGMA_MAX_ACC = POLITICA["max_var_mensual"] * np.sqrt(12) / (Z_95 * ACC)   # volatilidad anual máxima de la parte en acciones


def var_mensual(sigma_anual_fondo: float) -> float:
    """VaR 95 % a 1 mes como fracción del fondo, con la fórmula del curso: VaR = N · σ · Z · √t (t = 1/12)."""
    return sigma_anual_fondo * Z_95 * np.sqrt(1 / 12)


def sectores_candidatos(tabla) -> dict:
    """Sectores con al menos 2 empresas que pasan todos los filtros, y sus 2 mejores por puntaje de bursatilidad."""
    c = tabla[tabla["Elegible"]].sort_values("Puntaje de bursatilidad", ascending=False)
    out = {}
    for s, g in c.groupby("Sector", sort=False):
        if len(g) >= ACTIVOS_POR_SECTOR:
            out[s] = list(g.index[:ACTIVOS_POR_SECTOR])
    return out


def _optimizar_estructura(tabla, activos, mu, S, rf, piso=None, con_var=True):
    """Máximo Sharpe con pesos iguales por sector (sobre la parte invertida), piso por activo, ≥ 50 % alto riesgo,
    Asia ≤ 35 % y, si con_var, VaR ≤ 8 %. Devuelve pesos sobre la parte invertida (suman 1) o None."""
    piso = (POLITICA["piso_activo"] if piso is None else piso) / ACC
    sectores = list(dict.fromkeys(tabla.loc[activos, "Sector"]))
    ws = 1 / len(sectores)
    sec = np.array([[1.0 if tabla.loc[a, "Sector"] == s else 0.0 for a in activos] for s in sectores])
    k = sec.sum(axis=1)
    if (k * piso > ws + 1e-9).any():
        return None
    ub = np.array([ws - piso * (k[sectores.index(tabla.loc[a, "Sector"])] - 1) for a in activos])
    lb = np.full(len(activos), piso)
    hr = np.array([1.0 if bool(tabla.loc[a, "Alto riesgo"]) else 0.0 for a in activos])
    asia = np.array([1.0 if tabla.loc[a, "Mercado"] in ("Taiwan", "Corea") else 0.0 for a in activos])
    # factibilidad lineal rápida (alto riesgo y Asia) con programación lineal
    lp = linprog(-hr, A_ub=[asia], b_ub=[LIM["max_asia"]], A_eq=sec, b_eq=np.full(len(sectores), ws),
                 bounds=list(zip(lb, ub)), method="highs")
    if not lp.success or -lp.fun < LIM["min_alto_riesgo"] - 1e-9:
        return None
    m, C = mu[activos].values, S.loc[activos, activos].values
    cons = [{"type": "eq", "fun": lambda w, r=r: r @ w - ws} for r in sec] + [
        {"type": "ineq", "fun": lambda w: hr @ w - LIM["min_alto_riesgo"]},
        {"type": "ineq", "fun": lambda w: LIM["max_asia"] - asia @ w}]
    if con_var:
        cons.append({"type": "ineq", "fun": lambda w: SIGMA_MAX_ACC ** 2 - w @ C @ w})
    f = lambda w: -(w @ m - rf) / np.sqrt(w @ C @ w)
    x_eq = sec.T @ (np.full(len(sectores), ws) / k)
    mejor = None
    for x0 in (lp.x, x_eq, 0.5 * (lp.x + x_eq)):
        r = minimize(f, x0, bounds=list(zip(lb, ub)), constraints=cons, method="SLSQP", options={"maxiter": 500, "ftol": 1e-10})
        w = r.x
        ok = (np.abs(sec @ w - ws).max() < 1e-6 and hr @ w >= LIM["min_alto_riesgo"] - 1e-6
              and asia @ w <= LIM["max_asia"] + 1e-6 and (w >= lb - 1e-6).all() and (w <= ub + 1e-6).all()
              and (not con_var or w @ C @ w <= SIGMA_MAX_ACC ** 2 * (1 + 1e-6)))
        if ok and (mejor is None or f(w) < f(mejor)):
            mejor = w
    return None if mejor is None else pd.Series(np.clip(mejor, lb, ub), index=activos)


def evaluar_combinaciones(tabla, sect, mu, S, rf, combos=None, piso=None, con_var=True):
    """Prueba combinaciones de 5 sectores; devuelve [(Sharpe, volatilidad, combinación, pesos)] ordenadas por Sharpe."""
    from itertools import combinations
    combos = combos if combos is not None else list(combinations(sorted(sect), N_SECTORES))
    out = []
    for combo in combos:
        act = [a for s in combo for a in sect[s]]
        if any(a not in mu.index for a in act):
            continue
        w = _optimizar_estructura(tabla, act, mu, S, rf, piso=piso, con_var=con_var)
        if w is None:
            continue
        v = float(np.sqrt(w @ S.loc[act, act].values @ w))
        out.append(((float(w @ mu[act]) - rf) / v, v, tuple(combo), w))
    return sorted(out, key=lambda x: -x[0])


def correlacion_en_caidas(datos, activos, pesos_mercado, anios=VENTANA_ANIOS):
    """Correlaciones de los activos en todo el periodo y solo en los meses en que cae el índice compuesto (USD)."""
    R = datos["R_usd"]
    R = R[R.index > R.index.max() - pd.DateOffset(years=anios)]
    comp = 0
    for m, p in pesos_mercado.items():
        ix = datos["indice_local"].get(m)
        if ix in R.columns:
            comp = comp + R[ix].fillna(0) * p / sum(pesos_mercado.values())
    act = [a for a in activos if a in R.columns]
    total = R[act].corr()
    caidas = R.loc[comp < 0, act].corr() if (comp < 0).sum() >= 6 else total
    tri = caidas.where(~np.eye(len(act), dtype=bool))
    par = tri.stack().idxmax() if tri.notna().any().any() else (None, None)
    return total, caidas, float(tri.max().max()) if tri.notna().any().any() else np.nan, par, int((comp < 0).sum())


def frontera_eficiente(mu, S, rf, puntos=40):
    """Frontera eficiente de Markowitz sin ventas en corto (pesos entre 0 y 1). Devuelve los puntos, el portafolio
    de mínima varianza y el de máximo Sharpe (tangente a la línea del mercado de capitales)."""
    n, m, C = len(mu), mu.values, S.values
    bnds, suma = [(0, 1)] * n, {"type": "eq", "fun": lambda w: w.sum() - 1}
    x0 = np.full(n, 1 / n)
    mv = minimize(lambda w: w @ C @ w, x0, bounds=bnds, constraints=[suma], method="SLSQP", options={"ftol": 1e-12, "maxiter": 500}).x
    ms = minimize(lambda w: -(w @ m - rf) / np.sqrt(w @ C @ w), x0, bounds=bnds, constraints=[suma], method="SLSQP",
                  options={"ftol": 1e-12, "maxiter": 500}).x
    filas, w_prev = [], mv
    for objetivo in np.linspace(mv @ m, m.max(), puntos):
        r = minimize(lambda w: w @ C @ w, w_prev, bounds=bnds, method="SLSQP", options={"ftol": 1e-12, "maxiter": 500},
                     constraints=[suma, {"type": "eq", "fun": lambda w, t=objetivo: w @ m - t}])
        if r.success:
            w_prev = r.x
            filas.append({"Volatilidad": float(np.sqrt(r.x @ C @ r.x)), "Rentabilidad": float(r.x @ m),
                          **{a: float(x) for a, x in zip(mu.index, r.x)}})
    pf = lambda w: {"Volatilidad": float(np.sqrt(w @ C @ w)), "Rentabilidad": float(w @ m),
                    "Sharpe": float((w @ m - rf) / np.sqrt(w @ C @ w)), "Pesos": pd.Series(w, index=mu.index)}
    return {"puntos": pd.DataFrame(filas), "min_varianza": pf(mv), "max_sharpe": pf(ms), "rf": rf}


def portafolio_concentrado(tabla, datos, rf_local):
    """Método anterior (solo para comparar): las 5 mejores de cada mercado y máximo Sharpe con pesos de 10 % a 20 %,
    sin la regla de sectores. Devuelve pesos sobre el fondo total."""
    t = tabla.copy()
    t["Puntaje mercado"] = t["Puntaje de bursatilidad"].where(t["Elegible"])
    t["Puesto"] = t.groupby("Mercado")["Puntaje mercado"].rank(ascending=False, method="first")
    for n in range(CANDIDATOS_POR_MERCADO, int(t["Puesto"].max() or 0) + 1):
        cand = list(t.index[t["Elegible"] & (t["Puesto"] <= n)])
        if len(cand) < POLITICA["min_activos"]:
            continue
        mu, S, rf = insumos(t, datos, rf_local, cand)
        try:
            return pesos_politica(t, mu, S, rf) * ACC
        except ValueError:
            continue
    return None


def seleccionar(consol, indices, datos, con_robustez=True):
    """Ejecuta toda la metodología con los datos hasta datos['fin']. Sin robustez es más rápido (selección diaria)."""
    tabla, rf_local = evaluar_universo(consol, indices, datos)
    sect = sectores_candidatos(tabla)
    if len(sect) < N_SECTORES:
        raise ValueError(f"Solo {len(sect)} sectores tienen al menos {ACTIVOS_POR_SECTOR} empresas que cumplen todos los "
                         f"criterios; se necesitan {N_SECTORES}.")
    cand = [a for s in sect for a in sect[s]]
    tabla["Candidato"] = tabla.index.isin(cand)
    mu, S, rf = insumos(tabla, datos, rf_local, cand)

    res_c = evaluar_combinaciones(tabla, sect, mu, S, rf, con_var=True)
    var_cumple = bool(res_c)
    if not res_c:   # ninguna combinación cumple el VaR: se elige la de menor riesgo entre las que cumplen lo demás
        res_c = sorted(evaluar_combinaciones(tabla, sect, mu, S, rf, con_var=False), key=lambda x: x[1])
    if not res_c:
        raise ValueError("Ninguna combinación de 5 sectores cumple el mínimo de 50 % en alto riesgo y el máximo de 35 % en Asia.")
    from itertools import combinations
    n_comb = len(list(combinations(sect, N_SECTORES)))
    sharpe_b, _, combo, w_fin = res_c[0]

    # Robustez: 3 ventanas × 2 métodos × 3 pisos por activo × 3 tasas = 54 escenarios, sobre las 10 mejores combinaciones
    top = [c for _, _, c, _ in res_c[:6]]
    elegidos, misma = [], 0
    for anios in (VENTANAS_ROBUSTEZ if con_robustez else ()):
        for metodo in ("historica", "mezcla"):
            for piso in (0.03, 0.05, 0.07):
                for drf in (-0.01, 0.0, 0.01):
                    try:
                        m_, S_, r_ = insumos(tabla, datos, rf_local, cand, anios, metodo, drf)
                        r = evaluar_combinaciones(tabla, sect, m_, S_, r_, combos=top, piso=piso, con_var=var_cumple)
                        if r:
                            elegidos.append(set(r[0][3].index))
                            misma += r[0][2] == combo
                    except Exception:
                        pass
    robustez = pd.Series({a: np.mean([a in e for e in elegidos]) if elegidos else np.nan for a in cand}).sort_values(ascending=False)

    sel = list(w_fin.index)
    sel = sorted(sel, key=lambda a: (list(combo).index(tabla.loc[a, "Sector"]), -w_fin[a]))
    w_fin = w_fin[sel]
    S_sel = S.loc[sel, sel]
    sw = S_sel.values @ w_fin.values
    var = float(w_fin @ sw)
    r_acc, s_acc = float(w_fin @ mu[sel]), np.sqrt(var)
    r_p, s_p = ACC * r_acc + PESO_LIQUIDEZ * rf, ACC * s_acc
    fondo = pd.DataFrame({
        "Empresa": tabla.loc[sel, "Empresa"], "Mercado": tabla.loc[sel, "Mercado"], "Sector": tabla.loc[sel, "Sector"],
        "Peso": w_fin * ACC, "Monto (USD)": w_fin * ACC * INVERSION,
        "E(R) anual USD": mu[sel], "Volatilidad anual USD": np.sqrt(np.diag(S_sel)),
        "Contribución al riesgo": w_fin.values * sw / var, "Robustez": robustez.reindex(sel),
    })
    for c in ["Índice local", "Beta local", "Alfa de Jensen", "t del alfa", "Sharpe", "Sharpe del índice",
              "Rentabilidad anual", "Rentabilidad del índice", "PER (Price/Earnings Ratio)", "PER relativo al sector",
              "Q de Tobin (P/VL)", "Q de Tobin relativa al sector", "Dividend yield",
              "ROA (Retorno Activos)", "ROE (Retorno Capital)", "Ratio Liquidez (Current Ratio)", "Endeudamiento",
              "Nivel de salud", "Puntaje de salud", "Criterio ASG", "Puntaje de bursatilidad", "Alto riesgo",
              "Lectura técnica"]:
        fondo[c] = tabla.loc[sel, c] if c in tabla else np.nan
    fondo["Nota ASG"] = notas_asg(tabla.loc[sel]).values

    peso_m = fondo.groupby("Mercado")["Peso"].sum().to_dict()
    corr, corr_caidas, max_corr, par_corr, meses_caida = correlacion_en_caidas(datos, sel, peso_m)
    frontera = {"fondo": frontera_eficiente(mu[sel], S_sel, rf), "candidatas": frontera_eficiente(mu, S, rf)}
    resumen = {"E(R) anual": r_p, "Volatilidad anual": s_p, "Sharpe": (r_p - rf) / s_p,
               "VaR 95 % 1 mes (%)": var_mensual(s_p), "VaR 95 % 1 mes (USD)": INVERSION * var_mensual(s_p), "Rf": rf}
    return {"fin": datos["fin"], "tabla": tabla, "candidatos": cand, "robustez": robustez,
            "robustos": [a for a in sel if robustez.get(a, 0) >= POLITICA["robustez_minima"]],
            "completados": [], "pesos": w_fin * ACC, "fondo": fondo, "resumen": resumen, "rf_local": rf_local,
            "escenarios_validos": len(elegidos), "robustez_combinacion": misma / len(elegidos) if elegidos else np.nan,
            "sectores": list(combo), "sectores_disponibles": sect, "combinaciones_evaluadas": n_comb,
            "combinaciones_factibles": len(res_c), "var_cumple": var_cumple,
            "correlacion": corr, "correlacion_caidas": corr_caidas, "max_correlacion_caidas": max_corr,
            "par_max_correlacion": par_corr, "meses_caida": meses_caida,
            "mu": mu, "S": S, "rf": rf, "frontera": frontera,
            "concentrado": portafolio_concentrado(tabla, datos, rf_local)}


# ----------------------------------------------------------------------------------------------
# Verificación, comparación con índices y desempeño histórico
# ----------------------------------------------------------------------------------------------
def verificar(res, comp=None):
    """Tabla de verificación de la política. `comp`: métricas históricas del fondo y del índice compuesto (opcional)."""
    f, w = res["fondo"], res["pesos"]
    asia = w[f["Mercado"].isin(["Taiwan", "Corea"])].sum()
    ene = w[f["Sector"] == "Energía"].sum()
    alto = w[f["Alto riesgo"].astype(bool)].sum()
    ps = w.groupby(f["Sector"]).sum()
    n_por_sector = f.groupby("Sector").size()
    rob = f["Robustez"].min()
    var_p = res["resumen"]["VaR 95 % 1 mes (%)"]
    vol = res["resumen"]["Volatilidad anual"]
    mc = res.get("max_correlacion_caidas", np.nan)
    filas = [
        ("Enunciado", "Mínimo 50 % del fondo en alto riesgo (β local > 1)", f"{alto:.1%}", alto >= POLITICA["min_alto_riesgo"] - 1e-6),
        ("Enunciado", "Entre 5 y 10 activos", str(len(w)), POLITICA["min_activos"] <= len(w) <= POLITICA["max_activos"]),
        ("Enunciado", "Sin activos alternativos", "solo acciones cotizadas", True),
        ("Enunciado", "Principalmente activos extranjeros", "100 % fuera de Colombia", True),
        ("Política", f"{N_SECTORES} sectores con igual peso", f"{len(ps)} sectores de {ps.min():.1%} a {ps.max():.1%}",
         len(ps) == N_SECTORES and ps.max() - ps.min() < 1e-4),
        ("Política", f"{ACTIVOS_POR_SECTOR} activos por sector", f"{n_por_sector.min()} a {n_por_sector.max()}",
         bool((n_por_sector == ACTIVOS_POR_SECTOR).all())),
        ("Política", f"Mínimo {POLITICA['piso_activo'] * 100:.0f} % por activo", f"{w.min():.1%} – {w.max():.1%}",
         w.min() >= POLITICA["piso_activo"] - 1e-6),
        ("Política", "Taiwán + Corea ≤ 35 %", f"{asia:.1%}", asia <= POLITICA["max_asia"] + 1e-6),
        ("Riesgo", "VaR 95 % a 1 mes ≤ 8 % (N·σ·Z·√t)", f"{var_p:.1%} (USD {INVERSION * var_p:,.0f})".replace(",", "."),
         var_p <= POLITICA["max_var_mensual"] + 1e-6),
        ("Riesgo", "Volatilidad anual (clase 6: 15 % a 25 %)", f"{vol:.1%}",
         True if 0.15 <= vol <= 0.25 else "Informativo"),
        ("Riesgo", f"Correlación entre pares en meses de caída ≤ {POLITICA['max_correlacion_caidas']:.1f} (meta)".replace(".", ","),
         "sin datos" if pd.isna(mc) else f"máxima {mc:.2f}".replace(".", ","),
         True if pd.notna(mc) and mc <= POLITICA["max_correlacion_caidas"] else "Sobre meta"),
    ]
    if comp is not None and "Fondo" in comp and "Índice compuesto" in comp:
        sf, si = comp.loc["Sharpe", "Fondo"], comp.loc["Sharpe", "Índice compuesto"]
        filas.append(("Desempeño", "Sharpe del fondo ≥ Sharpe del índice compuesto (3 años)",
                      f"{sf:.2f} frente a {si:.2f}".replace(".", ","), sf >= si))
    filas += [
        ("ASG", "Energía fósil ≤ 20 %", f"{ene:.1%}", ene <= POLITICA["max_energia"] + 1e-6),
        ("ASG", "Sin armas controvertidas, tabaco ni carbón térmico", "todos los activos", (f["Criterio ASG"] == "Cumple").all()),
        ("Salud financiera", "Todos con nivel Bueno", "todos los activos", (f["Nivel de salud"] == "Bueno").all()),
        ("Bursatilidad", "Sharpe mayor que el de su índice y alfa > 0", "todos los activos",
         bool(((f["Sharpe"] > f["Sharpe del índice"]) & (f["Alfa de Jensen"] > 0)).all())),
        ("Técnico", "Precio sobre media de 200 días y lectura no desfavorable al comprar", "todos los activos",
         bool((f["Lectura técnica"] != TECNICO_EXCLUIDO).all()) if "Lectura técnica" in f else True),
        ("Robustez", "Cada activo en ≥ 80 % de los escenarios", f"mínimo {rob:.0%}",
         True if rob >= POLITICA["robustez_minima"] else "Parcial"),
    ]
    v = pd.DataFrame(filas, columns=["Origen", "Regla", "Valor", "Cumple"])
    v["Cumple"] = v["Cumple"].map(lambda x: x if isinstance(x, str) else ("Sí" if x else "No"))
    v["Valor"] = v["Valor"].str.replace(r"(\d)\.(\d)%", r"\1,\2 %", regex=True).str.replace(r"(\d)%", r"\1 %", regex=True)
    if (v["Cumple"] == "Parcial").any():
        bajos = [a for a in f.index if f.loc[a, "Robustez"] < POLITICA["robustez_minima"]]
        v.loc[v["Cumple"] == "Parcial", "Valor"] = "menor: " + ", ".join(
            f"{a} {f.loc[a, 'Robustez']:.0%}".replace("%", " %") for a in bajos[:3])
    return v


def serie_fondo_diaria(res, datos, anios=VENTANA_ANIOS):
    """Simulación diaria en USD del fondo con los pesos fijos (rebalanceo diario aproximado) y de los índices."""
    d = datos["diario_usd"]
    d = d[d.index > d.index.max() - pd.DateOffset(years=anios)]
    r = d.pct_change(fill_method=None).iloc[1:]
    w = res["pesos"]
    act = [a for a in w.index if a in r.columns]
    rf_d = res["resumen"]["Rf"] / 252
    fondo = (r[act].fillna(0) @ (w[act] / w[act].sum())) * ACC + PESO_LIQUIDEZ * rf_d
    out = pd.DataFrame({"Fondo": fondo})
    peso_m = res["fondo"].groupby("Mercado")["Peso"].sum()
    comp = 0
    for m, p in peso_m.items():
        ix = datos["indice_local"][m]
        if ix in r.columns:
            out[NOMBRE_INDICE.get(ix, ix) + " (USD)"] = r[ix]
            comp = comp + r[ix].fillna(0) * p / peso_m.sum()
    out["Índice compuesto"] = comp
    if "^GSPC" in r.columns and "S&P 500 (USD)" not in out:
        out["S&P 500 (USD)"] = r["^GSPC"]
    return out


def metricas(serie: pd.Series, rf_anual: float, ref: pd.Series | None = None):
    s = serie.dropna()
    v = s.std() * np.sqrt(252)
    acum = (1 + s).prod() - 1
    anual = (1 + acum) ** (252 / len(s)) - 1 if len(s) else np.nan
    eq = (1 + s).cumprod()
    out = {"Rentabilidad anual": anual, "Volatilidad anual": v, "Sharpe": (anual - rf_anual) / v if v else np.nan,
           "Máxima caída": (eq / eq.cummax() - 1).min(),
           "VaR 95 % 1 mes (USD)": INVERSION * v / np.sqrt(12) * norm.ppf(0.95)}
    if ref is not None:
        z = pd.concat([s, ref], axis=1).dropna()
        beta = np.cov(z.iloc[:, 0], z.iloc[:, 1])[0, 1] / np.var(z.iloc[:, 1], ddof=1)
        out["Beta frente al índice compuesto"] = beta
        out["Treynor"] = (anual - rf_anual) / beta if beta else np.nan
        dif = z.iloc[:, 0] - z.iloc[:, 1]
        te = dif.std() * np.sqrt(252)
        r_ref = (1 + z.iloc[:, 1]).prod() ** (252 / len(z)) - 1
        out["Tracking error"] = te
        out["Information ratio"] = (anual - r_ref) / te if te > 1e-9 else np.nan
    return out


def clase_riesgo(vol: float) -> int:
    """Clase de riesgo de 1 a 7 por volatilidad anual (escala SRRI de los fondos europeos UCITS)."""
    cortes = [0.005, 0.02, 0.05, 0.10, 0.15, 0.25]
    return int(np.searchsorted(cortes, vol, side="right") + 1) if pd.notna(vol) else 0


def nombre_corto(nombre: str, largo: int = 30) -> str:
    """Quita la forma jurídica para que el nombre quepa en las tablas."""
    import re
    s = re.sub(r",?\s+(Inc\.?|Incorporated|Corporation|Corp\.?|Co\.,?\s*Ltd\.?|Company Limited|Ltd\.?|Limited|plc|N\.V\.|S\.A\.|"
               r"Holdings?|Group|Company|Co\.)$", "", str(nombre).strip(), flags=re.I)
    s = re.sub(r",?\s+(Inc\.?|Corporation|Corp\.?|Co\.,?\s*Ltd\.?|Ltd\.?|Holdings?)$", "", s, flags=re.I)
    s = s.replace("The ", "", 1) if s.startswith("The ") else s
    s = s.replace("Taiwan Semiconductor Manufacturing", "TSMC")
    return s if len(s) <= largo else s[: largo - 1] + "…"


def rentabilidad_por_periodos(serie: pd.Series):
    """Rentabilidad efectiva anual y volatilidad por periodo, como en las fichas técnicas."""
    s = serie.dropna()
    fin = s.index.max()
    periodos = {"Último mes": fin - pd.DateOffset(months=1), "Últimos 6 meses": fin - pd.DateOffset(months=6),
                "Año corrido": pd.Timestamp(year=fin.year, month=1, day=1) - pd.Timedelta(days=1),
                "Último año": fin - pd.DateOffset(years=1), "Últimos 2 años": fin - pd.DateOffset(years=2),
                "Últimos 3 años": fin - pd.DateOffset(years=3)}
    filas = {}
    for k, ini in periodos.items():
        x = s[s.index > ini]
        if len(x) < 5:
            filas[k] = {"Rentabilidad E.A.": np.nan, "Rentabilidad del periodo": np.nan, "Volatilidad": np.nan}
            continue
        dias = (x.index.max() - ini).days
        acum = (1 + x).prod() - 1
        filas[k] = {"Rentabilidad E.A.": (1 + acum) ** (365 / dias) - 1, "Rentabilidad del periodo": acum,
                    "Volatilidad": x.std() * np.sqrt(252)}
    return pd.DataFrame(filas)


def tecnico(p: pd.Series):
    p = p.dropna()
    if len(p) < 260:
        return {"Lectura técnica": "Sin datos"}
    sma50, sma200 = p.rolling(50).mean(), p.rolling(200).mean()
    dlt = p.diff()
    up = dlt.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-dlt.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn)
    macd = p.ewm(span=12, adjust=False).mean() - p.ewm(span=26, adjust=False).mean()
    senal = macd.ewm(span=9, adjust=False).mean()
    a52 = p.iloc[-252:]
    ult = p.iloc[-1]
    s = {"Precio > media 200": bool(ult > sma200.iloc[-1]), "Media 50 > media 200": bool(sma50.iloc[-1] > sma200.iloc[-1]),
         "MACD > señal": bool(macd.iloc[-1] > senal.iloc[-1]), "RSI 14": float(rsi.iloc[-1]),
         "Distancia al máximo 52 semanas": float(ult / a52.max() - 1),
         "Fibonacci 61,8 %": float(a52.max() - 0.618 * (a52.max() - a52.min()))}
    s["RSI en zona de compra"] = bool(RSI_RANGO[0] <= s["RSI 14"] <= RSI_RANGO[1])
    n = s["Media 50 > media 200"] + s["MACD > señal"] + s["RSI en zona de compra"]
    if not s["Precio > media 200"]:
        s["Lectura técnica"] = "Desfavorable"
    else:
        s["Lectura técnica"] = "Favorable" if n >= 2 else ("Neutral" if n == 1 else "Desfavorable")
    return s


def fecha_rebalanceo(hoy: pd.Timestamp, indice: pd.DatetimeIndex) -> pd.Timestamp:
    """Último día hábil con datos del mes anterior a `hoy` (rebalanceo mensual)."""
    corte = pd.Timestamp(year=hoy.year, month=hoy.month, day=1) - pd.Timedelta(days=1)
    previos = indice[indice <= corte]
    return previos.max() if len(previos) else indice.min()


def comparar_oficial_hoy(oficial, hoy, datos_hoy):
    """Pesos actuales del portafolio oficial (por movimiento de precios) frente a la selección sugerida hoy."""
    d = datos_hoy["diario_usd"]
    w0 = oficial["pesos"]
    p0 = d.loc[d.index <= oficial["fin"]].iloc[-1]
    p1 = d.iloc[-1]
    crec = (p1[w0.index] / p0[w0.index]).fillna(1.0)
    valor = w0 * crec
    w_hoy_oficial = valor / (valor.sum() + PESO_LIQUIDEZ)
    todos = list(dict.fromkeys(list(w0.index) + list(hoy["pesos"].index)))
    t = pd.DataFrame(index=todos)
    t["Peso oficial"] = w0.reindex(todos).fillna(0)
    t["Peso actual (por precios)"] = w_hoy_oficial.reindex(todos).fillna(0)
    t["Peso sugerido hoy"] = hoy["pesos"].reindex(todos).fillna(0)
    t["Desviación"] = t["Peso actual (por precios)"] - t["Peso oficial"]
    tabla_hoy = hoy["tabla"]
    acc = []
    for a in todos:
        en_of, en_hoy = a in w0.index, a in hoy["pesos"].index
        if en_of and not en_hoy:
            motivo = tabla_hoy.loc[a, "Motivo de exclusión"] if a in tabla_hoy.index else ""
            acc.append("Sale" + (f": {motivo}" if motivo else ": ya no está entre los más robustos u óptimos"))
        elif en_hoy and not en_of:
            acc.append("Entra")
        elif abs(t.loc[a, "Desviación"]) > POLITICA["rebalanceo_puntos"]:
            acc.append("Rebalancear peso")
        else:
            acc.append("Mantener")
    t["Acción sugerida"] = acc
    return t
