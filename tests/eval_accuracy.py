"""
eval_accuracy.py
-----------------
Arnés de precisión y alucinaciones — NovaTech Colombia S.A.S. / PostgreSQL.

Mide dos tipos de falla por separado, para cada pregunta:

  1. Alucinación ESTRUCTURAL: el SQL generado no ejecuta (referencia una tabla o
     columna que no existe, sintaxis inválida, etc.).
  2. Alucinación DE CONTENIDO: el SQL ejecuta sin error, pero el valor que
     devuelve no coincide con el de una consulta de referencia escrita y
     verificada a mano contra el esquema real (tolerancia configurable).

También valida, igual que tests/ai_regression.py, que el tipo de gráfico
generado pertenezca a la familia esperada y que la paleta sea Práxedes — pero
PARA RESPONDER "¿el modelo acierta HOY?" este script NO usa query_cache: cada
caso llama a vn.generate_sql() de cero, nunca reutiliza una respuesta cacheada
de hace semanas (a diferencia de ai_regression.py, que sí puede devolver
resultados de caché — bueno para una prueba de humo rápida, malo como línea
base de precisión).

Cada corrida se guarda en la tabla eval_runs para poder graficar la evolución
de la precisión en el tiempo a medida que se implementen las mejoras del
roadmap (auto-corrección, memoria conversacional, feedback RAG, etc.).

Uso:
    python tests/eval_accuracy.py
    python tests/eval_accuracy.py --save-json informe.json
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

import pandas as pd
import app.dashboard as d   # inicializa Vanna + conexión (mismo proceso que la app real)

ROLE = "hr_admin"
USER = "eval_harness"
DEFAULT_TOLERANCE = 0.03   # 3% de tolerancia relativa en comparaciones numéricas

# ══════════════════════════════════════════════════════════════════════════
# CASOS — pregunta en lenguaje natural + SQL de referencia verificado a mano
# contra las 9 vistas semánticas y las tablas de apoyo de NovaTech/Postgres.
# mode: "scalar" (un solo número) | "grouped" (una fila por categoría)
# ══════════════════════════════════════════════════════════════════════════
CASES = [
    # ── v_perfil_empleado ──
    {"q": "¿Cuántos empleados activos hay en total?", "mode": "scalar",
     "ref_sql": "SELECT COUNT(*) FROM v_perfil_empleado WHERE estado_empleo='activo'",
     "allowed": [{"indicator"}]},
    {"q": "¿Cuántos empleados activos hay en cada sede?", "mode": "grouped",
     "ref_sql": "SELECT sede, COUNT(*) FROM v_perfil_empleado WHERE estado_empleo='activo' GROUP BY sede",
     "allowed": [{"bar"}, {"pie"}]},
    {"q": "¿Cuál es el salario promedio de los empleados activos?", "mode": "scalar",
     "ref_sql": "SELECT AVG(salario_actual) FROM v_perfil_empleado WHERE estado_empleo='activo'",
     "allowed": [{"indicator"}]},
    {"q": "¿Cuál es el salario promedio por género entre los empleados activos?", "mode": "grouped",
     "ref_sql": "SELECT genero, AVG(salario_actual) FROM v_perfil_empleado WHERE estado_empleo='activo' GROUP BY genero",
     "allowed": [{"bar"}]},
    {"q": "¿Cuántos empleados activos tiene cada departamento?", "mode": "grouped",
     "ref_sql": "SELECT departamento, COUNT(*) FROM v_perfil_empleado WHERE estado_empleo='activo' GROUP BY departamento",
     "allowed": [{"bar"}]},
    {"q": "¿Cuál es la antigüedad promedio, en años, de los empleados activos?", "mode": "scalar",
     "ref_sql": "SELECT AVG(anos_empresa) FROM v_perfil_empleado WHERE estado_empleo='activo'",
     "allowed": [{"indicator"}]},

    # ── v_nomina_mensual ──
    {"q": "¿Cuál fue el costo total de nómina en el último mes disponible?", "mode": "scalar",
     "ref_sql": "SELECT SUM(costo_total_empresa) FROM v_nomina_mensual WHERE periodo=(SELECT MAX(periodo) FROM v_nomina_mensual)",
     "allowed": [{"indicator"}]},
    {"q": "¿Cuál es el costo de nómina por sede en el último mes disponible?", "mode": "grouped",
     "ref_sql": "SELECT sede, SUM(costo_total_empresa) FROM v_nomina_mensual WHERE periodo=(SELECT MAX(periodo) FROM v_nomina_mensual) GROUP BY sede",
     "allowed": [{"bar"}, {"pie"}]},
    {"q": "¿Cuál es el salario neto promedio por nivel de cargo en el último mes?", "mode": "grouped",
     "ref_sql": "SELECT nivel_cargo, AVG(salario_neto) FROM v_nomina_mensual WHERE periodo=(SELECT MAX(periodo) FROM v_nomina_mensual) GROUP BY nivel_cargo",
     "allowed": [{"bar"}, {"scatter"}]},

    # ── v_asistencia_mensual ──
    {"q": "¿Cuál es la tasa de asistencia promedio del último mes disponible?", "mode": "scalar",
     "ref_sql": "SELECT AVG(tasa_asistencia) FROM v_asistencia_mensual WHERE periodo=(SELECT MAX(periodo) FROM v_asistencia_mensual)",
     "allowed": [{"indicator"}]},
    {"q": "¿Cuántos días de ausencia hubo por sede en el último mes disponible?", "mode": "grouped",
     "ref_sql": "SELECT sede, SUM(dias_ausencia) FROM v_asistencia_mensual WHERE periodo=(SELECT MAX(periodo) FROM v_asistencia_mensual) GROUP BY sede",
     "allowed": [{"bar"}]},
    {"q": "¿Cuántas horas extra acumuló cada departamento en el último mes disponible?", "mode": "grouped",
     "ref_sql": "SELECT departamento, SUM(total_horas_extra) FROM v_asistencia_mensual WHERE periodo=(SELECT MAX(periodo) FROM v_asistencia_mensual) GROUP BY departamento",
     "allowed": [{"bar"}]},

    # ── v_rotacion_retiros ──
    {"q": "¿Cuántos retiros hubo en los últimos 12 meses?", "mode": "scalar",
     "ref_sql": "SELECT COUNT(*) FROM v_rotacion_retiros WHERE fecha_retiro >= CURRENT_DATE - INTERVAL '12 months'",
     "allowed": [{"indicator"}]},
    {"q": "¿Cuántos retiros voluntarios vs involuntarios hubo en los últimos 12 meses?", "mode": "grouped",
     "ref_sql": "SELECT tipo_retiro, COUNT(*) FROM v_rotacion_retiros WHERE fecha_retiro >= CURRENT_DATE - INTERVAL '12 months' AND tipo_retiro IN ('voluntario','involuntario') GROUP BY tipo_retiro",
     "allowed": [{"bar"}, {"pie"}]},
    {"q": "¿Qué departamento tuvo más retiros en los últimos 12 meses?", "mode": "grouped",
     "ref_sql": "SELECT departamento, COUNT(*) FROM v_rotacion_retiros WHERE fecha_retiro >= CURRENT_DATE - INTERVAL '12 months' GROUP BY departamento",
     "allowed": [{"bar"}]},
    {"q": "¿Cuál es la calificación promedio que dan los empleados que se retiran de la empresa?", "mode": "scalar",
     "ref_sql": "SELECT AVG(calificacion_empresa) FROM v_rotacion_retiros",
     "allowed": [{"indicator"}]},

    # ── v_headcount_historico ──
    {"q": "¿Cuál es el headcount total según el histórico del último mes disponible?", "mode": "scalar",
     "ref_sql": "SELECT SUM(headcount_fin) FROM v_headcount_historico WHERE periodo=(SELECT MAX(periodo) FROM v_headcount_historico)",
     "allowed": [{"indicator"}]},
    {"q": "¿Cuál ha sido la tasa de rotación mensual promedio en los últimos 12 meses?", "mode": "scalar",
     "ref_sql": "SELECT AVG(tasa_rotacion_mensual) FROM v_headcount_historico WHERE periodo >= CURRENT_DATE - INTERVAL '12 months'",
     "allowed": [{"indicator"}]},

    # ── v_evaluaciones_desempeno ──
    {"q": "¿Cuál es el desempeño promedio por departamento en la evaluación más reciente?", "mode": "grouped",
     "ref_sql": "SELECT departamento, AVG(puntaje_total) FROM v_evaluaciones_desempeno WHERE periodo=(SELECT MAX(periodo) FROM v_evaluaciones_desempeno) GROUP BY departamento",
     "allowed": [{"bar"}]},
    {"q": "¿Qué porcentaje de empleados fue clasificado como sobresaliente en la evaluación más reciente?", "mode": "scalar",
     "ref_sql": "SELECT 100.0*SUM((clasificacion='sobresaliente')::int)/COUNT(*) FROM v_evaluaciones_desempeno WHERE periodo=(SELECT MAX(periodo) FROM v_evaluaciones_desempeno)",
     "allowed": [{"indicator"}, {"pie"}]},

    # ── v_vacantes_reclutamiento ──
    {"q": "¿Cuántas vacantes están abiertas en este momento?", "mode": "scalar",
     "ref_sql": "SELECT COUNT(*) FROM v_vacantes_reclutamiento WHERE estado='abierta'",
     "allowed": [{"indicator"}]},
    {"q": "¿Cuál es el tiempo promedio, en días, para cubrir una vacante?", "mode": "scalar",
     "ref_sql": "SELECT AVG(dias_abierta) FROM v_vacantes_reclutamiento WHERE estado='cubierta'",
     "allowed": [{"indicator"}]},
    {"q": "¿Qué departamento tarda más en promedio en cubrir sus vacantes?", "mode": "grouped",
     "ref_sql": "SELECT departamento, AVG(dias_abierta) FROM v_vacantes_reclutamiento WHERE estado='cubierta' GROUP BY departamento",
     "allowed": [{"bar"}]},
    {"q": "¿Cuántas vacantes cubiertas hay por cada fuente de contratación?", "mode": "grouped",
     "ref_sql": "SELECT fuente_contratacion, COUNT(*) FROM v_vacantes_reclutamiento WHERE estado='cubierta' GROUP BY fuente_contratacion",
     "allowed": [{"bar"}, {"pie"}]},

    # ── v_engagement_encuestas ──
    {"q": "¿Cuál fue el eNPS en el ciclo de encuesta más reciente?", "mode": "scalar",
     "ref_sql": "SELECT AVG(enps) FROM v_engagement_encuestas WHERE periodo=(SELECT MAX(periodo) FROM v_engagement_encuestas)",
     "allowed": [{"indicator"}]},
    {"q": "¿Cuál es la tasa de participación promedio histórica en las encuestas de clima?", "mode": "scalar",
     "ref_sql": "SELECT AVG(tasa_participacion) FROM v_engagement_encuestas",
     "allowed": [{"indicator"}]},

    # ── v_capacitaciones ──
    {"q": "¿Cuántos empleados completaron una capacitación en los últimos 12 meses?", "mode": "scalar",
     "ref_sql": "SELECT COUNT(DISTINCT empleado_id) FROM v_capacitaciones WHERE estado='completado' AND fecha_fin >= CURRENT_DATE - INTERVAL '12 months'",
     "allowed": [{"indicator"}]},
    {"q": "¿Cuál es la mejora promedio de desempeño después de completar una capacitación?", "mode": "scalar",
     "ref_sql": "SELECT AVG(delta_desempeno) FROM v_capacitaciones WHERE estado='completado'",
     "allowed": [{"indicator"}, {"histogram"}, {"box"}]},
    {"q": "¿Cuántos programas de capacitación hay por categoría?", "mode": "grouped",
     "ref_sql": "SELECT categoria, COUNT(DISTINCT programa_id) FROM v_capacitaciones GROUP BY categoria",
     "allowed": [{"bar"}, {"pie"}]},

    # ── tablas de apoyo ──
    {"q": "¿Cuántos días de incapacidad se registraron en los últimos 12 meses?", "mode": "scalar",
     "ref_sql": "SELECT SUM(dias) FROM incapacidades WHERE fecha_inicio >= CURRENT_DATE - INTERVAL '12 months'",
     "allowed": [{"indicator"}]},
    {"q": "¿Cuántos días de vacaciones pendientes tienen acumulados los empleados en total, en el periodo más reciente?", "mode": "scalar",
     "ref_sql": "SELECT SUM(dias_pendientes) FROM saldo_vacaciones WHERE periodo=(SELECT MAX(periodo) FROM saldo_vacaciones)",
     "allowed": [{"indicator"}]},
]


# ══════════════════════════════════════════════════════════════════════════
# Comparación de resultados
# ══════════════════════════════════════════════════════════════════════════
def _close(a, b, tol=DEFAULT_TOLERANCE) -> bool:
    if a is None or b is None:
        return False
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if abs(b) < 1e-9:
        return abs(a) < 1e-6
    return abs(a - b) / abs(b) <= tol


def compare_scalar(gen_df: pd.DataFrame, ref_val):
    """
    El modelo cumple si ALGUNA columna numérica del resultado — tomada como
    primer valor, como suma, o como promedio de todas las filas — coincide con
    la referencia. Esto evita penalizar al modelo cuando responde bien pero
    agrega columnas extra (un conteo junto al promedio) o desagrega un total
    pedido como único número en varias filas (p. ej. por sede) que al sumarlas
    reconstruyen el total correcto. Un DataFrame vacío cuenta como 0 en todas
    las columnas (para "¿cuántos X hay?" cuando la respuesta real es cero).
    """
    num_cols = [c for c in gen_df.columns if pd.api.types.is_numeric_dtype(gen_df[c])] if gen_df is not None else []
    if gen_df is None or (len(gen_df) == 0 and not num_cols):
        # 0 filas y ni siquiera sabemos qué columnas esperar: tratar como 0.
        ok = _close(0, ref_val)
        return ok, f"0 filas (tratado como 0) vs referencia={ref_val}"
    if not num_cols:
        return False, "sin columna numérica"

    best_col, best_val, best_diff = None, None, float("inf")
    for c in num_cols:
        s = gen_df[c]
        # Cualquier valor individual (p. ej. una fila "TOTAL" en un UNION ALL),
        # más la suma y el promedio (si el total vino desagregado por fila).
        candidates = set(float(v) for v in s.tolist()) | {float(s.sum()), float(s.mean())} if len(s) else {0.0}
        for v in candidates:
            try:
                diff = abs(v - float(ref_val)) / max(abs(float(ref_val)), 1e-9)
            except (TypeError, ValueError):
                continue
            if diff < best_diff:
                best_col, best_val, best_diff = c, v, diff
            if _close(v, ref_val):
                return True, f"columna={c} valor={v} vs referencia={ref_val}"
    return False, f"ningún candidato coincide — más cercano: columna={best_col} valor={best_val} vs referencia={ref_val}"


def compare_grouped(gen_df: pd.DataFrame, ref_df: pd.DataFrame):
    """Igual idea que compare_scalar pero por grupo: prueba cada columna numérica
    como posible "valor" y se queda con la que logre mejor cobertura contra la
    referencia, en vez de asumir que es la primera columna numérica."""
    if gen_df is None or len(gen_df) == 0:
        return False, "sin filas"
    key_col_ref, val_col_ref = ref_df.columns[0], ref_df.columns[1]
    ref_map = {str(k).strip().lower(): v for k, v in zip(ref_df[key_col_ref], ref_df[val_col_ref])}

    text_cols = [c for c in gen_df.columns if not pd.api.types.is_numeric_dtype(gen_df[c])]
    num_cols  = [c for c in gen_df.columns if pd.api.types.is_numeric_dtype(gen_df[c])]
    if not text_cols or not num_cols:
        return False, "no se pudo identificar columna de categoría/valor"

    # Prueba cada combinación (columna-categoría × columna-valor) — el modelo
    # puede anteponer otra columna de texto (p. ej. "mes") antes de la
    # categoría real que pidió la pregunta (p. ej. "sede").
    best = None  # (key_col, val_col, coverage, mismatched, missing)
    for key_col_gen in text_cols:
        for val_col_gen in num_cols:
            matched, mismatched, missing = 0, [], []
            for k, ref_v in ref_map.items():
                row = gen_df[gen_df[key_col_gen].astype(str).str.strip().str.lower() == k]
                if len(row) == 0:
                    missing.append(k)
                    continue
                gen_v = row.iloc[0][val_col_gen]
                if _close(gen_v, ref_v):
                    matched += 1
                else:
                    mismatched.append(f"{k}: generado={gen_v} vs referencia={ref_v}")
            coverage = matched / max(len(ref_map), 1)
            if best is None or coverage > best[2]:
                best = (key_col_gen, val_col_gen, coverage, mismatched, missing)

    key_col_gen, val_col_gen, coverage, mismatched, missing = best
    ok = coverage >= 0.9 and not mismatched
    detail = f"clave={key_col_gen} columna={val_col_gen} coverage={coverage:.0%}"
    if mismatched:
        detail += f" | mismatches={mismatched[:3]}"
    if missing:
        detail += f" | faltantes={missing[:3]}"
    return ok, detail


def _colors_of(fig_dict):
    out = []
    for tr in fig_dict.get("data", []):
        marker = tr.get("marker", {})
        c = marker.get("color")
        if isinstance(c, str):
            out.append(c)
        for cc in (marker.get("colors") or []):
            if isinstance(cc, str):
                out.append(cc)
        line_c = tr.get("line", {}).get("color")
        if isinstance(line_c, str):
            out.append(line_c)
    return out


def _palette_ok(colors):
    ok_prefixes = ("rgba(255,139,0", "rgba(0,0,0,0)")
    for c in colors:
        cl = c.lower().replace(" ", "")
        if cl.startswith("#") and cl not in d._PRAXEDES_HEX:
            return False
        if cl.startswith("rgb") and not cl.startswith(ok_prefixes):
            return False
    return True


# ══════════════════════════════════════════════════════════════════════════
# Ejecución
# ══════════════════════════════════════════════════════════════════════════
def run_case(case: dict) -> dict:
    out = {"q": case["q"], "sql_ok": False, "content_ok": None, "chart_ok": None,
           "palette_ok": None, "detail": "", "sql": None, "error": None}
    t0 = time.time()

    # 1. Generar SQL fresco — SIN cache, para medir el modelo de hoy.
    try:
        sql = d.clean_sql(d.vn.generate_sql(question=case["q"], allow_llm_to_see_data=True))
    except Exception as e:
        out["error"] = f"generate_sql: {e}"
        return out
    out["sql"] = sql

    # 2. RLS + ejecución
    try:
        sql_run = d.rls_intercept(sql, ROLE, d.conn, user=USER)
        gen_df = pd.read_sql_query(sql_run, d.conn._c)
    except Exception as e:
        out["error"] = f"ejecución: {e}"
        return out
    out["sql_ok"] = True

    # 3. Comparar contra la referencia
    try:
        ref_df = pd.read_sql_query(case["ref_sql"], d.conn._c)
    except Exception as e:
        out["error"] = f"ref_sql inválido (bug del arnés, no del modelo): {e}"
        return out

    if case["mode"] == "scalar":
        ref_val = ref_df.iloc[0, 0]
        ok, detail = compare_scalar(gen_df, ref_val)
    else:
        ok, detail = compare_grouped(gen_df, ref_df)
    out["content_ok"] = ok
    out["detail"] = detail

    # 4. Gráfico
    try:
        fig = d.generate_chart(gen_df, case["q"], sql)
        fig_dict = json.loads(fig.to_json())
        types = {tr.get("type", "scatter") for tr in fig_dict.get("data", [])}
        out["chart_ok"] = any(types == a or types <= a for a in case["allowed"])
        out["palette_ok"] = _palette_ok(_colors_of(fig_dict))
    except Exception as e:
        out["chart_ok"] = False
        out["palette_ok"] = False
        out["detail"] += f" | gráfico falló: {e}"

    out["latency_ms"] = int((time.time() - t0) * 1000)
    return out


def ensure_eval_table():
    d.conn.execute("""
        CREATE TABLE IF NOT EXISTS eval_runs (
            id                  SERIAL PRIMARY KEY,
            run_at              TIMESTAMPTZ DEFAULT now(),
            model               TEXT,
            total_cases         INTEGER,
            sql_ok              INTEGER,
            structural_halluc   INTEGER,
            content_ok          INTEGER,
            content_halluc      INTEGER,
            chart_ok            INTEGER,
            palette_fail        INTEGER,
            avg_latency_ms      INTEGER,
            detail_json         JSONB
        )
    """)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save-json", default=None, help="Guardar el detalle completo en un archivo JSON")
    args = parser.parse_args()

    print(f"Modelo evaluado: {d.get_model_name()}")
    print(f"{len(CASES)} preguntas · sin caché · comparadas contra SQL de referencia\n")
    print(f"  {'pregunta':<70} {'SQL':<6} {'contenido':<10} {'gráfico':<8} paleta")
    print("─" * 115)

    results = []
    for case in CASES:
        r = run_case(case)
        results.append(r)
        sql_mark = "✓" if r["sql_ok"] else "✗ ALUC.ESTRUCTURAL"
        if not r["sql_ok"]:
            print(f"✗ {case['q'][:68]:<70} {sql_mark:<6}")
            if r["error"]:
                print(f"    → {r['error'][:140]}")
            continue
        content_mark = "✓" if r["content_ok"] else "✗ ALUC.CONTENIDO"
        chart_mark   = "✓" if r["chart_ok"] else "✗"
        palette_mark = "ok" if r["palette_ok"] else "FAIL"
        print(f"{'✓' if r['content_ok'] else '✗'} {case['q'][:68]:<70} {'ok':<6} "
              f"{content_mark:<10} {chart_mark:<8} {palette_mark}")
        if not r["content_ok"]:
            print(f"    → {r['detail'][:160]}")

    total = len(results)
    sql_ok_n   = sum(1 for r in results if r["sql_ok"])
    content_ok_n = sum(1 for r in results if r["sql_ok"] and r["content_ok"])
    chart_ok_n   = sum(1 for r in results if r["sql_ok"] and r["chart_ok"])
    palette_fail_n = sum(1 for r in results if r["sql_ok"] and not r["palette_ok"])
    latencies = [r["latency_ms"] for r in results if r.get("latency_ms")]
    avg_latency = int(sum(latencies) / len(latencies)) if latencies else 0

    print("─" * 115)
    print(f"SQL ejecutable (sin alucinación estructural): {sql_ok_n}/{total} ({100*sql_ok_n/total:.0f}%)")
    print(f"Respuesta correcta (sin alucinación de contenido), sobre los que ejecutaron: "
          f"{content_ok_n}/{sql_ok_n} ({100*content_ok_n/max(sql_ok_n,1):.0f}%)")
    print(f"Gráfico de familia correcta: {chart_ok_n}/{sql_ok_n} ({100*chart_ok_n/max(sql_ok_n,1):.0f}%)")
    print(f"Violaciones de paleta: {palette_fail_n}")
    print(f"Latencia promedio por pregunta: {avg_latency} ms")
    print(f"\nAlucinaciones totales: {total - sql_ok_n} estructurales + {sql_ok_n - content_ok_n} de contenido "
          f"= {total - content_ok_n}/{total} ({100*(total-content_ok_n)/total:.0f}%)")

    ensure_eval_table()
    d.conn.execute(
        "INSERT INTO eval_runs (model, total_cases, sql_ok, structural_halluc, content_ok, "
        "content_halluc, chart_ok, palette_fail, avg_latency_ms, detail_json) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (d.get_model_name(), total, sql_ok_n, total - sql_ok_n, content_ok_n,
         sql_ok_n - content_ok_n, chart_ok_n, palette_fail_n, avg_latency, json.dumps(results, default=str)),
    )
    print("\nCorrida guardada en eval_runs.")

    if args.save_json:
        with open(args.save_json, "w") as f:
            json.dump({"run_at": datetime.now(timezone.utc).isoformat(),
                       "model": d.get_model_name(), "results": results}, f, indent=2, default=str)
        print(f"Detalle guardado en {args.save_json}")


if __name__ == "__main__":
    main()
