"""
Universo de inversión automático del Solid & Sustainable Equity Fund.

  · Estados Unidos: las empresas del S&P 500 (lista vigente, descargada de Wikipedia).
  · Taiwán y Corea del Sur: las mayores empresas de cada bolsa (listas de abajo; se pueden ampliar).
  · Fundamentales, sector e industria de cada empresa: Yahoo Finance.

El resultado se guarda en data/universo.csv. La tarea diaria de GitHub (actualizar_universo.py) lo renueva cada noche.
"""
from __future__ import annotations

import io
import time

import numpy as np
import pandas as pd

URL_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

# Mayores empresas por capitalización de la Bolsa de Taiwán (TWSE) y de Corea (KRX).
TAIWAN = ["2330.TW", "2317.TW", "2454.TW", "2308.TW", "2382.TW", "2881.TW", "2882.TW", "2891.TW", "2412.TW", "3711.TW",
          "2303.TW", "2886.TW", "2884.TW", "1216.TW", "2345.TW", "3231.TW", "6669.TW", "2357.TW", "2885.TW", "2892.TW",
          "5880.TW", "2880.TW", "2883.TW", "2887.TW", "2890.TW", "1301.TW", "1303.TW", "6505.TW", "2002.TW", "2603.TW",
          "2609.TW", "2615.TW", "3008.TW", "2395.TW", "4938.TW", "2379.TW", "3034.TW", "3037.TW", "2327.TW", "3045.TW",
          "4904.TW", "2207.TW", "1101.TW", "2912.TW", "5871.TW", "3661.TW", "3443.TW", "2376.TW", "2301.TW", "3017.TW",
          "2383.TW", "2059.TW"]
COREA = ["005930.KS", "000660.KS", "373220.KS", "207940.KS", "005380.KS", "000270.KS", "068270.KS", "035420.KS", "105560.KS",
         "055550.KS", "012450.KS", "005490.KS", "035720.KS", "006400.KS", "051910.KS", "028260.KS", "012330.KS", "086790.KS",
         "032830.KS", "000810.KS", "015760.KS", "017670.KS", "030200.KS", "033780.KS", "003550.KS", "034730.KS", "096770.KS",
         "010130.KS", "009540.KS", "329180.KS", "042660.KS", "011200.KS", "316140.KS", "138040.KS", "064350.KS", "079550.KS",
         "010140.KS", "034020.KS", "267260.KS", "402340.KS", "066570.KS", "018260.KS", "009150.KS", "011070.KS", "024110.KS",
         "090430.KS", "097950.KS", "004020.KS", "010950.KS", "047810.KS", "352820.KS", "259960.KS", "036570.KS"]

# Índice local y tasa libre de riesgo anual de cada mercado (EE. UU. se reemplaza por el T-bill ^IRX del día)
INDICES = pd.DataFrame({"Mercado": ["EEUU", "Taiwan", "Corea"], "Índice": ["^GSPC", "^TWII", "^KS11"],
                        "Rf usada": [0.0524, 0.015, 0.030]}).set_index("Mercado")

SECTOR_ES = {"Technology": "Tecnología", "Communication Services": "Comunicaciones", "Financial Services": "Servicios financieros",
             "Energy": "Energía", "Healthcare": "Salud", "Consumer Defensive": "Consumo básico",
             "Consumer Cyclical": "Consumo discrecional", "Industrials": "Industria", "Basic Materials": "Materiales",
             "Utilities": "Servicios públicos", "Real Estate": "Inmobiliario"}
GICS_ES = {"Information Technology": "Tecnología", "Communication Services": "Comunicaciones", "Financials": "Servicios financieros",
           "Energy": "Energía", "Health Care": "Salud", "Consumer Staples": "Consumo básico",
           "Consumer Discretionary": "Consumo discrecional", "Industrials": "Industria", "Materials": "Materiales",
           "Utilities": "Servicios públicos", "Real Estate": "Inmobiliario"}

COLUMNAS = ["Mercado", "Empresa", "Sector", "Industria", "Moneda", "Capitalización (USD)", "PER (Price/Earnings Ratio)",
            "ROE (Retorno Capital)", "ROA (Retorno Activos)", "Ratio Liquidez (Current Ratio)", "Ratio Deuda/Capital (Debt/Equity)"]


def lista_sp500() -> pd.DataFrame:
    """Tickers, nombres y sector GICS del S&P 500 (Wikipedia). Los puntos se cambian por guion para Yahoo (BRK.B → BRK-B)."""
    import requests
    html = requests.get(URL_SP500, headers={"User-Agent": "Mozilla/5.0 (fondo academico Univalle)"}, timeout=30).text
    t = next(x for x in pd.read_html(io.StringIO(html)) if {"Symbol", "Security", "GICS Sector"} <= set(x.columns))
    t["Ticker"] = t["Symbol"].astype(str).str.replace(".", "-", regex=False)
    return pd.DataFrame({"Ticker": t["Ticker"], "Empresa": t["Security"], "Sector GICS": t["GICS Sector"]}).set_index("Ticker")


def ficha_yahoo(ticker: str, intentos: int = 3) -> dict | None:
    import yfinance as yf
    for k in range(intentos):
        try:
            info = yf.Ticker(ticker).info
            if info and (info.get("longName") or info.get("shortName")):
                return info
        except Exception:
            pass
        time.sleep(1.5 * (k + 1))
    return None


def construir_universo(progreso=None, pausa: float = 0.25, anterior: str | None = None) -> pd.DataFrame:
    """Arma el universo completo con fundamentales de Yahoo Finance. `progreso(i, n, ticker)` informa el avance.
    Si Wikipedia no responde, usa las empresas de EE. UU. del universo anterior (`anterior`, ruta a universo.csv)."""
    try:
        sp = lista_sp500()
    except Exception:
        sp = pd.DataFrame(columns=["Empresa", "Sector GICS"])
        if anterior:
            try:
                prev = pd.read_csv(anterior, index_col="Ticker")
                prev = prev[prev["Mercado"] == "EEUU"]
                sp = pd.DataFrame({"Empresa": prev["Empresa"], "Sector GICS": ""}, index=prev.index)
            except Exception:
                pass
    tickers = [(t, "EEUU") for t in sp.index] + [(t, "Taiwan") for t in TAIWAN] + [(t, "Corea") for t in COREA]
    moneda = {"EEUU": "USD", "Taiwan": "TWD", "Corea": "KRW"}
    filas = {}
    for i, (t, m) in enumerate(tickers):
        if progreso:
            progreso(i, len(tickers), t)
        info = ficha_yahoo(t)
        if info is None:
            continue
        de = info.get("debtToEquity")
        sector = SECTOR_ES.get(info.get("sector"), None)
        if sector is None and t in sp.index:
            sector = GICS_ES.get(sp.loc[t, "Sector GICS"], "Otros")
        filas[t] = {
            "Mercado": m,
            "Empresa": info.get("longName") or info.get("shortName") or (sp.loc[t, "Empresa"] if t in sp.index else t),
            "Sector": sector or "Otros",
            "Industria": info.get("industry") or "",
            "Moneda": moneda[m],
            "Capitalización (USD)": info.get("marketCap"),
            "PER (Price/Earnings Ratio)": info.get("trailingPE"),
            "ROE (Retorno Capital)": info.get("returnOnEquity"),
            "ROA (Retorno Activos)": info.get("returnOnAssets"),
            "Ratio Liquidez (Current Ratio)": info.get("currentRatio"),
            "Ratio Deuda/Capital (Debt/Equity)": None if de is None else de / 100,   # Yahoo lo reporta en %
        }
        time.sleep(pausa)
    u = pd.DataFrame.from_dict(filas, orient="index")
    u.index.name = "Ticker"
    for c in COLUMNAS[5:]:
        u[c] = pd.to_numeric(u[c], errors="coerce")
    # La capitalización de Taiwán y Corea viene en moneda local: se deja como referencia, no se compara entre mercados.
    return u[COLUMNAS]
