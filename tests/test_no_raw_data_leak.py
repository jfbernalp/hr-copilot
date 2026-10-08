"""
test_no_raw_data_leak.py
-------------------------
Guardia de seguridad permanente: verifica que la generación de gráficos
(`app.dashboard._generate_chart_code`) nunca mande valores reales de celda
a Gemini — solo metadatos agregados (shape, dtypes, cardinalidad).

Motivo: `v_perfil_empleado` devuelve `nombre_completo` y `salario_actual` en
la misma fila. Antes del fix, `_generate_chart_code` mandaba
`df.head(5).to_string()` al LLM — es decir, nombres y salarios reales de
empleados viajaban al endpoint de Gemini. Este test construye un DataFrame
sintético con valores únicos y fáciles de reconocer (nunca datos reales de
la BD) y falla si cualquiera de esos valores aparece en el prompt enviado.

No hace llamadas reales a Gemini: monkeypatchea `d.vn._provider.generate`
para capturar el prompt y devolver código Plotly dummy. Costo: $0.

Uso:
    python tests/test_no_raw_data_leak.py
Sale con código 1 si se detecta una fuga de datos reales al prompt.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

import app.dashboard as d   # inicializa Vanna + conexión (misma ruta que ai_regression.py)

# Valores centinela: únicos, no pueden aparecer por coincidencia en el prompt
# (shape/dtypes/column names), a diferencia de "Juan" o "1000000" que sí podrían.
SENTINEL_NAME   = "Zzqvexotic Wbrfpqlmn"
SENTINEL_SALARY = 7913574.91
SENTINEL_EMAIL  = "zzqvexotic.wbrfpqlmn@novatech-sentinel.co"

FAKE_SENSITIVE_DF = pd.DataFrame({
    "nombre_completo":  [SENTINEL_NAME, "Otra Persona Ficticia"],
    "salario_actual":   [SENTINEL_SALARY, 3123456.78],
    "correo_corporativo": [SENTINEL_EMAIL, "otra.persona@novatech.co"],
    "anos_empresa":     [3, 7],
})


def _capture_provider_calls():
    """Monkeypatchea vn._provider.generate; devuelve (lista_de_prompts, restore_fn)."""
    captured = []
    original = d.vn._provider.generate

    def fake_generate(text, *args, **kwargs):
        captured.append(text)
        return "fig = go.Figure()\n", 0, 0

    d.vn._provider.generate = fake_generate

    def restore():
        d.vn._provider.generate = original

    return captured, restore


def main():
    captured, restore = _capture_provider_calls()
    try:
        d._generate_chart_code(
            "¿cómo se relacionan el salario y los años en la empresa?",
            "SELECT nombre_completo, salario_actual, correo_corporativo, anos_empresa FROM v_perfil_empleado",
            FAKE_SENSITIVE_DF,
        )
    finally:
        restore()

    assert len(captured) == 1, f"se esperaba 1 llamada al LLM, hubo {len(captured)}"
    prompt = captured[0]

    leaks = []
    for sentinel in (SENTINEL_NAME, str(SENTINEL_SALARY), SENTINEL_EMAIL, "Otra Persona Ficticia"):
        if sentinel in prompt:
            leaks.append(sentinel)

    print(f"Prompt capturado: {len(prompt)} caracteres")
    if leaks:
        print(f"✗ FUGA DE DATOS: valores reales de celda aparecen en el prompt a Gemini: {leaks}")
        sys.exit(1)

    # Verificación positiva: el prompt sigue teniendo metadatos útiles (no se rompió el fix).
    for expected in ("shape:", "dtypes", "cardinality", "nombre_completo", "salario_actual"):
        assert expected in prompt, f"metadato esperado ausente del prompt: {expected!r}"

    print("✓ Sin fuga de datos reales. Solo metadatos agregados llegan al prompt.")


if __name__ == "__main__":
    main()
