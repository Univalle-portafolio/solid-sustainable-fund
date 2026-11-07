"""Genera la ficha técnica del fondo en PDF (formato de la Superintendencia Financiera, secciones 1 a 17)."""
from __future__ import annotations

import io
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
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
    def __init__(self, fecha):
        super().__init__(format="A4")
        self.fecha = fecha
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
        self.cell(80, 4, "Invest with strength, grow with purpose.")
        self.set_font("DV", "B", 10)
        self.set_xy(100, 5)
        self.cell(98, 5, "Solid & Sustainable Equity Fund", align="R")
        self.set_font("DV", "", 7)
        self.set_xy(100, 11)
        self.cell(98, 4, f"2. Fecha de corte: {fecha_larga(self.fecha)}", align="R")
        self.set_text_color(*TINTA)
        self.set_y(24)

    def footer(self):
        self.set_y(-11)
        self.set_font("DV", "", 6.5)
        self.set_text_color(*GRIS)
        self.cell(0, 4, f"Solid & Sustainable Equity Fund · Ficha técnica · Página {self.page_no()} · "
                        "Ejercicio académico · Gestión de Portafolios · Universidad del Valle", align="C")

    def titulo(self, txt):
        if self.get_y() > 265:
            self.add_page()
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
        self.set_font("DV", "B", 6.4)
        self.set_text_color(*GRIS)
        for c, w, a in zip(cabecera, anchos, alinear):
            self.cell(w, 4.6, c.upper(), border="B", align=a)
        self.ln()
        self.set_text_color(*TINTA)
        self.set_font("DV", "", tam)
        for fila in filas:
            if self.get_y() > 275:
                self.add_page()
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


def _grafico_evolucion(serie_df):
    v = (1 + serie_df[["Fondo", "Índice compuesto"] + [c for c in serie_df.columns if c.startswith("S&P")]].fillna(0)).cumprod() * 100_000
    fig, ax = plt.subplots(figsize=(7.2, 2.3), dpi=200)
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
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf


def generar(res, serie_df, periodos, comp_indices, verif) -> bytes:
    f = res["fondo"]
    pdf = Ficha(res["fin"])
    pdf.add_page()

    pdf.titulo("1–5. Información general")
    pdf.kv([("1. Sociedad administradora", "Equipo Gestión de Portafolios · Universidad del Valle (ejercicio académico)"),
            ("3. Nombre del fondo", "Fondo de Inversión Colectiva Solid & Sustainable Equity Fund"),
            ("4. Gestores", "Pendiente: nombres del equipo gestor"),
            ("5. Custodio de valores", "No aplica (ejercicio académico)")])

    pdf.titulo("6. Características del FIC y tipos de participación")
    pdf.kv([("6.1 Tipo de FIC", "Abierto, sin pacto de permanencia"),
            ("6.2 Fecha de inicio de operaciones", "Pendiente: fecha definida por el equipo"),
            ("6.3 Valor del FIC", f"USD {M.INVERSION:,.0f}".replace(",", ".")),
            ("6.5 Valor inicial de la unidad / 6.4 unidades", "USD 10,00 / 100.000 unidades"),
            ("6.7 Inversión inicial mínima · 6.8 saldo mínimo", "USD 1.000 · USD 500"),
            ("6.9 Preaviso para retiro · 6.16 pacto de permanencia", "3 días hábiles · no tiene"),
            ("6.10 Comisión de administración", "2,50 % E.A."),
            ("6.11–6.14 Comisiones de gestión, éxito, entrada y salida", "No aplica"),
            ("6.17 Gastos totales (estimados)", "2,50 % E.A.")])

    pdf.titulo("7–8. Calificación y política de inversión")
    pdf.parrafo("7. Calificación: no aplica (fondo de renta variable). 8. Política: crecimiento del capital a largo plazo con "
                "acciones de empresas de Estados Unidos, Taiwán y Corea del Sur que cumplen los criterios ASG, tienen salud "
                "financiera buena, superan a su índice local y, al comprarse, no tienen lectura técnica desfavorable (media de 200 y 50 días, MACD y RSI). Entre 5 y 10 acciones de 10 % a 20 % cada una; mínimo 50 % en "
                "alto riesgo (β local > 1); tecnología ≤ 50 %; Taiwán + Corea ≤ 35 %; energía fósil ≤ 20 %; 5 % en liquidez. "
                "Sin renta fija, alternativos, derivados ni apalancamiento. Perfil de riesgo: arriesgado (clase 6 de 7). "
                "Índice de referencia: índice compuesto de los índices locales en USD (S&P 500, TAIEX y KOSPI), ponderado por "
                "el peso del fondo en cada país.")

    pdf.titulo(f"9. Evolución de USD 100.000 invertidos hace {M.VENTANA_ANIOS} años (simulación)")
    pdf.image(_grafico_evolucion(serie_df), x=12, w=186)

    pdf.titulo("10–11. Plazos, rentabilidad y volatilidad histórica (simulación)")
    pdf.parrafo("10. Plazos y duración: no aplica (100 % renta variable, sin vencimiento).", 7.2, GRIS)
    cols = list(periodos.columns)
    pdf.tabla(["Indicador"] + cols,
              [("11.1 Rentabilidad E.A.",) + tuple(pct(periodos.loc["Rentabilidad E.A.", c]) for c in cols),
               ("11.2 Volatilidad",) + tuple(pct(periodos.loc["Volatilidad", c]) for c in cols)],
              [36] + [25] * len(cols), ["L"] + ["R"] * len(cols))

    pdf.add_page()
    pdf.titulo("12. Composición del fondo")
    peso_m = f.groupby("Mercado")["Peso"].sum()
    peso_s = f.groupby("Sector")["Peso"].sum().sort_values(ascending=False)
    pdf.parrafo(f"12.1 Calificación: no aplica. 12.2 Tipo de renta: renta variable {pct(f['Peso'].sum())}, liquidez "
                f"{pct(M.PESO_LIQUIDEZ)}. 12.6 Por activo: inversiones {pct(f['Peso'].sum())}, disponible {pct(M.PESO_LIQUIDEZ)}. "
                "12.7 Exposición a derivados: no tiene.", 7.4)
    pdf.ln(1)
    filas = [(s, pct(p)) for s, p in peso_s.items()]
    pdf.tabla(["12.3 Sector", "Peso"], filas, [60, 30], ["L", "R"])
    pdf.ln(1)
    pdf.tabla(["12.4 País del emisor", "Peso", "12.5 Moneda"],
              [(MERCADO_ES.get(m, m), pct(p), MONEDA_ES.get(m, m)) for m, p in peso_m.sort_values(ascending=False).items()]
              + [("Liquidez", pct(M.PESO_LIQUIDEZ), "Dólar (USD)")], [60, 30, 60], ["L", "R", "L"])

    pdf.titulo("13. Principales inversiones")
    filas = [(r["Empresa"][:34], a, MERCADO_ES.get(r["Mercado"], r["Mercado"]), r["Sector"], pct(r["Peso"]),
              f"{r['Monto (USD)']:,.0f}".replace(",", "."), pct(r["Robustez"], 0)) for a, r in f.iterrows()]
    filas.append(("Total renta variable", "", "", "", pct(f["Peso"].sum()), f"{f['Monto (USD)'].sum():,.0f}".replace(",", "."), ""))
    pdf.tabla(["Emisor", "Ticker", "País", "Sector", "Peso", "Monto USD", "Robustez"], filas,
              [50, 22, 24, 34, 16, 24, 16], ["L", "L", "L", "L", "R", "R", "R"])

    pdf.titulo(f"Cada activo frente a su índice local ({M.VENTANA_ANIOS} años, moneda local)")
    filas = [(a, M.NOMBRE_INDICE.get(r["Índice local"], r["Índice local"]), pct(r["Rentabilidad anual"]), pct(r["Rentabilidad del índice"]),
              num(r["Sharpe"]), num(r["Sharpe del índice"]), num(r["Beta local"]), pct(r["Alfa de Jensen"])) for a, r in f.iterrows()]
    pdf.tabla(["Activo", "Índice", "Rent. activo", "Rent. índice", "Sharpe", "Sharpe índ.", "Beta", "Alfa"], filas,
              [26, 22, 24, 24, 20, 22, 20, 28], ["L", "L", "R", "R", "R", "R", "R", "R"])

    pdf.titulo(f"Indicadores del fondo frente a los índices (simulación de {M.VENTANA_ANIOS} años, USD)")
    cols = list(comp_indices.columns)
    filas = []
    for k in comp_indices.index:
        vals = [(f"{v:,.0f}".replace(",", ".") if "USD" in k else (num(v) if k.startswith(("Sharpe", "Beta")) else pct(v)))
                for v in comp_indices.loc[k]]
        filas.append((k,) + tuple(vals))
    w0 = 186 - 46
    pdf.tabla(["Indicador"] + cols, filas, [46] + [w0 / len(cols)] * len(cols), ["L"] + ["R"] * len(cols), tam=6.8)

    pdf.titulo("Salud financiera y ASG de los activos")
    filas = [(a, pct(r["ROA (Retorno Activos)"]), pct(r["ROE (Retorno Capital)"]),
              "n. a." if r["Sector"] == "Servicios financieros" else num(r["Ratio Liquidez (Current Ratio)"]) + "x",
              "n. a." if r["Sector"] == "Servicios financieros" else pct(r["Endeudamiento"]),
              r["Nivel de salud"], r["Criterio ASG"]) for a, r in f.iterrows()]
    pdf.tabla(["Activo", "ROA", "ROE", "Liquidez", "Endeud.", "Salud", "ASG"], filas,
              [28, 22, 22, 22, 22, 26, 44], ["L", "R", "R", "R", "R", "L", "L"])

    pdf.titulo("14–17. Vinculadas, gerentes, revisor fiscal y defensor del consumidor")
    pdf.kv([("14. Empresas vinculadas", "No aplica (ejercicio académico)"),
            ("15. Hoja de vida de los gerentes", "Pendiente: integrantes del equipo y sus roles"),
            ("16. Revisor fiscal · 17. Defensor del consumidor", "No aplica (ejercicio académico)")])

    pdf.titulo("Verificación de la política")
    pdf.tabla(["Origen", "Regla", "Valor", "Cumple"], [tuple(x) for x in verif.values.tolist()], [24, 88, 58, 16],
              ["L", "L", "L", "C"], tam=6.8)

    pdf.ln(2)
    pdf.parrafo("Advertencia. Este material es para información de los inversionistas y no constituye una oferta ni una solicitud "
                "para comprar o vender valores. Las obligaciones de la sociedad administradora relacionadas con la gestión del "
                "portafolio son de medio y no de resultado. La inversión está sujeta a los riesgos de los activos que componen el "
                "fondo. Las rentabilidades históricas son simulaciones con los pesos actuales y no garantizan rentabilidades "
                "futuras. Ejercicio académico del curso Gestión de Portafolios, Universidad del Valle.", 6.4, GRIS)
    return bytes(pdf.output())
