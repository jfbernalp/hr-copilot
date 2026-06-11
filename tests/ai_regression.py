"""
ai_regression.py
----------------
Test de regresión del pipeline IA (Fase 2): corre preguntas canónicas por el
pipeline completo (generate_sql → RLS → SQLite → generate_chart) y valida:

  1. El SQL generado ejecuta y devuelve filas.
  2. El tipo de gráfico pertenece a la familia esperada para la semántica de la
     pregunta (el objetivo: que NO todo termine en barras verticales).
  3. Todos los colores del gráfico pertenecen a la paleta Práxedes.

Usa la API de Gemini (costo ≈ $0.02 por corrida completa). Correr desde el root:
    python tests/ai_regression.py
Sale con código 1 si falla algún SQL o si la tasa de acierto de gráficos < 75%.
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

import app.dashboard as d   # inicializa Vanna + conexión

# Cada caso: pregunta + familias de gráfico aceptadas (conjunto de trace types).
# "bar_v_bad" marca preguntas donde una barra vertical sería el error clásico.
CASES = [
    # ── Series temporales (el caso crítico anti-barras) ──
    {"q": "¿Cómo ha evolucionado el headcount mes a mes?",
     "allowed": [{"scatter"}, {"bar", "scatter"}], "no_pure_vbar": True},
    {"q": "¿Cuál es la tasa de ausentismo mensual?",
     "allowed": [{"scatter"}, {"bar", "scatter"}], "no_pure_vbar": True},
    {"q": "¿Cuál es el eNPS por ciclo de encuesta?",
     "allowed": [{"scatter"}, {"bar", "scatter"}], "no_pure_vbar": True},
    {"q": "¿Qué porcentaje de los ingresos se gasta en nómina cada mes?",
     "allowed": [{"scatter"}], "no_pure_vbar": True},
    {"q": "Horas extra promedio por mes y departamento",
     "allowed": [{"scatter"}, {"heatmap"}], "no_pure_vbar": True},
    {"q": "Salidas voluntarias vs involuntarias por mes",
     "allowed": [{"bar"}, {"scatter"}, {"bar", "scatter"}]},
    # ── Proporciones → dona ──
    {"q": "¿Qué porcentaje de empleados hay por género?",
     "allowed": [{"pie"}]},
    {"q": "¿Cómo se distribuyen las incapacidades por tipo?",
     "allowed": [{"pie"}, {"bar"}]},
    # ── Correlación → scatter ──
    {"q": "¿Cómo se relacionan el salario mensual y los años en la compañía?",
     "allowed": [{"scatter"}], "no_pure_vbar": True},
    # ── Valor único → indicador ──
    {"q": "¿Cuántos empleados activos hay en total?",
     "allowed": [{"indicator"}], "no_pure_vbar": True},
    # ── Distribución → histograma/box ──
    {"q": "Muéstrame la distribución de la edad de los empleados",
     "allowed": [{"histogram"}, {"box"}, {"bar"}]},
    # ── Secuencial → línea ──
    {"q": "Salario promedio por nivel de cargo",
     "allowed": [{"scatter"}, {"bar"}]},
    # ── Rankings → barras está bien aquí ──
    {"q": "Tiempo promedio de cobertura de vacantes por departamento",
     "allowed": [{"bar"}]},
    {"q": "¿Qué programas de capacitación mejoraron más el desempeño?",
     "allowed": [{"bar"}]},
]


def _colors_of(fig_dict):
    """Extrae todos los colores string de marker/line de las trazas."""
    out = []
    for tr in fig_dict.get("data", []):
        marker = tr.get("marker", {})
        for c in ([marker.get("color")] if isinstance(marker.get("color"), str)
                  else (marker.get("color") or [])):
            if isinstance(c, str):
                out.append(c)
        for c in (marker.get("colors") or []):
            if isinstance(c, str):
                out.append(c)
        line = tr.get("line", {})
        if isinstance(line.get("color"), str):
            out.append(line["color"])
    return out


def _palette_ok(colors):
    ok_prefixes = ("rgba(255,139,0", "rgba(0,0,0,0)")
    for c in colors:
        cl = c.lower().replace(" ", "")
        if cl.startswith("#") and cl not in d._PRAXEDES_HEX:
            return False, c
        if cl.startswith("rgb") and not cl.startswith(ok_prefixes):
            return False, c
    return True, None


def main():
    sql_fail, chart_pass, chart_total, palette_fail = 0, 0, 0, 0
    print(f"{'':2}{'pregunta':<58} {'sql':<4} {'tipos':<22} {'gráfico':<8} paleta")
    print("─" * 110)
    for case in CASES:
        r = d.process_question(case["q"], "hr_admin")
        if r["error"] or not r["fig_json"]:
            sql_fail += 1
            print(f"✗ {case['q'][:56]:<58} FAIL {str(r['error'])[:40]}")
            continue
        fig = json.loads(r["fig_json"])
        types = {tr.get("type", "scatter") for tr in fig.get("data", [])}

        ok_type = any(types == a or types <= a for a in case["allowed"])
        if case.get("no_pure_vbar") and types == {"bar"}:
            # barra vertical pura donde no corresponde: ¿es horizontal?
            orientations = {tr.get("orientation") for tr in fig["data"]}
            ok_type = orientations == {"h"} and not case.get("no_pure_vbar")
        chart_total += 1
        chart_pass += ok_type

        pal_ok, bad = _palette_ok(_colors_of(fig))
        palette_fail += not pal_ok
        cache = " (cache)" if r["from_cache"] else ""
        print(f"{'✓' if ok_type else '✗'} {case['q'][:56]:<58} ok   "
              f"{str(sorted(types)):<22} {'PASS' if ok_type else 'FAIL':<8} "
              f"{'ok' if pal_ok else 'FAIL: ' + str(bad)}{cache}")

    rate = 100 * chart_pass / max(chart_total, 1)
    print("─" * 110)
    print(f"SQL ejecutable: {len(CASES) - sql_fail}/{len(CASES)} | "
          f"Gráfico correcto: {chart_pass}/{chart_total} ({rate:.0f}%) | "
          f"Violaciones de paleta: {palette_fail}")
    if sql_fail > 0 or rate < 75 or palette_fail > 0:
        sys.exit(1)
    print("REGRESIÓN OK")


if __name__ == "__main__":
    main()
