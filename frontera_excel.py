"""
Excel de la frontera eficiente (entregable 4 del trabajo final: «Excel con los cálculos de frontera eficiente (Sharpe)»).

Se escribe con XlsxWriter: cada celda de cálculo lleva su fórmula y también el resultado ya calculado, de modo que el
archivo se ve completo aunque se abra en una vista previa (correo, Google Drive, celular) que no recalcula.

Hojas:
  Leame               · qué contiene cada hoja, convenciones y cómo usar Solver.
  Parametros          · tasa libre de riesgo, liquidez, valor del fondo, Z, horizonte, comisión y límites de la política.
  Rendimientos        · rendimientos mensuales en USD (activos del fondo y demás empresas que pasaron los filtros).
  Rend_local          · rendimientos mensuales en moneda local de los activos y de sus índices (para la beta del CAPM).
  CAPM                · beta, prima de mercado, CAPM local, ajuste por paridad de tasas, histórica y E(R) del modelo.
  Estadisticas        · rentabilidad y volatilidad históricas, E(R) del modelo, pesos y clasificación de cada activo.
  Covarianzas         · matriz de covarianzas anualizada y matriz de correlaciones.
  Portafolio          · rentabilidad bruta y neta, volatilidad, Sharpe, VaR y verificación de toda la política.
  Frontera            · frontera con los activos del fondo, fila de prueba con Solver configurado y gráfico.
  Frontera_elegibles  · frontera con todas las empresas que pasaron los filtros (si son más que las del fondo).
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
import xlsxwriter
from xlsxwriter.utility import xl_col_to_name as COL
from xlsxwriter.utility import xl_rowcol_to_cell as CELDA

import motor as M

PCT, NUM, N4 = "0.0%;-0.0%;-", "0.00", "0.0000"


def generar(res: dict, datos: dict) -> bytes:
    f = res["fondo"]
    sel = list(f.index)
    n = len(sel)
    tabla, rf_local = res["tabla"], res["rf_local"]
    rf = float(res["rf"])
    w_acc = (res["pesos"][sel] / M.ACC).values.astype(float)

    # Mismos datos que usa el motor (función insumos): ventana de VENTANA_ANIOS años, meses completos
    Ru, Rl = datos["R_usd"], datos["R_loc"]
    ini = Ru.index.max() - pd.DateOffset(years=M.VENTANA_ANIOS)
    Ru, Rl = Ru[Ru.index > ini], Rl[Rl.index > ini]
    eleg = [a for a in dict.fromkeys(list(tabla.index[tabla["Elegible"]]) + sel)
            if a in Ru.columns and Ru[a].notna().all() and a in Rl.columns and Rl[a].notna().all()]
    eleg = sel + [a for a in eleg if a not in sel]
    misma = res["frontera"].get("mismas_empresas", set(eleg) == set(sel))
    T = len(Ru)
    mercado = {a: tabla.loc[a, "Mercado"] for a in eleg}
    ix_de = {a: datos["indice_local"][mercado[a]] for a in eleg}
    indices = list(dict.fromkeys(ix_de.values()))

    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "nan_inf_to_errors": True})
    base = {"font_name": "Arial", "font_size": 10}
    fm = lambda **k: wb.add_format({**base, **k})
    TIT = fm(bold=True, font_size=13, font_color="#1D5F78")
    NEG = fm(bold=True)
    TXT = fm()
    CAB = fm(bold=True, font_color="#FFFFFF", bg_color="#1D5F78", align="center", valign="vcenter", text_wrap=True, border=1)
    IN_P = fm(font_color="#0000FF", num_format=PCT)
    IN_N = fm(font_color="#0000FF", num_format=N4)
    IN_T = fm(font_color="#0000FF")
    IN_PY = fm(font_color="#0000FF", num_format=PCT, bg_color="#FFF2CC")
    F_P = fm(num_format=PCT)
    F_N = fm(num_format=NUM)
    F_4 = fm(num_format=N4)
    F_5 = fm(num_format="0.00000")
    F_M = fm(num_format="#,##0")
    V_P = fm(font_color="#008000", num_format=PCT)
    MES = fm(num_format="mmm-yyyy", font_color="#0000FF")
    RES = fm(bold=True, num_format=PCT, bg_color="#FFF2CC")
    RES_N = fm(bold=True, num_format=NUM, bg_color="#FFF2CC")

    # ------------------------------------------------------------------ Leame
    ws = wb.add_worksheet("Leame")
    ws.set_column("A:A", 135)
    lineas = [
        (f"{M.NOMBRE_FONDO} · Frontera eficiente de Markowitz", TIT),
        (f"Datos al {pd.Timestamp(res['fin']).strftime('%d/%m/%Y')} (fecha de selección del portafolio oficial) · rendimientos "
         f"mensuales de los últimos {M.VENTANA_ANIOS} años ({T} meses) · fuente: Yahoo Finance.", TXT),
        ("El archivo guarda las fórmulas y también sus resultados: se ve completo aunque se abra en una vista previa que no recalcula.", TXT),
        ("", TXT),
        ("Hojas", NEG),
        ("Parametros: tasa libre de riesgo, liquidez, valor del fondo, Z al 95 %, horizonte del VaR, comisión y límites de la política.", TXT),
        (f"Rendimientos: rendimientos mensuales en USD de los {n} activos del fondo"
         + ("" if misma else f" y de las demás {len(eleg) - n} empresas que pasaron todos los filtros") + ".", TXT),
        ("Rend_local: rendimientos mensuales en moneda local de los activos y de su índice (S&P 500, TAIEX o KOSPI), para la beta.", TXT),
        ("CAPM: beta local = PENDIENTE(activo; índice), prima de mercado, CAPM local, ajuste por paridad de tasas, histórica y E(R).", TXT),
        ("Estadisticas: rentabilidad y volatilidad históricas, E(R) del modelo (vínculo a CAPM), pesos y clasificación de cada activo.", TXT),
        ("Covarianzas: matriz de covarianzas anualizada (muestral × 12) y matriz de correlaciones.", TXT),
        ("Portafolio: rentabilidad bruta y neta de comisión, volatilidad, Sharpe, VaR y verificación de toda la política.", TXT),
        ("Frontera: portafolios de mínima varianza para cada nivel de rentabilidad (sin ventas en corto), fila de prueba para "
         "Solver y gráfico.", TXT),
        ("Frontera_elegibles: la misma frontera con todas las empresas que pasaron los filtros." if not misma else
         "Frontera_elegibles: no se incluye porque solo los activos del fondo pasaron todos los filtros (las dos fronteras coinciden).", TXT),
        ("", TXT),
        ("Convenciones de color", NEG),
        ("Azul: datos de entrada (rendimientos, tasas, pesos). Negro: fórmulas. Verde: vínculos a otra hoja. Amarillo: resultados clave.", TXT),
        ("", TXT),
        ("E(R) del modelo", NEG),
        ("½ rentabilidad histórica en USD + ½ CAPM. CAPM local = Rf local + β local × (rentabilidad media del índice local − Rf "
         "local); se lleva a USD sumando (Rf de EE. UU. − Rf local), por paridad de tasas. La mitad histórica proviene de los "
         "mismos años con que se escogieron las empresas, así que hereda parte del sesgo de selección.", TXT),
        ("Las rentabilidades históricas muy altas (por ejemplo, de Micron o TSMC) reflejan el ciclo de semiconductores e IA de "
         "estos años; el CAPM modera esa cifra en la E(R) del modelo.", TXT),
        ("", TXT),
        ("Solver", NEG),
        ("La hoja Frontera tiene una fila «Prueba con Solver» con el modelo ya configurado: objetivo = Sharpe (máximo), "
         "cambiando los pesos de esa fila, con suma de pesos = 1 y pesos ≥ 0.", TXT),
        ("Datos → Solver → Resolver. Para un punto de la frontera: objetivo = volatilidad (mínimo) y agregue la restricción "
         "rentabilidad = valor objetivo. Con LibreOffice use Herramientas → Solver con los mismos datos.", TXT),
        ("", TXT),
        ("El fondo no queda sobre la frontera porque la política fija 5 sectores con igual peso (19 % cada uno), mínimo 5 % por "
         "activo, ≥ 50 % en acciones con β > 1, Asia ≤ 35 % y VaR ≤ 8 %. La distancia es el costo, en Sharpe, de diversificar.", TXT),
    ]
    for i, (t, fmt_) in enumerate(lineas):
        ws.write(i, 0, t, fmt_)

    # ------------------------------------------------------------------ Parametros
    wp = wb.add_worksheet("Parametros")
    wp.write("A1", "Parámetros", TIT)
    wp.write_row("A2", ["Parámetro", "Valor", "Fuente"], CAB)
    z = float(M.Z_95)
    params = [  # (texto, valor o (fórmula, valor), formato, fuente)
        ("Tasa libre de riesgo (USD, anual)", rf, IN_P, "T-bill de EE. UU. a 3 meses (^IRX, Yahoo Finance)"),
        ("Liquidez del fondo", M.PESO_LIQUIDEZ, IN_P, "Política del fondo"),
        ("Parte invertida en acciones", ("=1-B4", M.ACC), F_P, "Fórmula"),
        ("Valor del fondo (USD)", M.INVERSION, fm(font_color="#0000FF", num_format="#,##0"), "Supuesto del ejercicio"),
        ("Z al 95 %", ("=NORMSINV(0.95)", z), F_4, "Fórmula"),
        ("Horizonte del VaR (años)", ("=1/12", 1 / 12), F_4, "1 mes"),
        ("Límite de VaR (fracción del fondo)", M.POLITICA["max_var_mensual"], IN_P, "Política del fondo"),
        ("Comisión de administración (E.A.)", M.COMISION, IN_P, "Reglamento del fondo"),
        ("Mínimo en acciones con β > 1", M.POLITICA["min_alto_riesgo"], IN_P, "Enunciado del trabajo final"),
        ("Máximo en Taiwán + Corea", M.POLITICA["max_asia"], IN_P, "Política del fondo"),
        ("Mínimo de activos", M.POLITICA["min_activos"], IN_T, "Enunciado del trabajo final"),
        ("Máximo de activos", M.POLITICA["max_activos"], IN_T, "Enunciado del trabajo final"),
        ("Peso mínimo por activo (fondo total)", M.POLITICA["piso_activo"], IN_P, "Política del fondo"),
    ]
    for i, (k, v, fmt_, src) in enumerate(params, start=2):
        wp.write(i, 0, k, TXT)
        if isinstance(v, tuple):
            wp.write_formula(i, 1, v[0], fmt_, v[1])
        else:
            wp.write(i, 1, v, fmt_)
        wp.write(i, 2, src, TXT)
    wp.set_column("A:A", 38)
    wp.set_column("B:B", 14)
    wp.set_column("C:C", 50)
    RF, LIQ, ACC, NV, Z, TH, VMAX, COM, MINHR, MAXAS, MINN, MAXN, PISO = (f"Parametros!$B${r}" for r in range(3, 16))

    # ------------------------------------------------------------------ Rendimientos (USD)
    wr = wb.add_worksheet("Rendimientos")
    wr.write(0, 0, "Mes", CAB)
    wr.write_row(0, 1, eleg, CAB)
    for i, (fecha, fila) in enumerate(Ru[eleg].iterrows(), start=1):
        wr.write_datetime(i, 0, pd.Timestamp(fecha).to_pydatetime(), MES)
        for j, a in enumerate(eleg, start=1):
            wr.write_number(i, j, float(fila[a]), IN_P)
    wr.set_column(0, 0, 11)
    rng_u = {a: f"Rendimientos!${COL(j)}$2:${COL(j)}${T + 1}" for j, a in enumerate(eleg, start=1)}

    # ------------------------------------------------------------------ Rend_local (moneda local)
    wl = wb.add_worksheet("Rend_local")
    cols_l = eleg + indices
    wl.write(0, 0, "Mes", CAB)
    wl.write_row(0, 1, cols_l, CAB)
    for i, (fecha, fila) in enumerate(Rl[cols_l].iterrows(), start=1):
        wl.write_datetime(i, 0, pd.Timestamp(fecha).to_pydatetime(), MES)
        for j, a in enumerate(cols_l, start=1):
            v = fila[a]
            if pd.notna(v):
                wl.write_number(i, j, float(v), IN_P)
    wl.set_column(0, 0, 11)
    rng_l = {a: f"Rend_local!${COL(j)}$2:${COL(j)}${len(Rl) + 1}" for j, a in enumerate(cols_l, start=1)}

    # ------------------------------------------------------------------ CAPM
    wc = wb.add_worksheet("CAPM")
    wc.write("A1", "Rentabilidad esperada del modelo: ½ histórica en USD + ½ CAPM local llevado a USD", TIT)
    cab = ["Ticker", "Mercado", "Índice local", "Rf local", "Rf USD", "β local", "Rentabilidad media del índice local",
           "Prima de mercado local", "CAPM local", "Ajuste por paridad de tasas", "CAPM en USD", "Rentabilidad histórica USD",
           "E(R) del modelo"]
    wc.write_row(2, 0, cab, CAB)
    wc.set_row(2, 42)
    mu_xl = {}
    for k, a in enumerate(eleg):
        r = 3 + k
        m, ix = mercado[a], ix_de[a]
        rfl = float(rf_local[m])
        wc.write(r, 0, a, NEG)
        wc.write(r, 1, m, TXT)
        wc.write(r, 2, M.NOMBRE_INDICE.get(ix, ix), TXT)
        if m == "EEUU":
            wc.write_formula(r, 3, f"={RF}", V_P, rfl)
        else:
            wc.write(r, 3, rfl, IN_P)
        wc.write_formula(r, 4, f"={RF}", V_P, rf)
        x, y = Rl[ix], Rl[a]
        ok = x.notna() & y.notna()
        beta = float(np.cov(y[ok], x[ok])[0, 1] / np.var(x[ok], ddof=1))
        media_ix = float(Rl[ix].mean() * 12)
        capm_l = rfl + beta * (media_ix - rfl)
        capm_u = capm_l + (rf - rfl)
        hist = float(Ru[a].mean() * 12)
        mu_xl[a] = (hist + capm_u) / 2
        f1 = r + 1
        wc.write_formula(r, 5, f"=SLOPE({rng_l[a]},{rng_l[ix]})", F_N, beta)
        wc.write_formula(r, 6, f"=AVERAGE({rng_l[ix]})*12", F_P, media_ix)
        wc.write_formula(r, 7, f"=G{f1}-D{f1}", F_P, media_ix - rfl)
        wc.write_formula(r, 8, f"=D{f1}+F{f1}*H{f1}", F_P, capm_l)
        wc.write_formula(r, 9, f"=E{f1}-D{f1}", F_P, rf - rfl)
        wc.write_formula(r, 10, f"=I{f1}+J{f1}", F_P, capm_u)
        wc.write_formula(r, 11, f"=AVERAGE({rng_u[a]})*12", F_P, hist)
        wc.write_formula(r, 12, f"=(K{f1}+L{f1})/2", RES, mu_xl[a])
    wc.set_column("A:C", 12)
    wc.set_column("D:M", 13)
    wc.write(4 + len(eleg), 0, "La beta (pendiente) no cambia si a ambos rendimientos se les resta la misma tasa libre de riesgo "
                               "mensual, por eso se calcula directamente con los rendimientos.", TXT)
    capm_ref = {a: f"CAPM!$M${4 + k}" for k, a in enumerate(eleg)}
    mu_arr = np.array([mu_xl[a] for a in sel])

    # ------------------------------------------------------------------ Estadisticas
    we = wb.add_worksheet("Estadisticas")
    cab = ["Ticker", "Empresa", "Sector", "Mercado", "Rentabilidad histórica anual", "Volatilidad anual", "E(R) del modelo",
           "Peso en acciones", "Peso en el fondo", "Sharpe individual", "β > 1 (1 = sí)", "Asia (1 = sí)"]
    we.write_row(0, 0, cab, CAB)
    we.set_row(0, 30)
    vol_h = {}
    for i, a in enumerate(sel, start=1):
        r1 = i + 1
        vol_h[a] = float(Ru[a].std() * np.sqrt(12))
        we.write(i, 0, a, NEG)
        we.write(i, 1, f.loc[a, "Empresa"], TXT)
        we.write(i, 2, f.loc[a, "Sector"], TXT)
        we.write(i, 3, f.loc[a, "Mercado"], TXT)
        we.write_formula(i, 4, f"=AVERAGE({rng_u[a]})*12", F_P, float(Ru[a].mean() * 12))
        we.write_formula(i, 5, f"=STDEV({rng_u[a]})*SQRT(12)", F_P, vol_h[a])
        we.write_formula(i, 6, f"={capm_ref[a]}", V_P, mu_xl[a])
        we.write(i, 7, float(w_acc[i - 1]), IN_P)
        we.write_formula(i, 8, f"=H{r1}*{ACC}", V_P, float(w_acc[i - 1] * M.ACC))
        we.write_formula(i, 9, f"=(G{r1}-{RF})/F{r1}", F_N, (mu_xl[a] - rf) / vol_h[a])
        we.write(i, 10, 1 if bool(f.loc[a, "Alto riesgo"]) else 0, IN_T)
        we.write(i, 11, 1 if f.loc[a, "Mercado"] in ("Taiwan", "Corea") else 0, IN_T)
    fe = n + 1
    we.write(fe, 6, "Total", NEG)
    we.write_formula(fe, 7, f"=SUM(H2:H{fe})", F_P, float(w_acc.sum()))
    we.write_formula(fe, 8, f"=SUM(I2:I{fe})", F_P, float(w_acc.sum() * M.ACC))
    for c_, wdt in zip("ABCDEFGHIJKL", (11, 34, 20, 9, 14, 12, 12, 12, 12, 12, 10, 10)):
        we.set_column(f"{c_}:{c_}", wdt)
    MU = f"Estadisticas!$G$2:$G${fe}"
    W = f"Estadisticas!$H$2:$H${fe}"
    WF = f"Estadisticas!$I$2:$I${fe}"

    # ------------------------------------------------------------------ Covarianzas
    wv = wb.add_worksheet("Covarianzas")
    wv.write("A1", "Matriz de covarianzas anualizada (muestral × 12)", TIT)
    wv.write(1, 0, "", CAB)
    wv.write_row(1, 1, sel, CAB)
    C = Ru[sel].cov().values * 12
    for i, a in enumerate(sel):
        wv.write(2 + i, 0, a, NEG)
        for j, b in enumerate(sel):
            wv.write_formula(2 + i, 1 + j, f"=COVAR({rng_u[a]},{rng_u[b]})*COUNT({rng_u[a]})/(COUNT({rng_u[a]})-1)*12",
                             F_4, float(C[i, j]))
    COV = f"Covarianzas!$B$3:${COL(n)}${n + 2}"
    f0 = n + 4
    wv.write(f0, 0, "Matriz de correlaciones", TIT)
    wv.write(f0 + 1, 0, "", CAB)
    wv.write_row(f0 + 1, 1, sel, CAB)
    Rc = Ru[sel].corr().values
    for i, a in enumerate(sel):
        wv.write(f0 + 2 + i, 0, a, NEG)
        for j, b in enumerate(sel):
            wv.write_formula(f0 + 2 + i, 1 + j, f"=CORREL({rng_u[a]},{rng_u[b]})", F_N, float(Rc[i, j]))
    wv.set_column(0, n, 11)

    # ------------------------------------------------------------------ Portafolio
    wq = wb.add_worksheet("Portafolio")
    wq.write("A1", "Indicadores del fondo y verificación de la política", TIT)
    wq.write_row(1, 0, ["Indicador", "Valor", "Fórmula / regla", "¿Cumple?"], CAB)
    r_acc = float(w_acc @ mu_arr)
    var_acc = float(w_acc @ C @ w_acc)
    s_acc = float(np.sqrt(var_acc))
    e_f = M.ACC * r_acc + (1 - M.ACC) * rf
    s_f = M.ACC * s_acc
    var_p = s_f * z * np.sqrt(1 / 12)
    alto = float((w_acc * M.ACC * f["Alto riesgo"].astype(bool).astype(int).values).sum())
    asia = float((w_acc * M.ACC * f["Mercado"].isin(["Taiwan", "Corea"]).astype(int).values).sum())
    filas = [  # (texto, fórmula, valor, formato, explicación, regla de cumplimiento o None, valor de la regla)
        ("Rentabilidad esperada de la parte en acciones", f"=SUMPRODUCT({W},{MU})", r_acc, F_P, "Σ wi·E(Ri)", None, None),
        ("Varianza de la parte en acciones", f"=SUMPRODUCT(MMULT({COV},{W}),{W})", var_acc, F_5, "Σ Σ wi·wj·σij = w'Σw", None, None),
        ("Volatilidad de la parte en acciones", "=SQRT(B4)", s_acc, F_P, "√varianza", None, None),
        ("Rentabilidad esperada del fondo (bruta)", f"={ACC}*B3+(1-{ACC})*{RF}", e_f, RES, "95 % acciones + 5 % liquidez a Rf", None, None),
        ("Rentabilidad esperada neta de comisión", f"=(1+B6)/(1+{COM})-1", (1 + e_f) / (1 + M.COMISION) - 1, RES,
         "(1 + bruta) / (1 + comisión) − 1", None, None),
        ("Volatilidad del fondo", f"={ACC}*B5", s_f, RES, "La liquidez no tiene volatilidad", None, None),
        ("Sharpe del fondo (bruto)", f"=(B6-{RF})/B8", (e_f - rf) / s_f, RES_N, "(E(Rp) − Rf) / σp", None, None),
        ("VaR 95 % a 1 mes (fracción del fondo)", f"=B8*{Z}*SQRT({TH})", var_p, RES, "σ · Z · √t", f'=IF(B10<={VMAX},"Sí","No")',
         var_p <= M.POLITICA["max_var_mensual"] + 1e-9),
        ("VaR 95 % a 1 mes (USD)", f"={NV}*B10", M.INVERSION * var_p, F_M, "N · σ · Z · √t", None, None),
        ("Renta variable (alto riesgo por clase de activo)", f"={ACC}", M.ACC, F_P, "≥ 50 % (enunciado)",
         f'=IF(B12>={MINHR},"Sí","No")', M.ACC >= M.POLITICA["min_alto_riesgo"]),
        ("Acciones con β > 1 (sobre el fondo)", "=SUMPRODUCT(Estadisticas!$I$2:$I${0},Estadisticas!$K$2:$K${0})".format(fe), alto, F_P,
         "≥ 50 % al seleccionar", f'=IF(B13>={MINHR}-0.00001,"Sí","No")', alto >= M.POLITICA["min_alto_riesgo"] - 1e-5),
        ("Taiwán + Corea", "=SUMPRODUCT(Estadisticas!$I$2:$I${0},Estadisticas!$L$2:$L${0})".format(fe), asia, F_P, "≤ 35 %",
         f'=IF(B14<={MAXAS}+0.00001,"Sí","No")', asia <= M.POLITICA["max_asia"] + 1e-5),
        ("Número de activos", f'=COUNTIF({W},">0")', n, fm(num_format="0"), "Entre 5 y 10 (enunciado)",
         f'=IF(AND(B15>={MINN},B15<={MAXN}),"Sí","No")', M.POLITICA["min_activos"] <= n <= M.POLITICA["max_activos"]),
        ("Peso mínimo por activo (fondo total)", f"=MIN({WF})", float(w_acc.min() * M.ACC), F_P, "≥ 5 %",
         f'=IF(B16>={PISO}-0.00001,"Sí","No")', w_acc.min() * M.ACC >= M.POLITICA["piso_activo"] - 1e-5),
    ]
    for i, (k, form, val, fmt_, txt, regla, ok) in enumerate(filas, start=2):
        wq.write(i, 0, k, TXT)
        wq.write_formula(i, 1, form, fmt_, val)
        wq.write(i, 2, txt, TXT)
        if regla:
            wq.write_formula(i, 3, regla, NEG, "Sí" if ok else "No")
    # pesos por sector (5 sectores con igual peso)
    r0 = len(filas) + 4
    wq.write(r0, 0, "Peso por sector (5 sectores con igual peso)", NEG)
    wq.write_row(r0 + 1, 0, ["Sector", "Peso en el fondo"], CAB)
    sectores = list(dict.fromkeys(f["Sector"]))
    ps = f.groupby("Sector")["Peso"].sum()
    for k, s_ in enumerate(sectores):
        wq.write(r0 + 2 + k, 0, s_, TXT)
        wq.write_formula(r0 + 2 + k, 1, f'=SUMIF(Estadisticas!$C$2:$C${fe},A{r0 + 3 + k},{WF})', F_P, float(ps[s_]))
    rs_ = f"B{r0 + 3}:B{r0 + 2 + len(sectores)}"
    wq.write(r0 + 2 + len(sectores), 0, "¿Todos los sectores pesan igual?", NEG)
    wq.write_formula(r0 + 2 + len(sectores), 1, f'=IF(MAX({rs_})-MIN({rs_})<0.0001,"Sí","No")', NEG,
                     "Sí" if ps.max() - ps.min() < 1e-4 else "No")
    wq.set_column("A:A", 50)
    wq.set_column("B:B", 14)
    wq.set_column("C:C", 34)
    wq.set_column("D:D", 10)

    # ------------------------------------------------------------------ Fronteras
    def hoja_frontera(nombre, activos, mu_vec, cov_ref, Cmat, fr, titulo, extra_puntos, solver):
        wf = wb.add_worksheet(nombre)
        k = len(activos)
        wf.write("A1", titulo, TIT)
        wf.write(1, 1, "E(R) →", fm(italic=True, font_size=9))
        for j, a in enumerate(activos):
            wf.write_formula(1, 2 + j, f"={capm_ref[a]}", V_P, float(mu_vec[j]))
        cS, cR, cV, cSh = 2 + k, 3 + k, 4 + k, 5 + k
        wf.write_row(2, 0, ["Punto", "Tipo"] + activos + ["Suma de pesos", "Rentabilidad", "Volatilidad", "Sharpe"], CAB)
        wl_, wr2 = COL(2), COL(1 + k)
        MU_ROW = f"${wl_}$2:${wr2}$2"
        puntos = list(extra_puntos) + [("Frontera", p[activos].values.astype(float)) for _, p in fr["puntos"].iterrows()]
        filas_tipo = {}
        for q, (tipo, w) in enumerate(puntos):
            i = 3 + q
            w = np.clip(np.asarray(w, dtype=float), 0, None)
            resaltar = tipo != "Frontera"
            fw = IN_PY if resaltar else IN_P
            wf.write(i, 0, q + 1, TXT)
            wf.write(i, 1, tipo, NEG if resaltar else TXT)
            for j in range(k):
                wf.write_number(i, 2 + j, float(w[j]), fw)
            rng = f"{wl_}{i + 1}:{wr2}{i + 1}"
            rr, vv = float(w @ mu_vec), float(np.sqrt(w @ Cmat @ w))
            wf.write_formula(i, cS, f"=SUM({rng})", F_P, float(w.sum()))
            wf.write_formula(i, cR, f"=SUMPRODUCT({rng},{MU_ROW})", F_P, rr)
            wf.write_formula(i, cV, f"=SQRT(SUMPRODUCT(MMULT({rng},{cov_ref}),{rng}))", F_P, vv)
            wf.write_formula(i, cSh, f"=({COL(cR)}{i + 1}-{RF})/{COL(cV)}{i + 1}", F_N, (rr - rf) / vv if vv else 0)
            filas_tipo[tipo] = i
        ult = 3 + len(puntos) - 1
        wf.set_column(1, 1, 26)
        wf.set_column(2, cSh, 11)
        if solver and "Prueba con Solver" in filas_tipo:
            i = filas_tipo["Prueba con Solver"] + 1
            hoja = f"'{nombre}'" if " " in nombre else nombre
            nombres = {
                "solver_adj": f"={hoja}!${wl_}${i}:${wr2}${i}", "solver_opt": f"={hoja}!${COL(cSh)}${i}",
                "solver_typ": "=1", "solver_val": "=0", "solver_num": "=1",
                "solver_lhs1": f"={hoja}!${COL(cS)}${i}", "solver_rel1": "=2", "solver_rhs1": "=1",
                "solver_neg": "=1", "solver_eng": "=1", "solver_ver": "=3", "solver_cvg": "=0.0001", "solver_drv": "=1",
                "solver_est": "=1", "solver_itr": "=2147483647", "solver_nwt": "=1", "solver_pre": "=0.000001",
                "solver_scl": "=1", "solver_sho": "=2", "solver_tim": "=2147483647", "solver_tol": "=0.01",
                "solver_mip": "=2147483647", "solver_nod": "=2147483647", "solver_rbv": "=1", "solver_rlx": "=2",
                "solver_ssz": "=100", "solver_msl": "=2", "solver_lin": "=2",
            }
            for nm, ref in nombres.items():
                wb.define_name(f"{hoja}!{nm}", ref)
            wf.write(ult + 2, 0, "La fila «Prueba con Solver» tiene el modelo de Solver ya configurado (máximo Sharpe, suma de "
                                 "pesos = 1, pesos ≥ 0): Datos → Solver → Resolver.", fm(italic=True))
        # activos individuales para el gráfico
        a0 = ult + 4
        wf.write(a0 - 1, 0, "Activos individuales", TIT)
        wf.write_row(a0, 0, ["Ticker", "", "Volatilidad", "E(R) del modelo"], CAB)
        for q, a in enumerate(activos):
            i = a0 + 1 + q
            wf.write(i, 0, a, TXT)
            wf.write_formula(i, 2, f"=STDEV({rng_u[a]})*SQRT(12)", F_P, float(Ru[a].std() * np.sqrt(12)))
            wf.write_formula(i, 3, f"={capm_ref[a]}", V_P, float(mu_vec[q]))
        ch = wb.add_chart({"type": "scatter", "subtype": "straight"})
        ini_f = 3 + len(extra_puntos)
        ch.add_series({"name": "Frontera eficiente", "categories": [nombre, ini_f, cV, ult, cV],
                       "values": [nombre, ini_f, cR, ult, cR], "line": {"color": "#1D5F78", "width": 2}, "marker": {"type": "none"}})
        ch.add_series({"name": "Activos", "categories": [nombre, a0 + 1, 2, a0 + k, 2], "values": [nombre, a0 + 1, 3, a0 + k, 3],
                       "line": {"none": True}, "marker": {"type": "circle", "size": 6, "fill": {"color": "#5A6F7A"}}})
        for tipo, mk, color in (("Fondo (parte en acciones)", "diamond", "#C08424"), ("Máximo Sharpe", "triangle", "#1D5F78"),
                                ("Mínima varianza", "square", "#1D5F78")):
            if tipo in filas_tipo:
                i = filas_tipo[tipo]
                ch.add_series({"name": tipo, "categories": [nombre, i, cV, i, cV], "values": [nombre, i, cR, i, cR],
                               "line": {"none": True}, "marker": {"type": mk, "size": 10, "fill": {"color": color}}})
        ch.set_title({"name": titulo, "name_font": {"size": 11}})
        ch.set_x_axis({"name": "Volatilidad anual", "num_format": "0%", "min": 0})
        ch.set_y_axis({"name": "Rentabilidad esperada anual", "num_format": "0%"})
        ch.set_legend({"position": "bottom"})
        ch.set_size({"width": 760, "height": 420})
        wf.insert_chart(2, cSh + 2, ch)

    fr = res["frontera"]["fondo"]
    hoja_frontera("Frontera", sel, mu_arr, COV, C, fr, f"Frontera eficiente (sin ventas en corto) con los {n} activos del fondo",
                  [("Mínima varianza", fr["min_varianza"]["Pesos"][sel].values), ("Máximo Sharpe", fr["max_sharpe"]["Pesos"][sel].values),
                   ("Fondo (parte en acciones)", w_acc), ("Prueba con Solver", w_acc)], solver=True)

    if not misma:
        mu_e = np.array([mu_xl[a] for a in eleg])
        C_e = Ru[eleg].cov().values * 12
        fe_ = M.frontera_eficiente(pd.Series(mu_e, index=eleg), pd.DataFrame(C_e, index=eleg, columns=eleg), rf, puntos=30)
        # matriz de covarianzas de todas las elegibles, debajo de la frontera
        wtmp = "Cov_elegibles"
        wk = wb.add_worksheet(wtmp)
        wk.write("A1", "Matriz de covarianzas anualizada de todas las empresas que pasaron los filtros", TIT)
        wk.write(1, 0, "", CAB)
        wk.write_row(1, 1, eleg, CAB)
        for i, a in enumerate(eleg):
            wk.write(2 + i, 0, a, NEG)
            for j, b in enumerate(eleg):
                wk.write_formula(2 + i, 1 + j, f"=COVAR({rng_u[a]},{rng_u[b]})*COUNT({rng_u[a]})/(COUNT({rng_u[a]})-1)*12",
                                 F_4, float(C_e[i, j]))
        wk.set_column(0, len(eleg), 11)
        hoja_frontera("Frontera_elegibles", eleg, mu_e, f"Cov_elegibles!$B$3:${COL(len(eleg))}${len(eleg) + 2}", C_e, fe_,
                      f"Frontera con las {len(eleg)} empresas que pasaron todos los filtros",
                      [("Mínima varianza", fe_["min_varianza"]["Pesos"][eleg].values),
                       ("Máximo Sharpe", fe_["max_sharpe"]["Pesos"][eleg].values),
                       ("Fondo (parte en acciones)", np.concatenate([w_acc, np.zeros(len(eleg) - n)]))], solver=False)

    wb.close()
    return buf.getvalue()
