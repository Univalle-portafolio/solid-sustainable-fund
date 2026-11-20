"""Genera la ficha técnica del fondo en PDF (formato de la Superintendencia Financiera, secciones 1 a 17 y anexos)."""
from __future__ import annotations

import io
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from fpdf import FPDF

import motor as M

AQUI = os.path.dirname(os.path.abspath(__file__))
def _buscar(nombre):
    """Busca un archivo en fonts/ o en la raíz del repositorio."""
    for ruta in (os.path.join(AQUI, "fonts", nombre), os.path.join(AQUI, nombre)):
        if os.path.exists(ruta):
            return ruta
    raise FileNotFoundError(f"No se encontró {nombre} en fonts/ ni en la raíz del repositorio.")


FUENTE = _buscar("DejaVuSans.ttf")
FUENTE_B = _buscar("DejaVuSans-Bold.ttf")
TINTA, MAR, ARENA, GRIS, LINEA, PEND = (13, 36, 51), (29, 95, 120), (192, 132, 36), (90, 111, 122), (207, 219, 224), (154, 100, 20)

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_larga(f):
    f = pd.Timestamp(f)
    return f"{f.day} de {MESES[f.month - 1]} de {f.year}"


def pct(x, d=1):
    return "n. d." if pd.isna(x) else f"{x * 100:,.{d}f} %".replace(",", "X").replace(".", ",").replace("X", ".")


def num(x, d=2):
    return "n. d." if pd.isna(x) else f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


MERCADO_ES = {"EEUU": "EE. UU.", "Taiwan": "Taiwán", "Corea": "Corea del Sur"}
MONEDA_ES = {"EEUU": "Dólar (USD)", "Taiwan": "Dólar taiwanés (TWD)", "Corea": "Won (KRW)"}


class Ficha(FPDF):
    def __init__(self, fecha, fecha_datos=None):
        super().__init__(format="A4")
        self.fecha = fecha
        self.fecha_datos = fecha_datos if fecha_datos is not None else fecha
        self.add_font("DV", "", FUENTE)
        self.add_font("DV", "B", FUENTE_B)
        self.set_auto_page_break(True, 14)
        self.set_margins(12, 12, 12)

    def header(self):
        self.set_fill_color(*TINTA)
        self.rect(0, 0, 210, 20, "F")
        self.set_xy(12, 6)
        self.set_text_color(255, 255, 255)
        self.set_font("DV", "B", 15)
        self.cell(80, 8, "FICHA TÉCNICA")
        self.set_font("DV", "", 7)
        self.set_xy(12, 13.5)
        self.cell(80, 4, M.ESLOGAN)
        self.set_font("DV", "B", 10)
        self.set_xy(100, 3.8)
        self.cell(98, 5, M.NOMBRE_FONDO, align="R")
        self.set_font("DV", "", 6.8)
        self.set_xy(100, 9.4)
        self.cell(98, 3.6, f"2. Fecha de corte (datos de mercado): {fecha_larga(self.fecha_datos)}", align="R")
        self.set_xy(100, 13.2)
        self.cell(98, 3.6, f"Composición: portafolio seleccionado con datos al {fecha_larga(self.fecha)}", align="R")
        self.set_text_color(*TINTA)
        self.set_y(24)

    def footer(self):
        self.set_y(-11)
        self.set_font("DV", "", 6.5)
        self.set_text_color(*GRIS)
        self.cell(0, 4, f"{M.NOMBRE_FONDO} · Ficha técnica · Página {self.page_no()} · "
                        "Ejercicio académico · Gestión de Portafolios · Universidad del Valle", align="C")

    def espacio(self, alto):
        """Salta de página si el bloque que sigue (título + tabla o gráfico) no cabe completo."""
        if self.get_y() + alto > 282:
            self.add_page()

    def titulo(self, txt, reserva=12):
        self.espacio(reserva)
        self.ln(1.5)
        self.set_font("DV", "B", 8.6)
        self.set_text_color(*MAR)
        self.cell(0, 5, txt.upper(), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*LINEA)
        self.line(12, self.get_y(), 198, self.get_y())
        self.ln(1.2)
        self.set_text_color(*TINTA)

    def parrafo(self, txt, tam=7.6, color=TINTA):
        self.set_font("DV", "", tam)
        self.set_text_color(*color)
        self.multi_cell(0, 3.8, txt, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(*TINTA)

    def tabla(self, cabecera, filas, anchos, alinear=None, tam=7.2):
        alinear = alinear or ["L"] * len(anchos)

        def cab():
            self.set_font("DV", "B", 6.4)
            self.set_text_color(*GRIS)
            for c, w, a in zip(cabecera, anchos, alinear):
                self.cell(w, 4.6, c.upper(), border="B", align=a)
            self.ln()
            self.set_text_color(*TINTA)

        self.espacio(4.6 + 4.4 * min(len(filas), 40))     # la tabla no se parte si cabe en una página
        cab()
        for fila in filas:
            if self.get_y() > 275:
                self.add_page()
                cab()
            negrita = isinstance(fila, tuple) and len(fila) and str(fila[0]).startswith("Total")
            self.set_font("DV", "B" if negrita else "", tam)
            for v, w, a in zip(fila, anchos, alinear):
                self.cell(w, 4.4, str(v), border="B", align=a)
            self.ln()
        self.set_draw_color(*LINEA)

    def kv(self, pares, ancho_k=84, ancho_v=None):
        ancho_v = ancho_v or (186 - ancho_k)
        for k, v in pares:
            self.set_font("DV", "", 7.2)
            self.set_text_color(*GRIS)
            self.cell(ancho_k, 4.4, k, border="B")
            self.set_text_color(*(PEND if str(v).startswith("Pendiente") else TINTA))
            self.set_font("DV", "B" if not str(v).startswith(("No aplica", "Pendiente")) else "", 7.2)
            self.cell(ancho_v, 4.4, str(v), border="B", new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(*TINTA)


def _png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf


def _grafico_evolucion(serie_df, alto=2.3):
    v = (1 + serie_df[["Fondo", "Índice compuesto"] + [c for c in serie_df.columns if c.startswith("S&P")]].fillna(0)).cumprod() * 100_000
    fig, ax = plt.subplots(figsize=(7.2, alto), dpi=200)
    colores = {"Fondo": "#1d5f78", "Índice compuesto": "#c08424"}
    for c in v.columns:
        ax.plot(v.index, v[c], lw=1.6 if c == "Fondo" else 1.0, color=colores.get(c, "#7a8a93"),
                ls="-" if c != "S&P 500 (USD)" else "--", label=c)
    ax.set_ylabel("USD", fontsize=7)
    ax.tick_params(labelsize=6.5)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{x:,.0f}".replace(",", ".")))
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="y", color="#e3e9ec", lw=0.6)
    ax.legend(fontsize=6.5, frameon=False, ncol=3, loc="upper left")
    fig.tight_layout()
    return _png(fig)


def _grafico_frontera(res):
    fr = res["frontera"]
    misma = fr.get("mismas_empresas", False)
    fig, ax = plt.subplots(figsize=(7.2, 3.3), dpi=200)
    pc, pf = fr["candidatas"]["puntos"], fr["fondo"]["puntos"]
    if len(pc) and not misma:
        ax.plot(pc["Volatilidad"], pc["Rentabilidad"], color="#9aa9b1", lw=1.1,
                label=f"Frontera con las {fr.get('n_elegibles', len(pc.columns) - 2)} empresas que pasaron los filtros")
    if len(pf):
        ax.plot(pf["Volatilidad"], pf["Rentabilidad"], color="#1d5f78", lw=1.8, label=f"Frontera con los {len(res['fondo'])} activos del fondo")
    rf, ms = fr["candidatas"]["rf"], fr["candidatas"]["max_sharpe"]
    ymax = max(pc["Rentabilidad"].max() if len(pc) else ms["Rentabilidad"], res["fondo"]["E(R) anual USD"].max()) * 1.1
    x = np.linspace(0, min((ymax - rf) / ms["Sharpe"], ms["Volatilidad"] * 1.8) if ms["Sharpe"] > 0 else ms["Volatilidad"], 20)
    ax.plot(x, rf + ms["Sharpe"] * x, color="#9aa9b1", lw=0.8, ls="--", label="Línea del mercado de capitales")
    f = res["fondo"]
    ax.scatter(f["Volatilidad anual USD"], f["E(R) anual USD"], s=12, color="#5a6f7a", zorder=3, label="Activos del fondo")
    for a, r in f.iterrows():
        ax.annotate(a, (r["Volatilidad anual USD"], r["E(R) anual USD"]), fontsize=5, xytext=(2, 2), textcoords="offset points")
    w = res["pesos"] / res["pesos"].sum()
    s_acc = float(np.sqrt(w @ res["S"].loc[w.index, w.index].values @ w))
    ax.scatter([s_acc], [float(w @ res["mu"][w.index])], marker="D", s=40, color="#c08424", zorder=4, label="Fondo (parte en acciones)")
    mv = fr["fondo"]["min_varianza"]
    ax.scatter([mv["Volatilidad"]], [mv["Rentabilidad"]], marker="s", s=22, color="#1d5f78", zorder=4, label="Mínima varianza")
    msf = fr["fondo"]["max_sharpe"]
    ax.scatter([msf["Volatilidad"]], [msf["Rentabilidad"]], marker="^", s=30, color="#1d5f78", zorder=4, label="Máximo Sharpe")
    ax.set_xlabel("Volatilidad anual (USD)", fontsize=7)
    ax.set_ylabel("Rentabilidad esperada", fontsize=7)
    fmt = matplotlib.ticker.FuncFormatter(lambda v, _: f"{v * 100:.0f} %")
    ax.xaxis.set_major_formatter(fmt)
    ax.yaxis.set_major_formatter(fmt)
    ax.set_xlim(left=0)
    ax.tick_params(labelsize=6.5)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(color="#e3e9ec", lw=0.6)
    fig.subplots_adjust(left=0.09, right=0.98, top=0.97, bottom=0.34)
    ax.legend(fontsize=5.8, frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.2))
    return _png(fig)


def generar(res, serie_df, periodos, comp_indices, verif, oos=None, fecha_datos=None, universo_mercados=None) -> bytes:
    f = res["fondo"]
    rs = res["resumen"]
    pdf = Ficha(res["fin"], fecha_datos if fecha_datos is not None else serie_df.index.max())
    pdf.add_page()
    mercados = list(f.groupby("Mercado")["Peso"].sum().sort_values(ascending=False).index)
    sin_inv = [MERCADO_ES[m] for m in ("EEUU", "Taiwan", "Corea") if universo_mercados and m in universo_mercados and m not in mercados]
    monedas = [{"Taiwan": "dólares taiwaneses (TWD)", "Corea": "wones coreanos (KRW)"}.get(m, m) for m in mercados if m != "EEUU"]

    pdf.titulo("1–5. Información general")
    pdf.kv([("1. Sociedad administradora", "Equipo Gestión de Portafolios · Universidad del Valle (ejercicio académico)"),
            ("3. Nombre del fondo", M.NOMBRE_FORMAL),
            ("4. Gestores", "B. Rendón, C. Estupiñán, S. Barona, C. López y D. Vargas"),
            ("5. Custodio de valores", "No aplica (ejercicio académico)")])

    pdf.titulo("6. Características del FIC y tipos de participación")
    pdf.kv([("6.1 Tipo de FIC", "Abierto, sin pacto de permanencia"),
            ("6.2 Fecha de inicio de operaciones", "30 de octubre de 2026"),
            ("6.3 Valor del FIC", f"USD {M.INVERSION:,.0f}".replace(",", ".")),
            ("6.5 Valor inicial de la unidad / 6.4 unidades", "USD 10,00 / 100.000 unidades"),
            ("6.7 Inversión inicial mínima · 6.8 saldo mínimo", "USD 100 · USD 50"),
            ("6.9 Preaviso para retiro · 6.16 pacto de permanencia", "3 días hábiles · no tiene"),
            ("6.10 Comisión de administración", "2,50 % E.A."),
            ("6.11–6.14 Comisiones de gestión, éxito, entrada y salida", "No aplica"),
            ("6.17 Gastos totales (estimados)", "2,50 % E.A.")])

    vol = rs["Volatilidad anual"]
    pdf.titulo("7–8. Calificación y política de inversión")
    pdf.parrafo(
        "7. Calificación: no aplica (fondo de renta variable). 8. Política: crecimiento del capital a largo plazo con "
        f"acciones de empresas de {M.mercados_texto(mercados)}"
        + (f" (el universo analizado incluye también {' y '.join(sin_inv)}; ninguna de sus empresas quedó en el portafolio)" if sin_inv else "")
        + " que cumplen los criterios ASG (incluido un riesgo ASG no severo según Sustainalytics), tienen salud financiera "
        "buena, superan a su índice local (Sharpe y alfa de Jensen) y, al comprarse, no tienen lectura técnica desfavorable. "
        "Asignación: 5 sectores con igual peso (19 % cada uno) y hasta 2 empresas por sector, ponderadas con Markowitz (máximo "
        "Sharpe) y con mínimo 5 % por activo. Taiwán + Corea ≤ 35 %; energía fósil ≤ 20 %; VaR 95 % a 1 mes ≤ 8 %; 5 % en "
        "liquidez. Sin renta fija, alternativos, derivados ni apalancamiento. "
        f"Alto riesgo: el fondo invierte el {pct(rs['Alto riesgo por clase de activo'], 0)} en renta variable, clase de activo "
        f"de alto riesgo; dentro de las acciones, además, el {pct(rs['Alto riesgo β > 1'])} está en empresas con β > 1, más "
        f"sensibles al mercado (mínimo 50 % al seleccionar). Perfil de riesgo: arriesgado; volatilidad esperada {pct(vol)}, "
        f"clase {M.clase_riesgo(vol)} de 7. "
        + (f"Riesgo cambiario: parte del fondo está en {' y '.join(monedas)}, cuyo valor en USD cambia con la tasa de "
           "cambio. " if monedas else "")
        + f"Revisión {M.REVISION} de la composición: un activo sale si deja de cumplir los criterios fundamentales; los pesos "
        f"vuelven a su objetivo si se desvían más de 3 puntos. Índice de referencia: {M.indices_texto(mercados)} en USD, "
        "ponderados por el peso del fondo en cada país.")

    pdf.titulo(f"9. Evolución de USD 100.000 invertidos hace {M.VENTANA_ANIOS} años (simulación)", reserva=60)
    pdf.image(_grafico_evolucion(serie_df), x=12, w=186)
    pdf.parrafo("Simulación ilustrativa con los pesos actuales: las empresas se seleccionaron con datos de este mismo periodo, "
                "por lo que el resultado sobrestima la rentabilidad que se habría obtenido en la realidad. La prueba fuera de "
                "muestra (anexo C) evalúa el método con datos que no se usaron para escoger las empresas.", 6.4, GRIS)

    pdf.titulo("10–11. Plazos, rentabilidad y volatilidad histórica (simulación)", reserva=36)
    pdf.parrafo("10. Plazos y duración: no aplica (100 % renta variable, sin vencimiento).", 7.2, GRIS)
    cols = list(periodos.columns)
    ref = M.rentabilidad_por_periodos(serie_df["Índice compuesto"]) if "Índice compuesto" in serie_df else None
    filas = [("11.1 Rentabilidad E.A.",) + tuple(pct(periodos.loc["Rentabilidad E.A.", c]) for c in cols),
             ("Rentabilidad del periodo",) + tuple(pct(periodos.loc["Rentabilidad del periodo", c]) for c in cols),
             ("11.2 Volatilidad",) + tuple(pct(periodos.loc["Volatilidad", c]) for c in cols)]
    if ref is not None:
        filas += [("Índice compuesto (E.A.)",) + tuple(pct(ref.loc["Rentabilidad E.A.", c]) for c in cols),
                  ("Índice compuesto (periodo)",) + tuple(pct(ref.loc["Rentabilidad del periodo", c]) for c in cols)]
    pdf.tabla(["Indicador"] + cols, filas, [36] + [25] * len(cols), ["L"] + ["R"] * len(cols))
    pdf.parrafo("Las rentabilidades de plazos menores a un año se expresan en tasa efectiva anual, como exige el formato; una "
                "variación de un mes se amplifica al anualizarse. Las filas «del periodo» muestran la variación efectiva sin "
                "anualizar. Rentabilidades brutas, antes de la comisión de administración.", 6.4, GRIS)

    pdf.add_page()
    pdf.titulo("12. Composición del fondo")
    peso_m = f.groupby("Mercado")["Peso"].sum()
    peso_s = f.groupby("Sector")["Peso"].sum().sort_values(ascending=False)
    pdf.parrafo(f"12.1 Calificación: no aplica. 12.2 Tipo de renta: renta variable {pct(f['Peso'].sum())}, liquidez "
                f"{pct(M.PESO_LIQUIDEZ)}. 12.6 Por activo: inversiones {pct(f['Peso'].sum())}, disponible {pct(M.PESO_LIQUIDEZ)}. "
                "12.7 Exposición a derivados: no tiene.", 7.4)
    pdf.ln(1)
    pdf.tabla(["12.3 Sector", "Peso"], [(s, pct(p)) for s, p in peso_s.items()], [60, 30], ["L", "R"])
    pdf.ln(1)
    pdf.tabla(["12.4 País del emisor", "Peso", "12.5 Moneda"],
              [(MERCADO_ES.get(m, m), pct(p), MONEDA_ES.get(m, m)) for m, p in peso_m.sort_values(ascending=False).items()]
              + [("Liquidez", pct(M.PESO_LIQUIDEZ), "Dólar (USD)")], [60, 30, 60], ["L", "R", "L"])
    if monedas:
        pdf.parrafo(f"Riesgo cambiario: {pct(peso_m.drop('EEUU', errors='ignore').sum())} del fondo está en "
                    f"{' y '.join(monedas)}; su valor en dólares cambia con la tasa de cambio.", 6.4, GRIS)

    pdf.titulo("13. Principales inversiones", reserva=50)
    rango = lambda r: "n. d." if pd.isna(r["Peso mínimo (escenarios)"]) else \
        f"{pct(r['Peso mínimo (escenarios)'], 0)}–{pct(r['Peso máximo (escenarios)'], 0)}".replace(" %–", "–")
    filas = [(M.nombre_corto(r["Empresa"], 26), a, MERCADO_ES.get(r["Mercado"], r["Mercado"]), r["Sector"], pct(r["Peso"]),
              f"{r['Monto (USD)']:,.0f}".replace(",", "."), "Sí" if r["Alto riesgo"] else "No", rango(r)) for a, r in f.iterrows()]
    filas.append(("Total renta variable", "", "", "", pct(f["Peso"].sum()), f"{f['Monto (USD)'].sum():,.0f}".replace(",", "."), "", ""))
    pdf.tabla(["Emisor", "Ticker", "País", "Sector", "Peso", "Monto USD", "β > 1", "Escenarios"], filas,
              [42, 18, 20, 34, 15, 22, 13, 22], ["L", "L", "L", "L", "R", "R", "C", "R"])
    pdf.parrafo(f"Acciones con β > 1: {pct(rs['Alto riesgo β > 1'])} del fondo. «Escenarios»: rango del peso óptimo del activo "
                f"en las {res.get('escenarios_total', 0)} pruebas de robustez.", 6.4, GRIS)

    pdf.titulo("14–17. Vinculadas, gerentes, revisor fiscal y defensor del consumidor", reserva=24)
    pdf.kv([("14. Empresas vinculadas", "No aplica (ejercicio académico)"),
            ("15. Hoja de vida de los gerentes", "Estudiantes de Gestión de Portafolios, Universidad del Valle (equipo gestor)"),
            ("16. Revisor fiscal · 17. Defensor del consumidor", "No aplica (ejercicio académico)")])

    # ------------------------------------------------------------ anexos
    pdf.titulo(f"Anexo A. Cada activo frente a su índice local ({M.VENTANA_ANIOS} años, moneda local)", reserva=60)
    filas = [(a, M.NOMBRE_INDICE.get(r["Índice local"], r["Índice local"]), pct(r["Rentabilidad anual"]), pct(r["Rentabilidad del índice"]),
              num(r["Sharpe"]), num(r["Sharpe del índice"]), num(r["Beta local"]), num(r.get("Beta local 5 años")), pct(r["Alfa de Jensen"]))
             for a, r in f.iterrows()]
    pdf.tabla(["Activo", "Índice", "Rent. activo", "Rent. índice", "Sharpe", "Sharpe índ.", "Beta 3a", "Beta 5a", "Alfa"], filas,
              [22, 20, 22, 22, 18, 20, 18, 18, 26], ["L", "L", "R", "R", "R", "R", "R", "R", "R"])
    pdf.parrafo("Rentabilidades: promedio aritmético de los rendimientos mensuales en moneda local, anualizado (× 12), con la "
                "tasa libre de riesgo de cada país. Por eso difieren de las del anexo B, que son tasas compuestas con precios "
                "diarios en USD.", 6.4, GRIS)

    def tabla_comp(comp):
        cols = list(comp.columns)
        filas = []
        for k in comp.index:
            vals = [(f"{v:,.0f}".replace(",", ".") if "USD" in k else (num(v) if k.startswith(("Sharpe", "Beta", "Treynor", "Information")) else pct(v)))
                    for v in comp.loc[k]]
            filas.append((k,) + tuple(vals))
        w0 = 186 - 50
        pdf.tabla(["Indicador"] + cols, filas, [50] + [w0 / len(cols)] * len(cols), ["L"] + ["R"] * len(cols), tam=6.8)

    pdf.titulo(f"Anexo B. Indicadores del fondo frente a los índices (simulación de {M.VENTANA_ANIOS} años, USD)", reserva=60)
    tabla_comp(comp_indices)
    var_usd = f"{rs['VaR 95 % 1 mes (USD)']:,.0f}".replace(",", ".")
    pdf.parrafo(f"Tasa compuesta anual con precios diarios en USD. El VaR histórico usa la volatilidad observada; el VaR "
                f"esperado del anexo F usa la volatilidad esperada del modelo ({pct(rs['VaR 95 % 1 mes (%)'])}, USD {var_usd}). "
                "Simulación dentro de muestra: sobrestima la rentabilidad.", 6.4, GRIS)

    pdf.titulo("Anexo C. Prueba fuera de muestra", reserva=70)
    if oos is None or oos.get("error"):
        pdf.parrafo("No fue posible armar el portafolio con los datos de octubre de 2023"
                    + (f": {oos['error']}" if oos else "."), 7.2, GRIS)
    else:
        r0 = oos["res"]
        pdf.parrafo(f"Misma metodología con los precios disponibles hasta el {fecha_larga(oos['fecha'])}; el portafolio que "
                    f"resultó ({', '.join(f'{a} {pct(p, 0)}' for a, p in r0['pesos'].items())}) se simuló desde esa fecha "
                    "hasta hoy, con datos que no se usaron para escoger las empresas.", 7.2)
        pdf.image(_grafico_evolucion(oos["serie"], 2.0), x=12, w=186)
        tabla_comp(oos["comp"])
        pdf.parrafo("Limitación: los fundamentales y la lista de empresas del S&P 500 son los de hoy (Yahoo Finance no publica "
                    "su historia), así que la prueba conserva algo de sesgo.", 6.4, GRIS)

    pdf.titulo("Anexo D. Salud financiera, valoración y ASG de los activos", reserva=4.6 + 4.4 * (len(f) + 1) + 14)
    filas = [(a, pct(r["ROA (Retorno Activos)"]), pct(r["ROE (Retorno Capital)"]),
              "n. a." if r["Sector"] == "Servicios financieros" else num(r["Ratio Liquidez (Current Ratio)"]) + "x",
              "n. a." if r["Sector"] == "Servicios financieros" else pct(r["Endeudamiento"]),
              num(r.get("Puntaje de salud")), num(r.get("PER (Price/Earnings Ratio)"), 1), num(r.get("Q de Tobin (P/VL)"), 1),
              pct(r.get("Dividend yield")), r["Nivel de salud"], num(r.get(M.COL_RIESGO_ASG), 1)) for a, r in f.iterrows()]
    pdf.tabla(["Activo", "ROA", "ROE", "Liquidez", "Endeud.", "Puntos", "PER", "Q Tobin", "Div. yield", "Salud", "Riesgo ASG"], filas,
              [20, 15, 15, 16, 16, 14, 15, 15, 17, 18, 25], ["L", "R", "R", "R", "R", "R", "R", "R", "R", "L", "R"], tam=6.8)
    notas = []
    if "WELL" in f.index:
        notas.append("WELL es un fideicomiso inmobiliario (REIT): la depreciación de los edificios reduce su utilidad contable, "
                     "por eso su ROA, ROE y PER se ven débiles; en los REIT se analizan los fondos de operación (FFO).")
    unicos = f.index[(f["Activos en su sector"] == 1) & (f["Elegibles en su sector"] <= 1)]
    if len(unicos):
        notas.append(f"{' y '.join(unicos)}: {'única empresa' if len(unicos) == 1 else 'únicas empresas'} de su sector que "
                     f"{'pasó' if len(unicos) == 1 else 'pasaron'} todos los filtros; "
                     f"{'lleva' if len(unicos) == 1 else 'llevan'} el peso completo del sector.")
    bajas = f.index[f["Beta local"] < 0.3]
    if len(bajas):
        notas.append(f"{', '.join(bajas)}: beta cercana a cero, se mueve poco con el mercado (en defensa pesan la geopolítica "
                     "y los presupuestos militares); aporta diversificación.")
    for a, r in f.iterrows():
        if r["Nota ASG"]:
            notas.append(f"{a} (ASG): {r['Nota ASG']}")
    if notas:
        pdf.parrafo("Puntos: promedio del semáforo de salud (2, 1 o 0 por indicador; nivel Bueno con 1,5 o más). Riesgo ASG: "
                    "ESG Risk Score de Sustainalytics (se excluye 40 o más). " + " ".join(notas), 6.4, GRIS)

    if "frontera" in res:
        pdf.titulo("Anexo E. Frontera eficiente de Markowitz (sin ventas en corto)", reserva=110)
        pdf.image(_grafico_frontera(res), x=12, w=186)
        fr = res["frontera"]["fondo"]
        filas = [(f"Mínima varianza ({len(f)} activos)", pct(fr["min_varianza"]["Rentabilidad"]), pct(fr["min_varianza"]["Volatilidad"]),
                  num((fr["min_varianza"]["Rentabilidad"] - fr["rf"]) / fr["min_varianza"]["Volatilidad"])),
                 (f"Máximo Sharpe ({len(f)} activos, sin política)", pct(fr["max_sharpe"]["Rentabilidad"]),
                  pct(fr["max_sharpe"]["Volatilidad"]), num(fr["max_sharpe"]["Sharpe"])),
                 ("Fondo (con la política) · rentabilidad bruta", pct(rs["E(R) anual"]), pct(rs["Volatilidad anual"]), num(rs["Sharpe"])),
                 ("Fondo · rentabilidad neta de comisión (2,5 %)", pct(rs["E(R) neta de comisión"]), pct(rs["Volatilidad anual"]),
                  num((rs["E(R) neta de comisión"] - rs["Rf"]) / rs["Volatilidad anual"]))]
        pdf.tabla(["Portafolio", "Rentabilidad esperada", "Volatilidad", "Sharpe"], filas, [86, 36, 32, 32], ["L", "R", "R", "R"])
        txt = ("La distancia entre el fondo y el portafolio de máximo Sharpe es el costo de la diversificación exigida por la "
               "política (5 sectores con igual peso, mínimo 5 % por activo, β > 1, Asia y VaR). Las filas del fondo incluyen el "
               "5 % de liquidez; el gráfico muestra solo la parte en acciones.")
        if res["frontera"].get("mismas_empresas"):
            txt += (" Solo estas empresas pasaron todos los filtros en la fecha de selección, así que la frontera con todas las "
                    "elegibles coincide con la del fondo.")
        pdf.parrafo(txt, 6.4, GRIS)

    pdf.titulo("Anexo F. Verificación de la política", reserva=4.6 + 4.4 * (len(verif) + 1))
    pdf.tabla(["Origen", "Regla", "Valor", "Cumple"], [tuple(x) for x in verif.values.tolist()], [25, 93, 52, 16],
              ["L", "L", "L", "C"], tam=6.6)
    pdf.parrafo("«Informativo»: dato que se reporta sin ser una regla obligatoria. La correlación en meses de caída es una meta "
                "de diversificación, no un límite.", 6.4, GRIS)

    pdf.ln(2)
    pdf.parrafo("Advertencia. Este material es para información de los inversionistas y no constituye una oferta ni una solicitud "
                "para comprar o vender valores. Las obligaciones de la sociedad administradora relacionadas con la gestión del "
                "portafolio son de medio y no de resultado. La inversión está sujeta a los riesgos de los activos que componen el "
                "fondo, incluido el riesgo de tasa de cambio. Las rentabilidades históricas son simulaciones con los pesos actuales "
                "sobre empresas escogidas con datos de ese mismo periodo, por lo que sobrestiman la rentabilidad que se habría "
                "obtenido; no garantizan rentabilidades futuras. Ejercicio académico del curso Gestión de Portafolios, "
                "Universidad del Valle.", 6.4, GRIS)
    return bytes(pdf.output())
