"""
Actualiza data/universo.csv con el universo completo y sus fundamentales (Yahoo Finance).
Lo ejecuta cada noche la tarea de GitHub (.github/workflows/actualizar_universo.yml); también puede correrse a mano:
    python actualizar_universo.py
"""
import os
import sys

import pandas as pd

import universo as U

AQUI = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(AQUI, "data", "universo.csv")


def main():
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)

    def progreso(i, n, t):
        if i % 50 == 0:
            print(f"  {i}/{n} · {t}", flush=True)

    u = U.construir_universo(progreso, anterior=SALIDA if os.path.exists(SALIDA) else None)
    if len(u) < 100:
        print(f"Solo se obtuvieron {len(u)} empresas; se conserva el universo anterior.", file=sys.stderr)
        sys.exit(1)
    u["Fecha de actualización"] = pd.Timestamp.today().strftime("%Y-%m-%d")
    u.to_csv(SALIDA, encoding="utf-8")
    print(f"Universo guardado: {len(u)} empresas · {u['Mercado'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
