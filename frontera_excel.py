"""
Excel de la frontera eficiente (entregable 4 del trabajo final: «Excel con los cálculos de frontera eficiente (Sharpe)»).

Hojas:
  Leame         · qué contiene cada hoja y cómo reproducir la frontera con Solver.
  Parametros    · tasa libre de riesgo, liquidez, valor del fondo, Z al 95 % y horizonte del VaR.
  Rendimientos  · rendimientos mensuales en USD de los 10 activos (últimos 3 años, Yahoo Finance).
  Estadisticas  · rentabilidad y volatilidad históricas (fórmulas), E(R) del modelo y pesos del fondo.
  Covarianzas   · matriz de covarianzas anualizada y matriz de correlaciones (fórmulas).
  Portafolio    · rentabilidad, volatilidad, Sharpe y VaR del fondo (fórmulas, VaR = N·σ·Z·√t).
  Frontera      · portafolios de la frontera eficiente (pesos) con su rentabilidad, volatilidad y Sharpe (fórmulas) y gráfico.
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import Reference, ScatterChart, Series
from openpyxl.chart.marker import Marker
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L

import motor as M

AZUL_INPUT = Font(name="Arial", size=10, color="0000FF")
NEGRO = Font(name="Arial", size=10, color="000000")
VERDE = Font(name="Arial", size=10, color="008000")
TIT = Font(name="Arial", size=13, bold=True, color="1D5F78")
CAB = Font(name="Arial", size=10, bold=True, color="FFFFFF")
FONDO_CAB = PatternFill("solid", start_color="1D5F78")
AMARILLO = PatternFill("solid", start_color="FFF2CC")
LINEA = Border(bottom=Side(style="thin", color="BFBFBF"))
PCT, NUM = "0.0%;-0.0%;-", "0.00"


def _cab(ws, fila, textos, col0=1):
    for j, t in enumerate(textos):
        c = ws.cell(fila, col0 + j, t)
        c.font, c.fill, c.alignment = CAB, FONDO_CAB, Alignment(horizontal="center", vertical="center", wrap_text=True)


def generar(res: dict, datos: dict) -> bytes:
    f = res["fondo"]
    sel = list(f.index)
    n = len(sel)
    w_acc = (res["pesos"][sel] / M.ACC).values
    R = datos["R_usd"]
    R = R[R.index > R.index.max() - pd.DateOffset(years=M.VENTANA_ANIOS)][sel].dropna()
    T = len(R)
    mu = res["mu"][sel]
    fr = res["frontera"]["fondo"]
    wb = Workbook()

    # ---------------------------------------------------------------- Leame
    ws = wb.active
    ws.title = "Leame"
    lineas = [
        (f"{M.NOMBRE_FONDO} · Frontera eficiente de Markowitz", TIT),
        (f"Datos al {pd.Timestamp(res['fin']).strftime('%d/%m/%Y')} · rendimientos mensuales en USD de los últimos "
         f"{M.VENTANA_ANIOS} años ({T} meses) · fuente: Yahoo Finance.", NEGRO),
        ("", NEGRO),
        ("Hojas", Font(name="Arial", size=10, bold=True)),
        ("Parametros: tasa libre de riesgo, liquidez, valor del fondo, Z al 95 % y horizonte del VaR (celdas azules editables).", NEGRO),
        ("Rendimientos: rendimientos mensuales en USD de los 10 activos del fondo.", NEGRO),
        ("Estadisticas: rentabilidad y volatilidad históricas anualizadas (fórmulas), E(R) del modelo y pesos del fondo.", NEGRO),
        ("Covarianzas: matriz de covarianzas anualizada (×12) y matriz de correlaciones, calculadas con fórmulas.", NEGRO),
        ("Portafolio: rentabilidad, volatilidad, Sharpe y VaR del fondo. σp² = Σ Σ wi wj σij (SUMPRODUCT y MMULT).", NEGRO),
        ("Frontera: portafolios de mínima varianza para cada nivel de rentabilidad (sin ventas en corto) y gráfico.", NEGRO),
        ("", NEGRO),
        ("Convenciones de color", Font(name="Arial", size=10, bold=True)),
        ("Azul: datos de entrada (precios, E(R) del modelo, pesos). Negro: fórmulas. Verde: vínculos a otra hoja.", NEGRO),
        ("", NEGRO),
        ("E(R) del modelo", Font(name="Arial", size=10, bold=True)),
        ("½ rentabilidad histórica en USD + ½ CAPM local (Rf local + β·prima del índice local) llevado a USD por paridad de tasas.", NEGRO),
        ("", NEGRO),
        ("Cómo reproducir un punto de la frontera con Solver", Font(name="Arial", size=10, bold=True)),
        ("1) En la hoja Frontera, fila de prueba: copie una fila de pesos. 2) Solver → objetivo: celda de volatilidad, mínimo.", NEGRO),
        ("3) Cambiando: las celdas de pesos. 4) Restricciones: suma de pesos = 1, pesos ≥ 0, rentabilidad = valor objetivo.", NEGRO),
        ("Para el máximo Sharpe: objetivo celda Sharpe, máximo, con suma = 1 y pesos ≥ 0.", NEGRO),
        ("", NEGRO),
        ("El fondo no queda sobre la frontera porque la política fija 5 sectores con igual peso (19 % cada uno), mínimo 5 % por "
         "activo, ≥ 50 % en alto riesgo, Asia ≤ 35 % y VaR ≤ 8 %. La distancia es el costo, en Sharpe, de la diversificación.", NEGRO),
    ]
    for i, (t, fnt) in enumerate(lineas, start=1):
        ws.cell(i, 1, t).font = fnt
    ws.column_dimensions["A"].width = 130

    # ---------------------------------------------------------------- Parametros
    wp = wb.create_sheet("Parametros")
    wp["A1"], wp["A1"].font = "Parámetros", TIT
    params = [("Tasa libre de riesgo (USD, anual)", res["rf"], PCT, "T-bill de EE. UU. a 3 meses (^IRX, Yahoo Finance)"),
              ("Liquidez del fondo", M.PESO_LIQUIDEZ, PCT, "Política del fondo"),
              ("Parte invertida en acciones", "=1-B4", PCT, "Fórmula"),
              ("Valor del fondo (USD)", M.INVERSION, "#,##0", "Supuesto del ejercicio"),
              ("Z al 95 %", "=NORMSINV(0.95)", "0.0000", "Fórmula"),
              ("Horizonte del VaR (años)", "=1/12", "0.0000", "1 mes"),
              ("Límite de VaR (fracción del fondo)", M.POLITICA["max_var_mensual"], PCT, "Política del fondo")]
    _cab(wp, 2, ["Parámetro", "Valor", "Fuente"])
    for i, (k, v, fmt, src) in enumerate(params, start=3):
        wp.cell(i, 1, k).font = NEGRO
        c = wp.cell(i, 2, v)
        c.number_format, c.font = fmt, (NEGRO if isinstance(v, str) else AZUL_INPUT)
        if not isinstance(v, str):
            c.fill = AMARILLO
        wp.cell(i, 3, src).font = NEGRO
    wp.column_dimensions["A"].width, wp.column_dimensions["B"].width, wp.column_dimensions["C"].width = 36, 14, 48
    RF, ACC, NV, Z, TH, VMAX = "Parametros!$B$3", "Parametros!$B$5", "Parametros!$B$6", "Parametros!$B$7", "Parametros!$B$8", "Parametros!$B$9"

    # ---------------------------------------------------------------- Rendimientos
    wr = wb.create_sheet("Rendimientos")
    _cab(wr, 1, ["Mes"] + sel)
    for i, (fecha, fila) in enumerate(R.iterrows(), start=2):
        wr.cell(i, 1, pd.Timestamp(fecha).to_pydatetime()).number_format = "mmm-yyyy"
        for j, a in enumerate(sel, start=2):
            c = wr.cell(i, j, float(fila[a]))
            c.number_format, c.font = PCT, AZUL_INPUT
    r0, r1 = 2, T + 1
    col_r = {a: f"Rendimientos!${L(j)}${r0}:${L(j)}${r1}" for j, a in enumerate(sel, start=2)}
    wr.column_dimensions["A"].width = 11

    # ---------------------------------------------------------------- Estadisticas
    we = wb.create_sheet("Estadisticas")
    _cab(we, 1, ["Ticker", "Empresa", "Sector", "Mercado", "Rentabilidad histórica anual", "Volatilidad anual",
                 "E(R) del modelo", "Peso en acciones", "Peso en el fondo", "Sharpe individual (E(R) modelo)"])
    for i, a in enumerate(sel, start=2):
        we.cell(i, 1, a).font = NEGRO
        we.cell(i, 2, f.loc[a, "Empresa"]).font = NEGRO
        we.cell(i, 3, f.loc[a, "Sector"]).font = NEGRO
        we.cell(i, 4, f.loc[a, "Mercado"]).font = NEGRO
        we.cell(i, 5, f"=AVERAGE({col_r[a]})*12").number_format = PCT
        we.cell(i, 6, f"=STDEV({col_r[a]})*SQRT(12)").number_format = PCT
        c = we.cell(i, 7, float(mu[a]))
        c.number_format, c.font = PCT, AZUL_INPUT
        c = we.cell(i, 8, float(w_acc[sel.index(a)]))
        c.number_format, c.font = PCT, AZUL_INPUT
        c = we.cell(i, 9, f"=H{i}*{ACC}")
        c.number_format, c.font = PCT, VERDE
        we.cell(i, 10, f"=(G{i}-{RF})/F{i}").number_format = NUM
    fin_e = n + 1
    we.cell(fin_e + 1, 7, "Total").font = Font(name="Arial", size=10, bold=True)
    we.cell(fin_e + 1, 8, f"=SUM(H2:H{fin_e})").number_format = PCT
    we.cell(fin_e + 1, 9, f"=SUM(I2:I{fin_e})").number_format = PCT
    for col, wdt in zip("ABCDEFGHIJ", (11, 30, 20, 9, 14, 12, 12, 12, 12, 14)):
        we.column_dimensions[col].width = wdt
    MU = f"Estadisticas!$G$2:$G${fin_e}"
    W = f"Estadisticas!$H$2:$H${fin_e}"

    # ---------------------------------------------------------------- Covarianzas y correlaciones
    wc = wb.create_sheet("Covarianzas")
    wc["A1"], wc["A1"].font = "Matriz de covarianzas anualizada (muestral × 12)", TIT
    _cab(wc, 2, [""] + sel)
    for i, a in enumerate(sel, start=3):
        wc.cell(i, 1, a).font = Font(name="Arial", size=10, bold=True)
        for j, b in enumerate(sel, start=2):
            c = wc.cell(i, j, f"=COVAR({col_r[a]},{col_r[b]})*COUNT({col_r[a]})/(COUNT({col_r[a]})-1)*12")
            c.number_format = "0.0000"
    COV = f"Covarianzas!$B$3:${L(n + 1)}${n + 2}"
    f0 = n + 5
    wc.cell(f0 - 1, 1, "Matriz de correlaciones").font = TIT
    _cab(wc, f0, [""] + sel)
    for i, a in enumerate(sel, start=f0 + 1):
        wc.cell(i, 1, a).font = Font(name="Arial", size=10, bold=True)
        for j, b in enumerate(sel, start=2):
            wc.cell(i, j, f"=CORREL({col_r[a]},{col_r[b]})").number_format = NUM
    wc.column_dimensions["A"].width = 11

    # ---------------------------------------------------------------- Portafolio
    wq = wb.create_sheet("Portafolio")
    wq["A1"], wq["A1"].font = "Indicadores del fondo", TIT
    _cab(wq, 2, ["Indicador", "Valor", "Fórmula"])
    filas = [
        ("Rentabilidad esperada de la parte en acciones", f"=SUMPRODUCT({W},{MU})", PCT, "Σ wi·E(Ri)"),
        ("Varianza de la parte en acciones", f"=SUMPRODUCT(MMULT({COV},{W}),{W})", "0.00000", "Σ Σ wi·wj·σij = w'Σw"),
        ("Volatilidad de la parte en acciones", "=SQRT(B4)", PCT, "√varianza"),
        ("Rentabilidad esperada del fondo", f"={ACC}*B3+(1-{ACC})*{RF}", PCT, "95 % acciones + 5 % liquidez a Rf"),
        ("Volatilidad del fondo", f"={ACC}*B5", PCT, "La liquidez no tiene volatilidad"),
        ("Sharpe del fondo", f"=(B6-{RF})/B7", NUM, "(E(Rp) − Rf) / σp"),
        ("VaR 95 % a 1 mes (fracción del fondo)", f"=B7*{Z}*SQRT({TH})", PCT, "σ · Z · √t"),
        ("VaR 95 % a 1 mes (USD)", f"={NV}*B9", "#,##0", "N · σ · Z · √t"),
        ("¿Cumple VaR ≤ 8 %?", f'=IF(B9<={VMAX},"Sí","No")', "@", "Política del fondo"),
    ]
    for i, (k, v, fmt, txt) in enumerate(filas, start=3):
        wq.cell(i, 1, k).font = NEGRO
        c = wq.cell(i, 2, v)
        c.number_format = fmt
        wq.cell(i, 3, txt).font = NEGRO
    wq.column_dimensions["A"].width, wq.column_dimensions["B"].width, wq.column_dimensions["C"].width = 44, 14, 36

    # ---------------------------------------------------------------- Frontera
    wf = wb.create_sheet("Frontera")
    wf["A1"], wf["A1"].font = "Frontera eficiente (sin ventas en corto) con los 10 activos del fondo", TIT
    _cab(wf, 3, ["Punto", "Tipo"] + sel + ["Suma de pesos", "Rentabilidad", "Volatilidad", "Sharpe"])
    wf.cell(2, 2, "E(R) →").font = Font(name="Arial", size=9, italic=True)
    for j in range(n):
        c = wf.cell(2, 3 + j, f"=Estadisticas!G{2 + j}")
        c.number_format, c.font = PCT, VERDE
    cS, cR, cV, cSh = 3 + n, 4 + n, 5 + n, 6 + n
    wl, wr_ = L(3), L(2 + n)
    MU_ROW = f"${wl}$2:${wr_}$2"
    puntos = []
    for _, p in fr["puntos"].iterrows():
        puntos.append(("Frontera", p[sel].values.astype(float)))
    puntos.insert(0, ("Mínima varianza", fr["min_varianza"]["Pesos"][sel].values))
    puntos.insert(1, ("Máximo Sharpe", fr["max_sharpe"]["Pesos"][sel].values))
    puntos.insert(2, ("Fondo (parte en acciones)", w_acc))
    for k, (tipo, w) in enumerate(puntos):
        i = 4 + k
        wf.cell(i, 1, k + 1).font = NEGRO
        wf.cell(i, 2, tipo).font = Font(name="Arial", size=10, bold=tipo != "Frontera")
        for j in range(n):
            c = wf.cell(i, 3 + j, float(max(w[j], 0)))
            c.number_format, c.font = PCT, AZUL_INPUT
        rng = f"{wl}{i}:{wr_}{i}"
        wf.cell(i, cS, f"=SUM({rng})").number_format = PCT
        wf.cell(i, cR, f"=SUMPRODUCT({rng},{MU_ROW})").number_format = PCT
        wf.cell(i, cV, f"=SQRT(SUMPRODUCT(MMULT({rng},{COV}),{rng}))").number_format = PCT
        wf.cell(i, cSh, f"=({L(cR)}{i}-{RF})/{L(cV)}{i}").number_format = NUM
        if tipo != "Frontera":
            for j in range(1, cSh + 1):
                wf.cell(i, j).fill = AMARILLO
    ult = 3 + len(puntos)
    wf.column_dimensions["B"].width = 24
    for j in range(3, cSh + 1):
        wf.column_dimensions[L(j)].width = 11

    # activos individuales (para el gráfico)
    a0 = ult + 3
    wf.cell(a0 - 1, 1, "Activos individuales").font = TIT
    _cab(wf, a0, ["Ticker", "", "Volatilidad", "Rentabilidad"])
    for k, a in enumerate(sel):
        i = a0 + 1 + k
        wf.cell(i, 1, a).font = NEGRO
        wf.cell(i, 3, f"=Estadisticas!F{2 + k}").number_format = PCT
        # rentabilidad esperada del modelo (la que usa la optimización)
        wf.cell(i, 4, f"=Estadisticas!G{2 + k}").number_format = PCT

    ch = ScatterChart()
    ch.title = "Frontera eficiente"
    ch.style = 13
    ch.x_axis.title, ch.y_axis.title = "Volatilidad anual", "Rentabilidad esperada anual"
    ch.x_axis.number_format = ch.y_axis.number_format = "0%"
    ch.height, ch.width = 11, 20
    ini_f = 4 + 3
    s1 = Series(Reference(wf, min_col=cR, min_row=ini_f, max_row=ult), Reference(wf, min_col=cV, min_row=ini_f, max_row=ult),
                title="Frontera eficiente")
    s1.marker = Marker(symbol="none")
    s1.smooth = True
    s2 = Series(Reference(wf, min_col=4, min_row=a0 + 1, max_row=a0 + n), Reference(wf, min_col=3, min_row=a0 + 1, max_row=a0 + n),
                title="Activos")
    s2.marker, s2.graphicalProperties.line.noFill = Marker(symbol="circle", size=6), True
    s3 = Series(Reference(wf, min_col=cR, min_row=6, max_row=6), Reference(wf, min_col=cV, min_row=6, max_row=6), title="Fondo")
    s3.marker, s3.graphicalProperties.line.noFill = Marker(symbol="diamond", size=11), True
    s4 = Series(Reference(wf, min_col=cR, min_row=5, max_row=5), Reference(wf, min_col=cV, min_row=5, max_row=5), title="Máximo Sharpe")
    s4.marker, s4.graphicalProperties.line.noFill = Marker(symbol="triangle", size=10), True
    for s in (s1, s2, s3, s4):
        ch.series.append(s)
    wf.add_chart(ch, f"{L(cSh + 2)}3")

    for hoja in wb.worksheets:
        for fila in hoja.iter_rows():
            for c in fila:
                if c.font is None or c.font.name != "Arial":
                    c.font = Font(name="Arial", size=c.font.size if c.font and c.font.size else 10,
                                  bold=c.font.bold if c.font else False, italic=c.font.italic if c.font else False,
                                  color=c.font.color if c.font else None)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
