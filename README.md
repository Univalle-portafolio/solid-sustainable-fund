# Solidez Sostenible · Renta Variable — aplicación web

*Invertir con fundamento, crecer con propósito.*

Aplicación que muestra la ficha técnica del fondo, el seguimiento del portafolio oficial y la metodología de selección.
Los precios vienen de Yahoo Finance.

- **Portafolio oficial congelado:** está en `data/portafolio_oficial.csv` (ticker, peso y fecha de selección). La página
  **no lo recalcula** al entrar: con los datos de la fecha de selección calcula sus indicadores, la frontera, la robustez y
  la verificación. Para cambiar el portafolio en una revisión trimestral, edite ese archivo (los pesos deben sumar 95 %).
- **Seguimiento:** con los precios del día muestra cómo se movieron los pesos y si cada activo sigue cumpliendo los criterios
  fundamentales (ASG, salud financiera y bursatilidad). Un activo sale solo si deja de cumplirlos; el técnico decide cuándo comprar.
- **Prueba fuera de muestra:** la misma metodología con precios hasta octubre de 2023, simulada hasta hoy (corrige el sesgo
  de la simulación de 3 años, que usa las mismas fechas con que se escogieron las empresas).
- **Ficha técnica en PDF y Excel de la frontera:** se generan al momento (botones en la barra lateral). El Excel guarda las
  fórmulas y sus resultados, tiene hoja CAPM, verificación de la política y una fila con Solver configurado.

## Archivos

| Archivo | Para qué sirve |
|---|---|
| `app.py` | La página web (Streamlit) |
| `motor.py` | El motor de selección: ASG, salud financiera, bursatilidad frente al índice local, Markowitz y robustez. **Aquí se cambian la política y los parámetros** |
| `ficha_pdf.py` | Genera la ficha técnica en PDF con el formato de la Superintendencia Financiera |
| `data/portafolio_oficial.csv` | **Portafolio oficial congelado** (ticker, peso sobre el fondo y fecha de selección) |
| `data/universo.csv` | Universo con fundamentales y riesgo ASG; lo actualiza cada noche la tarea de GitHub |
| `frontera_excel.py` | Genera el Excel de la frontera eficiente |
| `universo.py`, `actualizar_universo.py` | Descargan el universo y sus fundamentales |
| `fonts/` | Tipografía para el PDF |
| `requirements.txt` | Paquetes de Python que instala el servidor (incluye `xlsxwriter`) |

## Metodología (versión de noviembre de 2026)

1. ASG → 2. salud financiera (fundamentales) → 3. bursatilidad frente al índice local (3 años) → 4. técnico
   (precio sobre la media de 200 días obligatorio; media de 50, MACD y RSI entre 30 y 50: retroceso en tendencia alcista) → 5. **5 sectores con igual peso (19 % cada uno) y hasta 2 empresas por sector** (1 si solo una cumple todo),
   eligiendo entre todas las combinaciones de 5 sectores la de mayor Sharpe que cumpla ≥ 50 % en alto riesgo (β > 1),
   Taiwán + Corea ≤ 35 % y VaR 95 % a 1 mes ≤ 8 % → 6. robustez en 54 escenarios.
- `frontera_excel.py` genera el Excel de la frontera eficiente (entregable 4) con fórmulas; se descarga desde la aplicación.
- La pestaña **Frontera eficiente** muestra la frontera, la línea del mercado de capitales, la comparación antes/después
  y las correlaciones en los meses de caída.

## Universo automático (sin Excel)

- `universo.py` arma el universo: todas las empresas del S&P 500 (lista vigente de Wikipedia) y las mayores de Taiwán y
  Corea del Sur, con ROA, ROE, liquidez, deuda/capital, PER, sector e industria descargados de Yahoo Finance.
- `.github/workflows/actualizar_universo.yml` ejecuta `actualizar_universo.py` cada noche de lunes a viernes y guarda el
  resultado en `data/universo.csv`. También se puede ejecutar a mano: pestaña **Actions → Actualizar universo de empresas → Run workflow**.
- La aplicación usa, en este orden: `data/universo.csv` → el ranking en Excel (respaldo) → el botón *Construir universo ahora*.
- Los filtros sin precios (ASG, salud financiera, PER) se aplican a todo el universo; solo las empresas que pasan descargan
  precios para la comparación con su índice.

## Publicarla en internet (gratis, unos 15 minutos)

1. **Cree una cuenta en GitHub** (https://github.com) si no tiene una.
2. **Cree un repositorio nuevo**: botón *New*, nombre por ejemplo `fondo-pacifico`, visibilidad *Public*, y *Create repository*.
3. **Suba los archivos**: en el repositorio, *Add file → Upload files*. Arrastre **todo el contenido** de esta carpeta
   (incluidas las carpetas `data`, `fonts` y `.streamlit`) y **el archivo del ranking dentro de `data/`**, con el nombre
   `ranking_PER_EEUU_Taiwan_Corea.xlsx`. Pulse *Commit changes*.
   - Si la carpeta `.streamlit` no se sube porque empieza con punto, no pasa nada: solo define los colores.
4. **Cree una cuenta en Streamlit Community Cloud** (https://share.streamlit.io) entrando con su cuenta de GitHub.
5. Pulse **Create app → Deploy a public app from GitHub**, elija el repositorio `fondo-pacifico`, la rama `main` y el
   archivo `app.py`. En *App URL* puede escribir un nombre, por ejemplo `fondo-pacifico-uv`. Pulse **Deploy**.
6. La primera vez tarda unos minutos en instalar los paquetes. Después queda un enlace del tipo
   `https://fondo-pacifico-uv.streamlit.app` que puede compartir con el profesor.

Cada visita descarga los precios del día. Para no saturar Yahoo Finance, la aplicación guarda los datos durante una hora;
el botón **Actualizar precios ahora** los vuelve a descargar.

## Cambiar la política del fondo

Todo está al inicio de `motor.py`:

- `POLITICA`: número de activos, piso y tope por activo, mínimo de alto riesgo, límites de tecnología, Asia y energía,
  robustez mínima y desviación que activa el rebalanceo.
- `PESO_LIQUIDEZ`, `CANDIDATOS_POR_MERCADO`, `VENTANA_ANIOS`.
- `ASG`: tickers excluidos, palabras de actividades excluidas y notas de seguimiento.
- `UMBRAL_SALUD`: cortes del semáforo de salud financiera.

Después de editar un archivo en GitHub (lápiz → *Commit changes*), la aplicación se actualiza sola en uno o dos minutos.

## Probarla en su computador (opcional)

```
pip install -r requirements.txt
streamlit run app.py
```

## Notas

- Los fundamentales (ROA, ROE, liquidez, deuda/capital, PER) se toman del ranking. El interruptor
  *Actualizar fundamentales desde Yahoo Finance* los reemplaza por los más recientes (tarda cerca de un minuto).
- La rentabilidad histórica y la evolución de USD 100.000 son simulaciones con los pesos del portafolio oficial.
- Ejercicio académico del curso Gestión de Portafolios, Universidad del Valle.
