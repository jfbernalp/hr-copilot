"""
dashboard.py
------------
HR Copilot — Práxedes Edition
Styled to match Práxedes S.A.S. web design manual:
  - Montserrat font family
  - Colors: #ff8b00 orange, #383838 dark gray, #dddddd light gray, #ffffff white
  - Rounded corners (25px), flat backgrounds, clean professional layout

Run from project root:
    python app/dashboard.py
"""

import os
import re
import sys
import json
import time
import hashlib
import sqlite3
from datetime import datetime
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots
import google.genai as genai
import dash
from dash import dcc, html, Input, Output, State, callback_context, ALL
from dash.exceptions import PreventUpdate
from dotenv import load_dotenv
from vanna.legacy.base.base import VannaBase

# ── Paths & Config ─────────────────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR    = (
    os.path.dirname(_SCRIPT_DIR)
    if os.path.basename(_SCRIPT_DIR) == "app"
    else _SCRIPT_DIR
)
DB_PATH    = os.path.join(BASE_DIR, "data", "hr_analytics.db")
CHROMA_DIR = os.path.join(BASE_DIR, "chroma_db")

sys.path.insert(0, _SCRIPT_DIR)
sys.path.insert(0, BASE_DIR)
from rls import rls_intercept, ROLES, DEPT_NAMES
from setup.train_vanna import (DDL, DDL_SYNTH, DOCUMENTATION, KPI_DOCUMENTATION,
                               SYNTH_DOCUMENTATION, VISUALIZATION_DOCUMENTATION,
                               EXAMPLES, KPI_EXAMPLES, SYNTH_EXAMPLES)
import kpi_catalog
import flask
from auth import check_login

load_dotenv(os.path.join(BASE_DIR, ".env"))
API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    print("ERROR: No API key found. Add GEMINI_API_KEY or GOOGLE_API_KEY to .env")
    sys.exit(1)

COST_INPUT_PER_1M  = 0.075
COST_OUTPUT_PER_1M = 0.30


# ── Vanna + Gemini ─────────────────────────────────────────────────────────────
class HRCopilot(VannaBase):
    def __init__(self, config=None):
        VannaBase.__init__(self, config=config)
        self._client    = genai.Client(api_key=config.get("api_key"))
        self.model_name = config.get("model", "gemini-2.5-flash")
        self.last_input_tokens = self.last_output_tokens = self.last_total_tokens = 0

    def system_message(self, message): return message
    def user_message(self, message):   return message
    def assistant_message(self, message): return message

    def generate_embedding(self, data, **kwargs): return [0.0]
    def get_related_ddl(self, question, **kwargs): return [DDL, DDL_SYNTH]
    def get_related_documentation(self, question, **kwargs): return [DOCUMENTATION, KPI_DOCUMENTATION, SYNTH_DOCUMENTATION, VISUALIZATION_DOCUMENTATION]
    def get_similar_question_sql(self, question, **kwargs): return EXAMPLES + KPI_EXAMPLES + SYNTH_EXAMPLES
    def add_ddl(self, ddl, **kwargs): pass
    def add_documentation(self, documentation, **kwargs): pass
    def add_question_sql(self, question, sql, **kwargs): pass
    def remove_training_data(self, id, **kwargs): pass
    def get_training_data(self, **kwargs): return pd.DataFrame()

    def submit_prompt(self, prompt, **kwargs):
        text = (
            "\n".join([p if isinstance(p, str) else str(p) for p in prompt])
            if isinstance(prompt, list) else str(prompt)
        )
        text += (
            "\n\nIMPORTANT: The database has these 18 tables (lowercase): "
            "employees, departments, job_roles, satisfaction (core); "
            "employment_dates, attendance_monthly, medical_leaves, payroll_monthly, "
            "payroll_runs, salary_bands, headcount_history, vacancies, survey_cycles, "
            "survey_responses, training_programs, training_participants, "
            "company_financials, vacation_balances (monthly series 2024-06..2026-05). "
            "Never invent table names. month columns are TEXT 'YYYY-MM'."
        )
        response = self._client.models.generate_content(
            model=self.model_name,
            contents=text,
            config=genai.types.GenerateContentConfig(
                thinking_config=genai.types.ThinkingConfig(thinking_budget=0)
            )
        )
        try:
            self.last_input_tokens  = response.usage_metadata.prompt_token_count
            self.last_output_tokens = response.usage_metadata.candidates_token_count
            self.last_total_tokens  = response.usage_metadata.total_token_count
        except Exception:
            pass
        return response.text


# ── Initialize Vanna ───────────────────────────────────────────────────────────
print("Initializing HR Copilot — Práxedes Edition...")

def _make_copilot():
    """RAG dual-mode. USE_CHROMA=1 → ChromaDB local (recupera top-K fragmentos,
    menos tokens por consulta). Default → modo estático: todo el corpus viaja en
    cada prompt (sin ChromaDB en memoria; apto para Render Free Tier)."""
    cfg = {"api_key": API_KEY, "model": "gemini-2.5-flash",
           "chroma_persist_directory": CHROMA_DIR}
    if os.getenv("USE_CHROMA", "0") == "1":
        try:
            from setup.train_vanna import HRCopilot as ChromaCopilot
            v = ChromaCopilot(config=cfg)
            if len(v.get_training_data()) == 0:
                raise RuntimeError("ChromaDB vacío — corre: python setup/train_vanna.py")
            print("  RAG: ChromaDB activo (" + CHROMA_DIR + ")")
            return v
        except Exception as exc:
            print(f"  RAG: ChromaDB no disponible ({exc}); usando modo estático")
    return HRCopilot(config=cfg)

vn = _make_copilot()
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.execute('''
    CREATE TABLE IF NOT EXISTS usage_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        question TEXT,
        tokens_input INTEGER,
        tokens_output INTEGER,
        cost REAL,
        sql_generated TEXT
    )
''')
# Migraciones aditivas de usage_metrics (idempotentes)
for _col, _typ in [("sql_generated", "TEXT"), ("role", "TEXT"), ("latency_ms", "INTEGER"),
                   ("cache_hit", "INTEGER"), ("success", "INTEGER")]:
    try:
        conn.execute(f"ALTER TABLE usage_metrics ADD COLUMN {_col} {_typ}")
    except Exception:
        pass
conn.execute('''
    CREATE TABLE IF NOT EXISTS query_cache (
        question_hash TEXT PRIMARY KEY,
        question      TEXT,
        sql_generated TEXT,
        result_json   TEXT
    )
''')
conn.commit()
vn.run_sql = lambda sql: pd.read_sql_query(sql, conn)
vn.run_sql_is_set = True
print("  Ready.")

# Catálogo de cargos para el segmentador del dashboard estático.
try:
    JOB_ROLES = dict(pd.read_sql_query("SELECT role_id, role_name FROM job_roles ORDER BY role_name", conn).values)
except Exception:
    JOB_ROLES = {}

# ── Plotly generation prompt ────────────────────────────────────────────────────
# Sent directly to Gemini on every chart request — bypasses Vanna's RAG so
# palette and chart-type rules are ALWAYS in the context window.
PLOTLY_PROMPT = """\
You are a data visualization expert for Práxedes S.A.S. Generate Python/Plotly code.

━━━ MANDATORY: PRÁXEDES COLOR PALETTE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Source: Manual Web Práxedes S.A.S. Use ONLY these colors. Never use defaults.

  '#ff8b00'  Naranjado Práxedes  → primary bars, titles, highlights
  '#383838'  Gris Oscuro         → text, dark bars, stable/neutral state
  '#dddddd'  Gris Claro          → neutral bars, background reference
  '#ffffff'  Blanco              → container backgrounds
  '#5b8db8'  Steel Blue          → Male gender, informational
  '#e67e22'  Amber               → medium risk, secondary accent
  '#c0392b'  Deep Red            → Attrition=Yes, high risk, alert

Semantic maps (apply automatically when column matches):
  Gender:    color_discrete_map={'Female': '#ff8b00', 'Male': '#5b8db8'}
  Attrition: color_discrete_map={'Yes': '#c0392b', 'No': '#383838'}
  OverTime:  color_discrete_map={'Yes': '#ff8b00', 'No': '#dddddd'}

Multi-series colorway (use in this order when 3+ categories):
  ['#ff8b00', '#383838', '#5b8db8', '#e67e22', '#dddddd', '#c0392b']

NEVER use: Plotly default blue/red/green, purple, teal, pink, or unlisted colors.

━━━ MANDATORY: CHART TYPE SELECTION ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Check the rules IN ORDER — first match wins. A vertical bar chart is the LAST
resort: before outputting bars you must have ruled out T1, S1, P1, D1 and C1.
Defaulting to bars when a time/proportion/correlation shape exists is a BUG.

T1 — TIME SERIES. Applies when any column is month/mes/cycle/ciclo/quarter/
     year/fecha/date or its values look like 'YYYY-MM' or 'YYYYQn'.
     NEVER use vertical bars for a time axis with more than 6 points.
  a) 1 numeric            → px.line(markers=True, color_discrete_sequence=['#ff8b00'])
  b) 2-3 numerics, same scale → multi-line px.line (colorway order)
  c) numeric + categorical (e.g. month + department_name):
       ≤4 categories → px.line(color=<categorical>, markers=True)
       >4 categories → go.Heatmap(z=pivot, colorscale=[[0,'#f5f5f5'],[0.55,'#ff8b00'],[1,'#c0392b']])
  d) volume (count/total/days/usd/cost) + rate (pct/rate/ratio/tasa) together →
       make_subplots(specs=[[{'secondary_y': True}]]):
       go.Bar volume '#dddddd' + go.Scatter line rate '#ff8b00' on secondary_y
  e) two complementary flows (hires/exits, voluntary/involuntary, in/out) →
       go.Bar stacked per month ('#ff8b00' / '#c0392b'), barmode='relative'
       with the second flow negated when they oppose each other
  f) cumulative/acumulado question → px.area (line_color '#ff8b00',
       fillcolor 'rgba(255,139,0,0.25)')

S1 — SINGLE ROW result → go.Indicator(mode='number', number_font_color='#ff8b00').
     NEVER a bar chart for one value.

D1 — DISTRIBUTION of a NUMERIC attribute (question is "distribución de <edad/
     salario/antigüedad/años/income/age...>", or the label column contains ordered
     numeric bands/ranges/buckets like '18-25', '0-2 años', levels 1-5) →
     raw values → px.histogram(nbins=25, color_discrete_sequence=['#ff8b00'])
     pre-grouped bands → vertical px.bar in band order, single color '#ff8b00'
     per category → px.box(color_discrete_sequence=['#ff8b00','#383838'])
     A pie chart here is ALWAYS WRONG: ordered buckets are not a composition.

P1 — PROPORTION / COMPOSITION across NOMINAL categories with no inherent order
     (gender, department, marital status, leave type; question says proporción/
     porcentaje/share/composición), 2-6 rows →
     px.pie(hole=0.45, color_discrete_sequence=['#ff8b00','#383838','#5b8db8','#e67e22'])
     >6 rows → horizontal bars instead. Check D1 first: if categories are ordered
     numeric bands, D1 wins.

C1 — CORRELATION / RELATIONSHIP (two numeric columns, many rows; question says
     relación/correlación/vs/afecta/impacto) →
     px.scatter(opacity=0.6, color_discrete_sequence=['#ff8b00'])
     If a third categorical exists → color=<categorical> with semantic maps.

R1 — RANKING / COMPARISON (one categorical + one numeric, no time axis):
     >6 rows → horizontal bar orientation='h' sorted ascending, '#ff8b00'
     ≤6 rows → vertical bar, color_discrete_sequence=['#ff8b00','#383838','#5b8db8']
     BUT if X is sequential (JobLevel, YearsAtCompany, Education, age/tenure
     bands) → px.line(markers=True): progressions are lines, not bars.

G1 — TWO CATEGORICALS + numeric (no time axis) → px.bar barmode='group' with
     semantic color maps (Gender/Attrition/OverTime) or colorway.

M1 — MULTIPLE METRIC COLUMNS on the same scale per category (e.g. 4 satisfaction
     dimensions 1-5) → 4-6 metrics for ONE entity → go.Scatterpolar (radar,
     fill='toself', line '#ff8b00'); otherwise pd.melt + grouped bars.

━━━ OUTPUT FORMAT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return ONLY executable Python. Start with imports. Assign result to `fig`.
Do NOT call fig.show() or fig.write_html(). No markdown fences.
"""

_PRAXEDES_HEX = {
    '#ff8b00', '#383838', '#5b8db8', '#e67e22', '#dddddd', '#c0392b',
    '#ffffff', '#fff3e0', '#cc6f00', '#666666', '#f5f5f5',
}
_COLORWAY = ['#ff8b00', '#383838', '#5b8db8', '#e67e22', '#dddddd', '#c0392b']


def _enforce_praxedes_palette(fig: go.Figure) -> go.Figure:
    """Post-process: replace any non-Práxedes color on all traces."""
    for i, trace in enumerate(fig.data):
        fallback = _COLORWAY[i % len(_COLORWAY)]
        try:
            mc = trace.marker.color
            if isinstance(mc, str) and mc.lower() not in _PRAXEDES_HEX:
                trace.marker.color = fallback
        except Exception:
            pass
        try:
            lc = trace.line.color
            if isinstance(lc, str) and lc.lower() not in _PRAXEDES_HEX:
                trace.line.color = fallback
        except Exception:
            pass
    return fig


_last_chart_usage = {"in": 0, "out": 0}

def _generate_chart_code(question: str, sql: str, df: pd.DataFrame) -> str:
    """Calls Gemini directly with the constrained chart prompt — not Vanna RAG."""
    df_sample = df.head(5).to_string(index=False)
    df_cardinality = {
        col: int(df[col].nunique())
        for col in df.select_dtypes(include=["object", "category"]).columns
    }
    user_msg = (
        f"Question: {question}\n\n"
        f"SQL used:\n{sql}\n\n"
        f"DataFrame info:\n"
        f"  shape: {df.shape[0]} rows × {df.shape[1]} cols\n"
        f"  dtypes:\n{df.dtypes.to_string()}\n\n"
        f"  first 5 rows:\n{df_sample}\n\n"
        f"  categorical cardinality: {df_cardinality}\n\n"
        "Generate the Plotly chart following ALL mandatory rules above."
    )
    response = vn._client.models.generate_content(
        model=vn.model_name,
        contents=PLOTLY_PROMPT + "\n\n" + user_msg,
        config=genai.types.GenerateContentConfig(
            thinking_config=genai.types.ThinkingConfig(thinking_budget=0)
        ),
    )
    try:
        _last_chart_usage["in"]  = response.usage_metadata.prompt_token_count
        _last_chart_usage["out"] = response.usage_metadata.candidates_token_count
    except Exception:
        pass
    return response.text


# ── SQL safety net ─────────────────────────────────────────────────────────────
def clean_sql(sql: str) -> str:
    """Strips markdown fences and validates parenthesis balance."""
    sql = re.sub(r"```sql|```", "", sql).strip()
    if sql.count("(") != sql.count(")"):
        raise ValueError(
            f"Generated SQL has unbalanced parentheses "
            f"({sql.count('(')} open, {sql.count(')')} close). "
            "Try rephrasing your question."
        )
    return sql


# ── Chart generation ────────────────────────────────────────────────────────────
# Primary path: ask Gemini (already trained with Plotly examples) to generate
# the chart code. Gemini has been trained to pick the correct chart type.
# Fallback path: smart_chart() is used only if Gemini's code raises an exception.

def _apply_praxedes_theme(fig: go.Figure) -> go.Figure:
    """Applies the Práxedes color theme to any Plotly figure."""
    fig.update_layout(
        paper_bgcolor=C["white"],
        plot_bgcolor=C["gray_bg"],
        font=dict(color=C["gray_dark"], family=FONT, size=11),
        title=dict(font=dict(color=C["gray_dark"], size=14, family=FONT)),
        xaxis=dict(gridcolor=C["gray_light"], zerolinecolor=C["gray_light"]),
        yaxis=dict(gridcolor=C["gray_light"], zerolinecolor=C["gray_light"]),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=C["gray_mid"])),
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig


def generate_chart(df: pd.DataFrame, question: str, sql: str) -> go.Figure:
    """
    Primary path: calls Gemini directly with PLOTLY_PROMPT (palette + chart-type
    rules always in context). Falls back to smart_chart() only on exception.
    """
    if df is None or len(df) == 0:
        return go.Figure()

    _last_chart_usage["in"] = _last_chart_usage["out"] = 0
    try:
        plotly_code = _generate_chart_code(question, sql, df)
        fig = vn.get_plotly_figure(plotly_code=plotly_code, df=df)
        fig = _enforce_praxedes_palette(fig)
        return _apply_praxedes_theme(fig)
    except Exception as primary_err:
        print(f"Gemini chart error — falling back to smart_chart: {primary_err}")

    colorway = [
        C["orange"], C["gray_dark"], C["info"],
        C["warning"], C["gray_light"], C["danger"],
    ]
    fig = smart_chart(df, question, colorway)
    return _apply_praxedes_theme(fig)


# ── smart_chart: rule-based fallback ──────────────────────────────────────────
def _is_cat(series: pd.Series) -> bool:
    """Robust categorical detection — handles pandas 2.x StringDtype."""
    dt = series.dtype
    return (
        dt == object
        or "str" in str(dt).lower()
        or "object" in str(dt).lower()
        or str(dt) == "category"
        or pd.api.types.is_string_dtype(dt)
    )

def _cat_cols(df):  return [c for c in df.columns if _is_cat(df[c])]
def _num_cols(df):  return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]

def _time_cols(df):
    """Only match time keywords as whole word tokens (avoids 'monthly' false positives)."""
    kw = {"year", "month", "date", "time", "periodo", "mes", "ano", "trimestre", "quarter"}
    return [
        c for c in df.columns
        if any(t in kw for t in re.split(r"[_\s]", c.lower()))
    ]


def smart_chart(df: pd.DataFrame, question: str, colorway: list) -> go.Figure:
    """
    Rule-based chart selector used as fallback when Gemini chart generation fails.
    Applies the same visual logic encoded in VISUALIZATION_DOCUMENTATION.
    """
    if df is None or len(df) == 0:
        return go.Figure()

    q     = question.lower()
    nrows = len(df)
    cats  = _cat_cols(df)
    nums  = _num_cols(df)
    times = _time_cols(df)

    # 1. Single row → KPI scorecard
    if nrows == 1:
        fig = go.Figure()
        for i, col in enumerate(nums[:4]):
            fig.add_trace(go.Indicator(
                mode="number",
                value=float(df.iloc[0][col]),
                title={"text": col.replace("_", " ").title()},
                domain={"row": 0, "column": i},
                number={"font": {"size": 48, "color": colorway[i % len(colorway)]}},
            ))
        fig.update_layout(
            grid={"rows": 1, "columns": max(len(nums[:4]), 1)},
            title=question[:60],
        )
        return fig

    # 2. Serie temporal → línea / heatmap / multilínea (nunca barras por defecto)
    if times and nums:
        t = times[0]
        other_cats = [c for c in cats if c != t]
        y_cols = [c for c in nums if c not in times]
        if y_cols and other_cats:
            cat = other_cats[0]
            if df[cat].nunique() > 4:
                pv = df.pivot_table(index=cat, columns=t, values=y_cols[0], aggfunc="sum").fillna(0)
                fig = go.Figure(go.Heatmap(
                    z=pv.values, x=list(pv.columns), y=list(pv.index),
                    colorscale=[[0, "#f5f5f5"], [0.55, "#ff8b00"], [1, "#c0392b"]]))
                fig.update_layout(title=question[:60])
                return fig
            return px.line(df, x=t, y=y_cols[0], color=cat, markers=True,
                           title=question[:60], color_discrete_sequence=colorway)
        if y_cols:
            fig = px.line(df, x=t, y=y_cols[:3], markers=True, title=question[:60],
                          color_discrete_sequence=colorway)
            fig.update_traces(line=dict(width=2.5))
            return fig

    # 3. Two categorical dims + one numeric → grouped bar (Rule 1 from training)
    if len(cats) >= 2 and nums:
        fig = px.bar(
            df, x=cats[0], y=nums[0], color=cats[1],
            barmode="group", title=question[:60],
            text=df[nums[0]].round(1),
            color_discrete_sequence=colorway,
        )
        fig.update_traces(textposition="outside")
        return fig

    # 4. Percentage + few cats → donut
    pct_kw = {"pct", "percent", "porcentaje", "ratio", "rate", "tasa", "proporcion"}
    pct = [c for c in nums if any(k in c.lower() for k in pct_kw)]
    if pct and cats and nrows <= 6:
        fig = px.pie(
            df, names=cats[0], values=pct[0], title=question[:60],
            color_discrete_sequence=colorway, hole=0.38,
        )
        fig.update_traces(textposition="inside", textinfo="percent+label")
        return fig

    # 5. Distribution intent → histogram or box
    dist_kw = {"distribucion", "distribución", "distribution", "spread",
               "variacion", "variación", "dispersion", "rango"}
    if any(k in q for k in dist_kw):
        if cats and nums:
            fig = px.box(
                df, x=cats[0], y=nums[0], title=question[:60],
                color=cats[0], color_discrete_sequence=colorway, points="outliers",
            )
            return fig
        if nums:
            fig = px.histogram(
                df, x=nums[0], title=question[:60],
                nbins=25, color_discrete_sequence=[colorway[0]],
            )
            return fig

    # 6. Exactly 2 rows + category → horizontal comparison bar
    if nrows == 2 and cats and nums:
        cnt_kw = {"count", "total", "n_", "empleados", "employees", "headcount"}
        metrics = [c for c in nums if not any(k in c.lower() for k in cnt_kw)] or nums
        fig = go.Figure()
        for i, col in enumerate(metrics[:2]):
            fig.add_trace(go.Bar(
                y=df[cats[0]], x=df[col], name=col.replace("_", " ").title(),
                orientation="h", marker_color=colorway[i % len(colorway)],
                text=df[col].round(1), textposition="outside",
            ))
        fig.update_layout(barmode="group", title=question[:60])
        return fig

    # 7. Many rows + category → horizontal bar
    if cats and nums and nrows > 6:
        sdf = df.head(20).sort_values(nums[0], ascending=True)
        fig = go.Figure(go.Bar(
            y=sdf[cats[0]], x=sdf[nums[0]], orientation="h",
            marker_color=colorway[0],
            text=sdf[nums[0]].round(1), textposition="outside",
        ))
        fig.update_layout(title=question[:60])
        return fig

    # 8. Few rows + category → vertical bar
    if cats and nums:
        fig = px.bar(
            df, x=cats[0], y=nums[0], title=question[:60],
            color=cats[0], text=df[nums[0]].round(1),
            color_discrete_sequence=colorway,
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(showlegend=False)
        return fig

    # 9. Pure numeric → line
    if len(nums) >= 2:
        fig = px.line(
            df, y=nums[:3], title=question[:60],
            color_discrete_sequence=colorway, markers=True,
        )
        return fig

    return go.Figure()


# ── KPI helpers ────────────────────────────────────────────────────────────────
def get_kpis() -> dict:
    queries = {
        "headcount":    "SELECT COUNT(*) AS n FROM employees",
        "attrition":    "SELECT ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) AS r FROM employees",
        "avg_income":   "SELECT ROUND(AVG(MonthlyIncome),0) AS r FROM employees",
        "overtime_pct": "SELECT ROUND(100.0*SUM(CASE WHEN OverTime='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) AS r FROM employees",
        "avg_perf":     "SELECT ROUND(AVG(PerformanceRating),2) AS r FROM satisfaction",
        "avg_sat":      "SELECT ROUND(AVG(JobSatisfaction),2) AS r FROM satisfaction",
    }
    result = {}
    for key, sql in queries.items():
        try:
            val = pd.read_sql(sql, conn).iloc[0, 0]
            result[key] = int(val) if key in ("headcount", "avg_income") else float(val)
        except Exception as e:
            print(f"KPI error [{key}]: {e}")
            result[key] = 0
    return result


# ── Query cache ────────────────────────────────────────────────────────────────
def _question_hash(question: str) -> str:
    return hashlib.md5(question.strip().lower().encode()).hexdigest()

def cache_lookup(question: str):
    try:
        row = pd.read_sql(
            "SELECT sql_generated, result_json FROM query_cache WHERE question_hash=?",
            conn, params=(_question_hash(question),)
        )
        if len(row):
            return row.iloc[0]["sql_generated"], row.iloc[0]["result_json"]
    except Exception:
        pass
    return None, None

def cache_store(question: str, sql: str, result_json: str):
    try:
        conn.execute(
            "INSERT OR REPLACE INTO query_cache"
            "(question_hash, question, sql_generated, result_json) VALUES(?,?,?,?)",
            (_question_hash(question), question, sql, result_json),
        )
        conn.commit()
    except Exception:
        pass


# ── Pipeline compartido (chat + dashboard) ──────────────────────────────────────
def _log_usage(question, role, tokens_in, tokens_out, cost, sql, cache_hit, success, t0):
    """Registra TODA consulta (incl. cache hits y errores) para la página de métricas."""
    try:
        conn.execute(
            "INSERT INTO usage_metrics (timestamp, question, tokens_input, tokens_output, "
            "cost, sql_generated, role, latency_ms, cache_hit, success) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), question, tokens_in, tokens_out,
             cost, sql, role, int((time.time() - t0) * 1000), int(cache_hit), int(success)),
        )
        conn.commit()
    except Exception:
        pass


def process_question(question: str, role: str | None) -> dict:
    """
    Ejecuta el pipeline completo Text-to-SQL y devuelve un dict serializable
    (apto para guardar en dcc.Store y re-renderizar sin volver a llamar a Gemini).
    """
    role = role or "hr_admin"
    t0 = time.time()
    out = {
        "question": question, "sql": None, "fig_json": None,
        "columns": [], "rows": [], "nrows": 0, "error": None, "from_cache": False,
    }
    tokens_in = tokens_out = 0
    cost = 0.0

    # 1. Generar SQL (con cache)
    cached_sql, _ = cache_lookup(question)
    if cached_sql:
        sql = cached_sql
        out["from_cache"] = True
    else:
        try:
            sql = clean_sql(vn.generate_sql(question=question, allow_llm_to_see_data=True))
            tokens_in  = vn.last_input_tokens
            tokens_out = vn.last_output_tokens
            cost = (tokens_in * COST_INPUT_PER_1M + tokens_out * COST_OUTPUT_PER_1M) / 1_000_000
        except Exception as e:
            out["error"] = f"No pude generar el SQL: {e}"
            _log_usage(question, role, tokens_in, tokens_out, cost, None, False, False, t0)
            return out
    out["sql"] = sql

    # 2. Interceptor RLS
    try:
        sql_run = rls_intercept(sql, role, conn, user=current_session()[0])
    except PermissionError as pe:
        out["error"] = f"Acceso denegado por tu rol: {pe}"
        _log_usage(question, role, tokens_in, tokens_out, cost, sql, out["from_cache"], False, t0)
        return out

    # 3. Ejecutar
    try:
        df = pd.read_sql_query(sql_run, conn)
        if not cached_sql:
            cache_store(question, sql, "")
    except Exception as e:
        out["error"] = f"Error ejecutando la consulta: {e}"
        _log_usage(question, role, tokens_in, tokens_out, cost, sql, out["from_cache"], False, t0)
        return out

    out["nrows"]   = len(df)
    out["columns"] = list(df.columns)
    out["rows"]    = df.head(50).astype(str).values.tolist()

    # 4. Gráfico (segunda llamada a Gemini — suma tokens del chart)
    if len(df) > 0:
        try:
            fig = generate_chart(df, question, sql)
            out["fig_json"] = fig.to_json()
            tokens_in  += _last_chart_usage["in"]
            tokens_out += _last_chart_usage["out"]
            cost += (_last_chart_usage["in"] * COST_INPUT_PER_1M
                     + _last_chart_usage["out"] * COST_OUTPUT_PER_1M) / 1_000_000
        except Exception as e:
            print(f"Chart error en process_question: {e}")

    _log_usage(question, role, tokens_in, tokens_out, cost, sql, out["from_cache"], True, t0)
    return out


# ── Design tokens ──────────────────────────────────────────────────────────────
C = {
    "orange":       "#ff8b00",
    "orange_dark":  "#cc6f00",
    "orange_light": "#fff3e0",
    "gray_dark":    "#383838",
    "gray_mid":     "#666666",
    "gray_light":   "#dddddd",
    "gray_bg":      "#f5f5f5",
    "white":        "#ffffff",
    "danger":       "#c0392b",   # Deep Red — alert, attrition, risk
    "success":      "#383838",   # Dark Gray — stable, neutral positive
    "info":         "#5b8db8",   # Steel Blue — Male gender, informational
    "warning":      "#e67e22",   # Amber — medium risk, overtime
}
FONT = "'Montserrat', sans-serif"

SUGGESTED = [
    "¿Cuál es la tasa de rotación general?",
    "¿Qué departamentos tienen la mayor rotación?",
    "¿Existe una brecha salarial de género?",
    "Salario promedio por nivel de cargo",
    "¿Cómo afectan las horas extra a la rotación?",
    "Distribución de empleados por departamento",
]


# ── UI helpers ─────────────────────────────────────────────────────────────────
def _accent_rgba(hex_color, alpha):
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def kpi_card(icon, label, value, unit="", color=None, sublabel="", trend=None):
    accent = color or C["orange"]

    trend_pill = None
    if trend:
        # Paleta Práxedes: positivo en gris oscuro, negativo en rojo profundo (sin verde).
        t_color = C["gray_dark"] if trend["dir"] == "up" else (C["danger"] if trend["dir"] == "down" else C["gray_mid"])
        t_arrow = "↗" if trend["dir"] == "up" else ("↘" if trend["dir"] == "down" else "→")
        trend_pill = html.Div(f"{t_arrow} {trend['value']}", style={
            "background": _accent_rgba(t_color, 0.10), "color": t_color, "padding": "4px 9px",
            "borderRadius": "25px", "fontSize": "11px", "fontWeight": "700", "marginLeft": "auto",
        })

    return html.Div([
        html.Div([
            html.Div(icon, style={"fontSize": "20px", "background": _accent_rgba(accent, 0.12), "color": accent,
                     "width": "42px", "height": "42px", "borderRadius": "50%", "display": "flex",
                     "alignItems": "center", "justifyContent": "center", "marginRight": "10px"}),
            trend_pill,
        ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "16px"}),

        html.Div([
            html.Span(str(value), style={"fontSize": "40px", "fontWeight": "900", "color": C["gray_dark"], "lineHeight": "1", "fontFamily": FONT}),
            html.Span(f" {unit}", style={"fontSize": "15px", "fontWeight": "700", "color": C["gray_mid"]}) if unit else None,
        ], style={"marginBottom": "10px"}),

        html.Div([
            html.Div(label, style={"fontSize": "11px", "fontWeight": "800", "color": C["gray_dark"], "textTransform": "uppercase", "letterSpacing": "0.05em"}),
            html.Div(sublabel, style={"fontSize": "11px", "color": C["gray_mid"], "fontWeight": "500", "marginTop": "2px"}) if sublabel else None,
        ]),
    ], className="kpi-card-hover", style={
        "background": C["white"], "borderRadius": "25px", "padding": "24px",
        "flex": "1", "minWidth": "190px",
        "boxShadow": "0 4px 15px rgba(0,0,0,0.03)",
        "border": "1px solid rgba(0,0,0,0.05)",
        "transition": "transform 0.3s ease, box-shadow 0.3s ease",
    })

def _separator(color=None):
    return html.Div(style={
        "height": "4px", "borderRadius": "25px",
        "background": color or C["gray_light"], "margin": "25px 0",
    })

def _panel_header(label, icon=""):
    return html.Div([
        html.Div(icon, style={"fontSize": "18px"}) if icon else None,
        html.Span(label, style={
            "fontSize": "15px", "fontWeight": "800", "color": C["gray_dark"],
            "letterSpacing": "-0.01em"
        }),
    ], style={"display": "flex", "alignItems": "center", "gap": "10px", "marginBottom": "20px"})


# ── Layout ─────────────────────────────────────────────────────────────────────
app = dash.Dash(__name__, title="HR Copilot — Práxedes", suppress_callback_exceptions=True)
server = app.server
server.secret_key = os.getenv("SECRET_KEY") or os.urandom(24).hex()


def current_session():
    """(username, role) desde la sesión server-side de Flask. La sesión es la
    fuente de verdad del rol — el dcc.Store del navegador es solo UX."""
    try:
        return flask.session.get("username"), flask.session.get("role")
    except Exception:
        return None, None

app.index_string = """
<!DOCTYPE html>
<html>
<head>
    {%metas%}
    <title>{%title%}</title>
    {%favicon%}
    {%css%}
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #f5f5f5; color: #383838; font-family: 'Montserrat', sans-serif; overflow-x: hidden; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #f5f5f5; }
        ::-webkit-scrollbar-thumb { background: #dddddd; border-radius: 3px; }
        input:focus { outline: none !important; box-shadow: 0 0 0 3px rgba(255,139,0,0.2) !important; border-color: #ff8b00 !important; }
        button:hover { opacity: 0.9; transform: scale(1.02); }
        button { transition: all 0.2s ease; }
        
        /* Glassmorphism & Hover effects */
        .kpi-card-hover:hover { transform: translateY(-5px) !important; box-shadow: 0 10px 25px rgba(255,139,0,0.15) !important; border-color: #ff8b00 !important; }
        .glass-panel { background: rgba(255, 255, 255, 0.85); backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.3); }
        
        /* Fade In Animation */
        .fade-in-up { animation: fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) forwards; opacity: 0; transform: translateY(20px); }
        @keyframes fadeInUp { to { opacity: 1; transform: translateY(0); } }
        
        .delay-1 { animation-delay: 0.1s; }
        .delay-2 { animation-delay: 0.2s; }
        .delay-3 { animation-delay: 0.3s; }
    </style>
</head>
<body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body>
</html>
"""

def _empty_chart():
    return go.Figure().update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=C["gray_light"], family=FONT),
        xaxis=dict(showgrid=False, zeroline=False, visible=False),
        yaxis=dict(showgrid=False, zeroline=False, visible=False),
        annotations=[dict(
            text="Visualización interactiva aparecerá aquí.",
            x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False,
            font=dict(color=C["gray_light"], size=14, family=FONT, weight=600),
        )],
    )


def _hero(title: str, subtitle: str):
    """Banner superior oscuro con círculos decorativos naranja (Manual Web Práxedes)."""
    circle = lambda d, color, top, left, op=1: html.Div(style={
        "position": "absolute", "width": d, "height": d, "borderRadius": "50%",
        "background": color, "top": top, "left": left, "opacity": op})
    return html.Div([
        circle("160px", C["orange"], "-60px", "70%"),
        circle("70px", C["orange"], "55%", "60%", 0.6),
        circle("110px", "rgba(255,255,255,0.06)", "30%", "85%"),
        html.Div([
            html.Div("PEOPLE ANALYTICS", style={"color": C["orange"], "fontSize": "11px",
                     "fontWeight": "800", "letterSpacing": "0.15em", "marginBottom": "10px"}),
            html.H1(title, style={"color": C["white"], "fontSize": "30px", "fontWeight": "900",
                     "margin": "0 0 8px 0", "fontFamily": FONT}),
            html.P(subtitle, style={"color": C["gray_light"], "fontSize": "13px", "margin": "0", "maxWidth": "640px"}),
        ], style={"position": "relative", "zIndex": 2}),
    ], style={"background": C["gray_dark"], "borderRadius": "25px", "padding": "36px 40px",
              "marginBottom": "30px", "position": "relative", "overflow": "hidden"})


def _navbar(active_page="dashboard"):
    navs = [
        ("Dashboard", "/dashboard", "dashboard"),
        ("KPIs", "/kpis", "kpis"),
        ("Métricas", "/metrics", "metrics")
    ]
    
    # Pestañas estilo "píldora" (Manual Web: contenedor gris claro, separadores
    # verticales finos, opción activa en naranja + Montserrat Black).
    items = []
    for i, (label, href, page_id) in enumerate(navs):
        is_active = (active_page == page_id)
        items.append(dcc.Link(label, href=href, style={
            "color": C["orange"] if is_active else C["gray_dark"],
            "fontWeight": "900" if is_active else "700",
            "fontSize": "13px", "textDecoration": "none", "padding": "0 18px",
            "transition": "all 0.2s ease",
        }))
        if i < len(navs) - 1:
            items.append(html.Div(style={"width": "1px", "height": "15px", "background": C["gray_light"]}))

    pill = html.Div(items, style={
        "display": "flex", "alignItems": "center", "background": C["gray_bg"],
        "borderRadius": "25px", "padding": "12px 12px",
    })

    return html.Div([
        html.Div([
            html.Div(style={"width": "18px", "height": "18px", "background": C["orange"], "borderRadius": "5px", "marginRight": "10px"}),
            html.Span("HR Copilot", style={"fontWeight": "900", "color": C["gray_dark"], "fontSize": "18px"})
        ], style={"display": "flex", "alignItems": "center"}),
        pill,
        dcc.Link("Salir →", href="/", style={"color": C["gray_mid"], "textDecoration": "none", "fontSize": "13px", "fontWeight": "700"}),
    ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center",
              "padding": "16px 40px", "background": C["white"], "borderBottom": "1px solid " + C["gray_light"]})

def _logo(dark_bg=False):
    return html.Div([
        html.Div(style={"width": "20px", "height": "20px", "background": C["orange"], "borderRadius": "5px", "marginRight": "10px"}),
        html.Span("HR Copilot", style={"color": C["white"] if dark_bg else C["gray_dark"], "fontWeight": "900", "fontSize": "18px"}),
    ], style={"display": "flex", "alignItems": "center"})


def layout_login():
    deco = lambda d, color, top, left, op=1: html.Div(style={
        "position": "absolute", "width": d, "height": d, "borderRadius": "50%",
        "background": color, "top": top, "left": left, "opacity": op, "zIndex": 1})
    return html.Div([
        html.Div([
            # ── Panel izquierdo (oscuro, con círculos decorativos) ──
            html.Div([
                deco("220px", C["orange"], "-70px", "-50px"),
                deco("90px", _accent_rgba(C["orange"], 0.5), "40%", "70%"),
                deco("140px", "rgba(255,255,255,0.05)", "70%", "10%"),
                html.Div([
                    _logo(dark_bg=True),
                    html.Div([
                        html.Div("PEOPLE ANALYTICS", style={"color": C["orange"], "fontSize": "11px", "fontWeight": "800", "letterSpacing": "0.15em", "marginBottom": "18px"}),
                        html.H1("Bienvenido a\nHR Copilot", style={"color": C["white"], "fontSize": "38px", "fontWeight": "900", "lineHeight": "1.1", "marginBottom": "18px", "whiteSpace": "pre-line", "fontFamily": FONT}),
                        html.P("Métricas de talento, rotación y desempeño en un solo lugar, listas para tomar decisiones.", style={"color": C["gray_light"], "fontSize": "13px", "lineHeight": "1.6", "maxWidth": "320px"}),
                    ], style={"marginTop": "auto", "marginBottom": "auto"}),
                    html.Div([
                        html.Div(style={"width": "22px", "height": "2px", "background": C["orange"], "marginRight": "10px"}),
                        html.Span("Plataforma Práxedes S.A.S.", style={"color": C["gray_light"], "fontSize": "11px"}),
                    ], style={"display": "flex", "alignItems": "center"}),
                ], style={"position": "relative", "zIndex": 2, "display": "flex", "flexDirection": "column", "height": "100%"}),
            ], style={"flex": "1", "background": C["gray_dark"], "padding": "50px", "position": "relative", "overflow": "hidden"}),

            # ── Panel derecho (blanco, formulario) ──
            html.Div([
                html.Div("ACCESO SEGURO", style={"display": "inline-block", "background": _accent_rgba(C["orange"], 0.1), "color": C["orange"], "padding": "6px 14px", "borderRadius": "25px", "fontSize": "10px", "fontWeight": "800", "letterSpacing": "0.08em", "marginBottom": "26px"}),
                html.H2("Inicia sesión", style={"color": C["gray_dark"], "fontSize": "26px", "fontWeight": "900", "margin": "0 0 8px 0", "fontFamily": FONT}),
                html.P("Cada usuario tiene un rol con reglas de seguridad (RLS) propias.", style={"color": C["gray_mid"], "fontSize": "13px", "marginBottom": "28px", "lineHeight": "1.5"}),

                html.Div("USUARIO", style={"fontSize": "10px", "fontWeight": "800", "color": C["gray_dark"], "letterSpacing": "0.06em", "marginBottom": "8px"}),
                dcc.Input(id="login-user", type="text", placeholder="ej. admin", autoComplete="username", style={
                    "width": "100%", "padding": "14px 16px", "borderRadius": "25px", "boxSizing": "border-box",
                    "border": "1px solid " + C["gray_light"], "fontFamily": FONT, "fontSize": "13px",
                    "outline": "none", "marginBottom": "18px"}),
                html.Div("CONTRASEÑA", style={"fontSize": "10px", "fontWeight": "800", "color": C["gray_dark"], "letterSpacing": "0.06em", "marginBottom": "8px"}),
                dcc.Input(id="login-pass", type="password", placeholder="••••••••", n_submit=0, autoComplete="current-password", style={
                    "width": "100%", "padding": "14px 16px", "borderRadius": "25px", "boxSizing": "border-box",
                    "border": "1px solid " + C["gray_light"], "fontFamily": FONT, "fontSize": "13px",
                    "outline": "none"}),
                html.Div(id="login-error", style={"color": C["danger"], "fontSize": "12px", "fontWeight": "600",
                                                  "minHeight": "18px", "margin": "12px 2px"}),
                html.Button("Ingresar al Sistema →", id="btn-login", n_clicks=0, style={
                    "width": "100%", "padding": "16px", "background": C["orange"],
                    "color": C["white"], "border": "none", "borderRadius": "25px", "cursor": "pointer",
                    "fontWeight": "800", "fontSize": "14px", "marginBottom": "20px", "fontFamily": FONT,
                }),
                html.Div("Usuarios demo: admin · sales.manager · rd.manager · viewer", style={"textAlign": "center", "fontSize": "11px", "color": C["gray_mid"]}),
            ], style={"flex": "1", "background": C["white"], "padding": "60px 50px", "display": "flex", "flexDirection": "column", "justifyContent": "center"}),

        ], style={"display": "flex", "width": "920px", "minHeight": "560px", "background": C["white"], "borderRadius": "25px", "overflow": "hidden", "boxShadow": "0 20px 50px rgba(0,0,0,0.12)"}),
    ], style={"height": "100vh", "display": "flex", "alignItems": "center", "justifyContent": "center", "background": C["gray_bg"], "fontFamily": FONT})

def layout_metrics(role):
    """Métricas de uso IA: tokens, costo, latencia y caché. Solo HR Admin."""
    if role != "hr_admin":
        return html.Div([
            _navbar("metrics"),
            html.Div(html.Div([
                html.Div("🔒", style={"fontSize": "40px", "marginBottom": "14px"}),
                html.Div("Acceso restringido", style={"fontSize": "20px", "fontWeight": "900", "color": C["gray_dark"], "marginBottom": "8px", "fontFamily": FONT}),
                html.Div("Las métricas de uso y costo de la IA solo están disponibles para el rol HR Admin.",
                         style={"fontSize": "13px", "color": C["gray_mid"], "maxWidth": "380px", "lineHeight": "1.5"}),
            ], style={"background": C["white"], "borderRadius": "25px", "padding": "60px", "textAlign": "center",
                      "boxShadow": "0 4px 15px rgba(0,0,0,0.03)"}),
                style={"display": "flex", "justifyContent": "center", "paddingTop": "80px"}),
        ], style={"background": C["gray_bg"], "minHeight": "100vh"})

    return html.Div([
        _navbar("metrics"),
        html.Div([
            _hero("Métricas de Uso de IA",
                  "Consumo de tokens, costo estimado, latencia y tasa de caché de las consultas "
                  "Text-to-SQL procesadas por Gemini."),
            html.Div([
                html.Div("PERÍODO", style={"fontSize": "10px", "fontWeight": "800", "color": C["gray_dark"],
                                           "letterSpacing": "0.06em", "marginBottom": "8px"}),
                dcc.Dropdown(id="metrics-range", value="30", clearable=False, options=[
                    {"label": "Últimos 7 días", "value": "7"},
                    {"label": "Últimos 30 días", "value": "30"},
                    {"label": "Todo el historial", "value": "all"}],
                    style={"width": "220px"}),
            ], style={"background": C["white"], "padding": "20px 24px", "borderRadius": "25px",
                      "marginBottom": "22px", "boxShadow": "0 4px 15px rgba(0,0,0,0.03)"}),
            dcc.Loading(type="dot", color=C["orange"], children=html.Div(id="metrics-body")),
        ], style={"padding": "40px", "maxWidth": "1300px", "margin": "0 auto"}),
    ], style={"background": C["gray_bg"], "minHeight": "100vh"})


def _metrics_table(df):
    th = lambda c: html.Th(c, style={"padding": "12px 14px", "textAlign": "left", "background": C["gray_dark"], "color": C["white"], "fontSize": "11px", "fontWeight": "800", "textTransform": "uppercase", "letterSpacing": "0.04em"})
    td = lambda v: html.Td(v, style={"padding": "11px 14px", "borderBottom": "1px solid " + C["gray_light"], "fontSize": "12px", "fontFamily": FONT})
    rows = []
    for _, r in df.tail(12).iloc[::-1].iterrows():
        rows.append(html.Tr([
            td(r["timestamp"]),
            td(r.get("role") or "—"),
            td(r["question"]),
            td(f"{int(r['tokens_input'] or 0):,} / {int(r['tokens_output'] or 0):,}"),
            td(f"{int(r['latency_ms'] or 0):,} ms"),
            td("✓" if r.get("cache_hit") else "—"),
            td(f"${(r['cost'] or 0):.5f}"),
            html.Td(html.Pre(r.get("sql_generated") or "N/A", style={"fontSize": "10px", "maxWidth": "280px", "overflowX": "auto", "margin": 0, "whiteSpace": "pre-wrap"}),
                    style={"padding": "11px 14px", "borderBottom": "1px solid " + C["gray_light"]}),
        ]))
    return html.Div(html.Table([
        html.Thead(html.Tr([th(c) for c in ["Fecha", "Rol", "Pregunta", "Tokens In/Out", "Latencia", "Caché", "Costo", "SQL"]])),
        html.Tbody(rows),
    ], style={"width": "100%", "borderCollapse": "collapse"}), style={"overflowX": "auto"})


def _panel(title, icon, *children, flex=1):
    return html.Div(
        [_panel_header(title, icon), *children],
        className="glass-panel fade-in-up",
        style={"flex": flex, "background": C["white"], "padding": "25px",
               "borderRadius": "25px", "boxShadow": "0 4px 15px rgba(0,0,0,0.03)",
               "border": "1px solid rgba(0,0,0,0.04)"},
    )


def _section_title(text):
    return html.Div([
        html.Div(style={"width": "8px", "height": "8px", "borderRadius": "50%", "background": C["orange"]}),
        html.Span(text, style={"fontSize": "16px", "fontWeight": "900", "color": C["gray_dark"]}),
    ], style={"display": "flex", "alignItems": "center", "gap": "10px", "margin": "6px 0 18px"})


# ── Página KPIs: catálogo completo de People Analytics (kpi_catalog.py) ──────────
_KPI_STATUS = {
    "ok":   ("Normal",  C["gray_dark"]),
    "warn": ("Alerta",  C["orange"]),
    "bad":  ("Crítico", C["danger"]),
}

def _kpi_ficha(meta):
    """Ficha técnica expandible: descripción, fórmula y gráfico recomendado del catálogo."""
    row = lambda lbl, txt: html.Div([
        html.Div(lbl, style={"fontSize": "9px", "fontWeight": "800", "color": C["orange"],
                             "textTransform": "uppercase", "letterSpacing": "0.06em", "marginBottom": "3px"}),
        html.Div(txt, style={"fontSize": "11px", "color": C["gray_mid"], "lineHeight": "1.5",
                             "whiteSpace": "pre-wrap", "marginBottom": "10px"}),
    ])
    return html.Details([
        html.Summary("ℹ️ Ficha técnica", style={"fontSize": "10px", "fontWeight": "700",
                     "color": C["gray_mid"], "cursor": "pointer", "outline": "none"}),
        html.Div([
            row("Qué mide", meta["Descripcion Funcional"]),
            row("Fórmula", meta["Formula tecnica"]),
            row("Visualización recomendada", meta["Grafico recomendado"]),
        ], style={"marginTop": "10px", "padding": "12px", "background": C["gray_bg"],
                  "borderRadius": "12px", "maxHeight": "260px", "overflowY": "auto"}),
    ], style={"marginTop": "8px"})


def _kpi_panel(item):
    meta, res = item["meta"], item["result"]
    name = meta["Nombre del KPI"].strip()
    chip = html.Span(f"★ {meta['Puntaje Relevancia']:g}", style={
        "background": _accent_rgba(C["orange"], 0.12), "color": C["orange"], "padding": "3px 9px",
        "borderRadius": "25px", "fontSize": "10px", "fontWeight": "800", "whiteSpace": "nowrap"})

    base_style = {"background": C["white"], "borderRadius": "25px", "padding": "22px",
                  "boxShadow": "0 4px 15px rgba(0,0,0,0.03)", "border": "1px solid rgba(0,0,0,0.04)"}
    if item["wide"]:
        base_style["gridColumn"] = "span 2"

    header = html.Div([
        html.Div(name, style={"fontSize": "13px", "fontWeight": "800", "color": C["gray_dark"],
                              "lineHeight": "1.3", "flex": "1"}),
        chip,
    ], style={"display": "flex", "alignItems": "flex-start", "gap": "10px", "marginBottom": "12px"})

    if item["locked"]:
        return html.Div([header, html.Div([
            html.Div("🔒", style={"fontSize": "26px", "marginBottom": "8px"}),
            html.Div("KPI salarial restringido para tu rol", style={
                "fontSize": "12px", "fontWeight": "700", "color": C["gray_mid"]}),
        ], style={"textAlign": "center", "padding": "30px 0"})], style=base_style)

    if item["no_data"]:
        return html.Div([header, html.Div(
            "Requiere datos que el laboratorio no genera (turnos / matriz de competencias).",
            style={"fontSize": "11px", "color": C["gray_mid"], "padding": "12px 0"}),
            _kpi_ficha(meta)], style=base_style)

    status_pill = None
    if res.get("status") in _KPI_STATUS:
        lbl, color = _KPI_STATUS[res["status"]]
        status_pill = html.Span(lbl, style={
            "background": _accent_rgba(color, 0.10), "color": color, "padding": "3px 10px",
            "borderRadius": "25px", "fontSize": "10px", "fontWeight": "800"})

    return html.Div([
        header,
        html.Div([
            html.Span(str(res["value"]), style={"fontSize": "30px", "fontWeight": "900",
                      "color": C["gray_dark"], "lineHeight": "1", "fontFamily": FONT}),
            html.Span(f" {res['unit']}", style={"fontSize": "12px", "fontWeight": "700",
                      "color": C["gray_mid"]}) if res.get("unit") else None,
            html.Span(status_pill, style={"marginLeft": "auto"}) if status_pill else None,
        ], style={"display": "flex", "alignItems": "baseline", "gap": "6px", "marginBottom": "6px"}),
        html.Div(res.get("sublabel", ""), style={"fontSize": "11px", "color": C["gray_mid"],
                 "marginBottom": "8px", "lineHeight": "1.4"}),
        dcc.Graph(figure=res["fig"], config={"displayModeBar": False}) if res.get("fig") is not None else None,
        _kpi_ficha(meta),
    ], className="fade-in-up", style=base_style)


# Hojas: una por categoría del catálogo. Cada hoja define qué segmentadores muestra.
_KPI_TAB_LABEL = {
    "resumen": "Resumen", "estructura": "Estructura", "rotacion": "Rotación",
    "desarrollo": "Desarrollo", "clima": "Clima", "eficiencia": "Eficiencia",
    "nomina": "Nómina", "horarios": "Horarios", "plazas": "Plazas",
}
_KPI_FILTER_VISIBILITY = {
    "resumen":    {"dept", "cargo", "gender", "period"},
    "estructura": {"dept", "cargo", "gender", "level", "period"},
    "rotacion":   {"dept", "cargo", "gender", "level", "period"},
    "desarrollo": {"dept", "cargo", "gender", "progcat"},
    "clima":      {"dept", "cargo", "gender", "cycle"},
    "eficiencia": {"dept", "cargo", "level", "period"},
    "nomina":     {"dept", "cargo", "gender", "level", "period"},
    "horarios":   {"dept", "cargo", "period", "leave"},
    "plazas":     {"dept", "cargo", "level", "period"},
}


def _kpi_tabs(active_slug):
    items = []
    tabs = [("Resumen Ejecutivo", "📌", "resumen")] + list(kpi_catalog.CATEGORY_ORDER)
    for cat, icon, slug in tabs:
        active = slug == active_slug
        items.append(dcc.Link(f"{icon} {_KPI_TAB_LABEL[slug]}", href=f"/kpis/{slug}", title=cat, style={
            "background": C["orange"] if active else "transparent",
            "color": C["white"] if active else C["gray_dark"],
            "fontWeight": "900" if active else "700", "fontSize": "12px",
            "padding": "10px 16px", "borderRadius": "25px", "textDecoration": "none",
            "whiteSpace": "nowrap", "transition": "all 0.2s ease",
        }))
    return html.Div(items, style={
        "display": "flex", "gap": "4px", "flexWrap": "wrap", "background": C["white"],
        "padding": "10px", "borderRadius": "25px", "marginBottom": "20px",
        "boxShadow": "0 4px 15px rgba(0,0,0,0.03)"})


def _kpi_filters_bar(role, slug):
    """Segmentadores de la hoja. Todos los controles existen siempre (el callback los
    referencia); los no relevantes para la hoja van ocultos. Depto bloqueado por RLS."""
    cfg     = ROLES.get(role, {})
    locked  = cfg.get("dept_filter")
    visible = _KPI_FILTER_VISIBILITY.get(slug, {"dept", "period"})

    if locked is None:
        dept_opts = [{"label": "Todos los departamentos", "value": "all"}] + \
                    [{"label": v, "value": str(k)} for k, v in DEPT_NAMES.items()]
        dept_val = "all"
    else:
        dept_opts = [{"label": DEPT_NAMES[locked], "value": str(locked)}]
        dept_val = str(locked)

    cycles   = [r[0] for r in conn.execute("SELECT cycle FROM survey_cycles ORDER BY cycle DESC")]
    progcats = [r[0] for r in conn.execute("SELECT DISTINCT category FROM training_programs ORDER BY 1")]

    lbl = {"fontSize": "10px", "fontWeight": "800", "color": C["gray_dark"],
           "letterSpacing": "0.06em", "marginBottom": "8px"}

    def field(key, text, comp):
        return html.Div([html.Div(text, style=lbl), comp], style={
            "flex": "1", "minWidth": "180px",
            "display": "block" if key in visible else "none"})

    controls = [
        field("dept", "DEPARTAMENTO", dcc.Dropdown(id="kpi-f-dept", options=dept_opts, value=dept_val,
                                                   clearable=False, disabled=(locked is not None))),
        field("cargo", "CARGO", dcc.Dropdown(id="kpi-f-cargo", value="all", clearable=False, options=[
            {"label": "Todos los cargos", "value": "all"}] +
            [{"label": v, "value": str(k)} for k, v in JOB_ROLES.items()])),
        field("gender", "GÉNERO", dcc.Dropdown(id="kpi-f-gender", value="all", clearable=False, options=[
            {"label": "Todos los géneros", "value": "all"},
            {"label": "Femenino", "value": "Female"}, {"label": "Masculino", "value": "Male"}])),
        field("level", "NIVEL DE CARGO", dcc.Dropdown(id="kpi-f-level", value="all", clearable=False, options=[
            {"label": "Todos los niveles", "value": "all"}] +
            [{"label": f"Nivel {i}", "value": str(i)} for i in range(1, 6)])),
        field("period", "PERÍODO", dcc.Dropdown(id="kpi-f-period", value="24", clearable=False, options=[
            {"label": "Últimos 24 meses", "value": "24"},
            {"label": "Últimos 12 meses", "value": "12"},
            {"label": "Últimos 6 meses", "value": "6"}])),
        field("leave", "TIPO DE INCAPACIDAD", dcc.Dropdown(id="kpi-f-leave", value="all", clearable=False, options=[
            {"label": "Todos los tipos", "value": "all"},
            {"label": "Enfermedad General (EPS)", "value": "EPS"},
            {"label": "Accidente de Trabajo (ARL)", "value": "AT"},
            {"label": "Enfermedad Laboral (ARL)", "value": "EL"}])),
        field("progcat", "CATEGORÍA DE PROGRAMA", dcc.Dropdown(id="kpi-f-progcat", value="all", clearable=False,
            options=[{"label": "Todas las categorías", "value": "all"}] +
                    [{"label": c, "value": c} for c in progcats])),
        field("cycle", "CICLO DE ENCUESTA", dcc.Dropdown(id="kpi-f-cycle", value="all", clearable=False,
            options=[{"label": "Más reciente", "value": "all"}] +
                    [{"label": c, "value": c} for c in cycles])),
        html.Div(html.Button("↺ Limpiar", id="kpi-f-reset", n_clicks=0, style={
            "background": C["gray_bg"], "border": "1px solid " + C["gray_light"], "color": C["gray_dark"],
            "padding": "10px 16px", "borderRadius": "25px", "fontSize": "12px", "fontWeight": "700",
            "cursor": "pointer", "fontFamily": FONT, "whiteSpace": "nowrap"}),
            style={"display": "flex", "alignItems": "flex-end"}),
    ]
    return html.Div(controls, style={
        "display": "flex", "gap": "16px", "flexWrap": "wrap", "alignItems": "flex-end",
        "background": C["white"], "padding": "20px 24px", "borderRadius": "25px",
        "marginBottom": "22px", "boxShadow": "0 4px 15px rgba(0,0,0,0.03)"})


def layout_kpis(role, slug="resumen"):
    """Dashboard estático del catálogo: hoja Resumen + una hoja por categoría, con segmentadores."""
    if slug not in kpi_catalog.SLUG_TO_CAT and slug != "resumen":
        slug = "resumen"
    if slug == "resumen":
        cat, icon = "Resumen Ejecutivo", "📌"
    else:
        cat = kpi_catalog.SLUG_TO_CAT[slug]
        icon = {s: i for _, i, s in kpi_catalog.CATEGORY_ORDER}[slug]
    return html.Div([
        _navbar("kpis"),
        html.Div([
            _hero(f"{icon} {cat}",
                  "Catálogo Práxedes de People Analytics — usa los segmentadores para "
                  "entender la data de esta categoría. Cada tarjeta incluye su ficha técnica."),
            _kpi_tabs(slug),
            _kpi_filters_bar(role, slug),
            dcc.Store(id="kpi-cat", data=slug),
            dcc.Loading(type="dot", color=C["orange"], children=html.Div(id="kpi-body")),
        ], style={"padding": "40px", "maxWidth": "1300px", "margin": "0 auto"}),
    ], style={"background": C["gray_bg"], "minHeight": "100vh"})


# ── Chat conversacional ──────────────────────────────────────────────────────────
def _chat_bubble_user(text):
    return html.Div(
        html.Div(text, style={
            "background": C["orange"], "color": C["white"], "padding": "12px 18px",
            "borderRadius": "18px 18px 4px 18px", "maxWidth": "75%", "fontSize": "14px",
            "fontWeight": "500", "lineHeight": "1.4", "boxShadow": "0 2px 8px rgba(255,139,0,0.25)",
        }),
        style={"display": "flex", "justifyContent": "flex-end", "marginBottom": "18px"},
    )


def _chat_bubble_assistant(turn):
    """Renderiza la respuesta del asistente: error, o gráfico + tabla + SQL colapsable."""
    inner = []

    if turn.get("error"):
        inner.append(html.Div([
            html.Span("⚠ ", style={"fontWeight": "800"}),
            turn["error"],
        ], style={"color": C["danger"], "fontSize": "13px", "fontWeight": "600"}))
    else:
        # Gráfico
        if turn.get("fig_json"):
            try:
                fig = pio.from_json(turn["fig_json"])
                inner.append(dcc.Graph(figure=fig, style={"height": "380px"}, config={"displayModeBar": False}))
            except Exception:
                pass

        # Tabla
        cols, rows = turn.get("columns", []), turn.get("rows", [])
        if cols and rows:
            inner.append(html.Div(f"{turn.get('nrows', len(rows))} filas", style={
                "fontSize": "10px", "fontWeight": "700", "color": C["gray_mid"],
                "textTransform": "uppercase", "letterSpacing": "0.05em", "margin": "10px 0 6px",
            }))
            inner.append(html.Div(
                html.Table([
                    html.Thead(html.Tr([
                        html.Th(c, style={"padding": "8px", "background": C["gray_dark"], "color": C["white"], "fontSize": "11px", "textAlign": "left", "position": "sticky", "top": 0})
                        for c in cols
                    ])),
                    html.Tbody([
                        html.Tr([
                            html.Td(cell, style={"padding": "7px", "fontSize": "12px", "borderBottom": "1px solid #eee"})
                            for cell in row
                        ]) for row in rows[:15]
                    ]),
                ], style={"width": "100%", "borderCollapse": "collapse"}),
                style={"maxHeight": "300px", "overflowY": "auto", "borderRadius": "10px", "border": "1px solid #eee"},
            ))
        elif not turn.get("fig_json"):
            inner.append(html.Div("Sin resultados para esta consulta.", style={"color": C["gray_mid"], "fontSize": "13px"}))

        # SQL colapsable
        if turn.get("sql"):
            cache_tag = " · desde cache" if turn.get("from_cache") else ""
            inner.append(html.Details([
                html.Summary(f"Ver SQL generado{cache_tag}", style={
                    "cursor": "pointer", "fontSize": "11px", "fontWeight": "700",
                    "color": C["orange"], "marginTop": "12px", "userSelect": "none",
                }),
                html.Pre(turn["sql"], style={
                    "background": C["gray_dark"], "color": "#e0e0e0", "padding": "14px",
                    "borderRadius": "10px", "fontSize": "11px", "overflowX": "auto",
                    "marginTop": "8px", "whiteSpace": "pre-wrap",
                }),
            ]))

    return html.Div([
        html.Div("🤖", style={
            "fontSize": "16px", "background": "rgba(56,56,56,0.06)", "width": "34px", "height": "34px",
            "borderRadius": "50%", "display": "flex", "alignItems": "center", "justifyContent": "center",
            "flexShrink": 0, "marginRight": "12px",
        }),
        html.Div(inner, style={
            "background": C["white"], "padding": "18px 20px", "borderRadius": "4px 18px 18px 18px",
            "maxWidth": "85%", "boxShadow": "0 2px 12px rgba(0,0,0,0.05)", "border": "1px solid rgba(0,0,0,0.04)",
        }),
    ], style={"display": "flex", "alignItems": "flex-start", "marginBottom": "18px"})


def _render_chat_history(history):
    """Convierte la lista de turnos del store en burbujas. Muestra estado vacío si no hay nada."""
    if not history:
        chips = [
            html.Button(q, id={"type": "suggest-chip", "index": i}, n_clicks=0, style={
                "background": C["white"], "border": "1px solid " + C["gray_light"], "color": C["gray_dark"],
                "padding": "10px 16px", "borderRadius": "25px", "fontSize": "13px", "fontWeight": "600",
                "cursor": "pointer", "fontFamily": FONT, "textAlign": "left",
            })
            for i, q in enumerate(SUGGESTED)
        ]
        return html.Div([
            html.Div("🤖", style={"fontSize": "48px", "textAlign": "center", "marginBottom": "16px"}),
            html.H3("Pregúntale a tus datos de talento", style={"color": C["gray_dark"], "textAlign": "center", "marginBottom": "8px"}),
            html.P("Escribe en lenguaje natural y la IA generará la consulta, el gráfico y la tabla.", style={"color": C["gray_mid"], "textAlign": "center", "fontSize": "13px", "marginBottom": "30px"}),
            html.Div("PRUEBA CON:", style={"fontSize": "10px", "fontWeight": "800", "color": C["gray_mid"], "letterSpacing": "0.1em", "textAlign": "center", "marginBottom": "14px"}),
            html.Div(chips, style={"display": "flex", "flexWrap": "wrap", "gap": "10px", "justifyContent": "center", "maxWidth": "620px", "margin": "0 auto"}),
        ], style={"padding": "40px 20px"})

    bubbles = []
    for turn in history:
        if turn.get("role") == "user":
            bubbles.append(_chat_bubble_user(turn.get("text", "")))
        else:
            bubbles.append(_chat_bubble_assistant(turn))
    return html.Div(bubbles)


def layout_chat(role):
    hero = _hero("Dashboard · Asistente IA",
                 "Pregunta en lenguaje natural y la IA genera la consulta, el gráfico solicitado "
                 "y la tabla de resultados. Las respuestas respetan tu perfil de acceso (RLS).")
    return html.Div([
        _navbar("dashboard"),
        dcc.Store(id="chat-store", storage_type="session", data=[]),
        html.Div([
            hero,
            # Barra de acciones
            html.Div([
                html.Span("Conversación", style={"fontSize": "15px", "fontWeight": "800", "color": C["gray_dark"]}),
                html.Button("🗑 Limpiar conversación", id="btn-clear-chat", n_clicks=0, style={
                    "background": C["white"], "border": "1px solid " + C["gray_light"], "color": C["gray_mid"],
                    "padding": "9px 16px", "borderRadius": "25px", "fontSize": "12px", "fontWeight": "700",
                    "cursor": "pointer", "fontFamily": FONT,
                }),
            ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "16px"}),

            # Historial
            dcc.Loading(type="dot", color=C["orange"], children=[
                html.Div(id="chat-history", style={
                    "minHeight": "52vh", "maxHeight": "64vh", "overflowY": "auto",
                    "background": C["white"], "borderRadius": "25px", "padding": "30px",
                    "border": "1px solid rgba(0,0,0,0.05)", "boxShadow": "0 4px 15px rgba(0,0,0,0.03)",
                })
            ]),

            # Barra de entrada
            html.Div([
                dcc.Textarea(id="chat-input", placeholder="Ej: ¿Cuál es la rotación por departamento?", style={
                    "flex": "1", "padding": "16px", "borderRadius": "25px", "border": "1px solid " + C["gray_light"],
                    "fontSize": "14px", "resize": "none", "height": "56px", "fontFamily": FONT, "background": C["white"],
                }),
                html.Button([html.Span("➤", style={"fontSize": "16px"})], id="chat-send", n_clicks=0, style={
                    "padding": "0 28px", "background": C["orange"], "color": C["white"], "border": "none",
                    "borderRadius": "25px", "fontWeight": "bold", "cursor": "pointer", "marginLeft": "14px",
                    "height": "56px", "fontSize": "16px",
                }),
            ], style={"display": "flex", "alignItems": "center", "marginTop": "18px"}),
        ], style={"padding": "40px", "maxWidth": "1100px", "margin": "0 auto"}),
    ], style={"background": C["gray_bg"], "minHeight": "100vh"})


app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    dcc.Store(id='store-role', storage_type='session'),
    html.Div(id='page-content')
])

# ── Callbacks ──────────────────────────────────────────────────────────────────

@app.callback(
    Output('page-content', 'children'),
    Input('url', 'pathname'),
    State('store-role', 'data')
)
def display_page(pathname, role):
    # /dashboard = chat con Gemini. /kpis/<hoja> = dashboard estático del catálogo.
    # El rol viene de la sesión server-side (el Store del navegador no es confiable).
    role = current_session()[1]
    if pathname in ('/dashboard', '/chat'):
        if not role: return dcc.Location(pathname="/", id="redirect-login")
        return layout_chat(role)
    elif pathname == '/metrics':
        if not role: return dcc.Location(pathname="/", id="redirect-login")
        return layout_metrics(role)
    elif pathname == '/analytics':
        # Página "Indicadores" consolidada en /kpis (hoja Resumen)
        return dcc.Location(pathname="/kpis", id="redirect-kpis")
    elif pathname and pathname.startswith('/kpis'):
        if not role: return dcc.Location(pathname="/", id="redirect-login")
        slug = pathname.split('/kpis/')[-1] if '/kpis/' in pathname else "resumen"
        return layout_kpis(role, slug)
    else:
        try:
            flask.session.clear()   # "Salir →" apunta a "/" — cierra la sesión
        except Exception:
            pass
        return layout_login()

@app.callback(
    Output('store-role', 'data'),
    Output('url', 'pathname', allow_duplicate=True),
    Output('login-error', 'children'),
    Input('btn-login', 'n_clicks'),
    Input('login-pass', 'n_submit'),
    State('login-user', 'value'),
    State('login-pass', 'value'),
    prevent_initial_call=True
)
def handle_login(n_clicks, n_submit, username, password):
    ok, user, err = check_login(conn, username or "", password or "")
    if ok:
        flask.session["username"]  = user["username"]
        flask.session["role"]      = user["role"]
        flask.session["full_name"] = user["full_name"]
        return user["role"], '/dashboard', ""
    return dash.no_update, dash.no_update, err


# ── Chat callbacks ───────────────────────────────────────────────────────────────
@app.callback(
    Output("chat-history", "children"),
    Input("chat-store", "data"),
)
def render_chat_on_load(history):
    """Restaura el historial al cargar la página o navegar (sesión persistente)."""
    return _render_chat_history(history or [])


@app.callback(
    Output("chat-history", "children", allow_duplicate=True),
    Output("chat-store",   "data",     allow_duplicate=True),
    Output("chat-input",   "value",    allow_duplicate=True),
    Input("chat-send",     "n_clicks"),
    State("chat-input",    "value"),
    State("store-role",    "data"),
    State("chat-store",    "data"),
    prevent_initial_call=True,
)
def submit_chat(n_clicks, question, role, history):
    if not question or not question.strip():
        raise PreventUpdate
    role = current_session()[1]
    if not role:
        raise PreventUpdate

    history = list(history or [])
    history.append({"role": "user", "text": question.strip()})

    result = process_question(question.strip(), role)
    result["role"] = "assistant"
    history.append(result)

    return _render_chat_history(history), history, ""


@app.callback(
    Output("chat-history", "children", allow_duplicate=True),
    Output("chat-store",   "data",     allow_duplicate=True),
    Input("btn-clear-chat", "n_clicks"),
    prevent_initial_call=True,
)
def clear_chat(n_clicks):
    return _render_chat_history([]), []


@app.callback(
    Output("chat-input", "value", allow_duplicate=True),
    Input({"type": "suggest-chip", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def fill_suggestion(clicks):
    if not clicks or not any(clicks):
        raise PreventUpdate
    idx = callback_context.triggered_id["index"]
    return SUGGESTED[idx]


# ── KPIs: hojas por categoría con segmentadores ──────────────────────────────────
_KPI_BODY_CACHE = {}

@app.callback(
    Output("kpi-body",  "children"),
    Input("kpi-f-dept",    "value"),
    Input("kpi-f-cargo",   "value"),
    Input("kpi-f-gender",  "value"),
    Input("kpi-f-level",   "value"),
    Input("kpi-f-period",  "value"),
    Input("kpi-f-leave",   "value"),
    Input("kpi-f-progcat", "value"),
    Input("kpi-f-cycle",   "value"),
    State("store-role", "data"),
    State("kpi-cat",    "data"),
)
def update_kpis(dept, cargo, gender, level, period, leave, progcat, cycle, role, slug):
    role = current_session()[1]
    if not role or not slug:
        raise PreventUpdate
    filters = {"dept": dept, "cargo": cargo, "gender": gender, "level": level,
               "period": period, "leave": leave, "progcat": progcat, "cycle": cycle}
    key = (role, slug, tuple(str(filters[k]) for k in sorted(filters)))
    if key in _KPI_BODY_CACHE:
        return _KPI_BODY_CACHE[key]

    sec = kpi_catalog.build_all(conn, ROLES.get(role, {}), category=slug, filters=filters)[0]
    n_calc = sum(1 for i in sec["items"] if i["result"] is not None)
    body = html.Div([
        html.Div([
            html.Span(f"{n_calc}/{len(sec['items'])} KPIs calculados", style={
                "background": C["white"], "color": C["gray_mid"], "padding": "4px 12px",
                "borderRadius": "25px", "fontSize": "10px", "fontWeight": "700"}),
        ], style={"marginBottom": "14px"}),
        html.Div([_kpi_panel(i) for i in sec["items"]], style={
            "display": "grid", "gridTemplateColumns": "repeat(2, 1fr)", "gap": "18px"}),
    ])
    if len(_KPI_BODY_CACHE) > 128:
        _KPI_BODY_CACHE.clear()
    _KPI_BODY_CACHE[key] = body
    return body


@app.callback(
    Output("kpi-f-cargo",   "value"),
    Output("kpi-f-gender",  "value"),
    Output("kpi-f-level",   "value"),
    Output("kpi-f-period",  "value"),
    Output("kpi-f-leave",   "value"),
    Output("kpi-f-progcat", "value"),
    Output("kpi-f-cycle",   "value"),
    Input("kpi-f-reset",    "n_clicks"),
    prevent_initial_call=True,
)
def reset_kpi_filters(n):
    # El departamento no se resetea: puede estar bloqueado por RLS.
    return "all", "all", "all", "24", "all", "all", "all"


# ── Métricas: cuerpo reactivo por rango de fechas ────────────────────────────────
@app.callback(
    Output("metrics-body", "children"),
    Input("metrics-range", "value"),
    State("store-role", "data"),
)
def update_metrics(days, role):
    if current_session()[1] != "hr_admin":
        raise PreventUpdate
    try:
        df = pd.read_sql_query("SELECT * FROM usage_metrics", conn)
    except Exception:
        df = pd.DataFrame()
    if len(df):
        df["date"] = df["timestamp"].str[:10]
        if days != "all":
            cutoff = (datetime.now() - pd.Timedelta(days=int(days))).strftime("%Y-%m-%d")
            df = df[df["date"] >= cutoff]
    if not len(df):
        return html.Div("Aún no hay consultas registradas en este período. Usa el chat para generar métricas.",
                        style={"color": C["gray_mid"], "fontSize": "13px", "padding": "30px",
                               "background": C["white"], "borderRadius": "25px"})

    for col, default in [("cache_hit", 0), ("success", 1), ("latency_ms", 0), ("role", "hr_admin")]:
        df[col] = df[col].fillna(default) if col in df else default
    df["tokens_total"] = df["tokens_input"].fillna(0) + df["tokens_output"].fillna(0)

    total_cost = df["cost"].fillna(0).sum()
    n_days     = max(df["date"].nunique(), 1)
    lat        = df.loc[df["latency_ms"] > 0, "latency_ms"]
    cards = html.Div([
        kpi_card("📊", "Prompts", f"{len(df):,}", "", C["info"], f"{int(df['success'].sum())} exitosos"),
        kpi_card("🔠", "Tokens", f"{int(df['tokens_total'].sum()):,}", "", C["gray_dark"], "SQL + gráficos"),
        kpi_card("💵", "Costo", f"${total_cost:.4f}", "USD", C["orange"], "Acumulado del período"),
        kpi_card("📈", "Proyección", f"${total_cost / n_days * 30:.2f}", "USD/mes", C["warning"], "Promedio diario × 30"),
        kpi_card("⚡", "Caché", f"{100 * df['cache_hit'].mean():.0f}%", "", C["gray_dark"], "Consultas sin costo de API"),
        kpi_card("⏱", "Latencia p50", f"{int(lat.median()) if len(lat) else 0:,}", "ms", C["info"], "Mediana del pipeline"),
    ], style={"display": "grid", "gridTemplateColumns": "repeat(3, 1fr)", "gap": "20px", "marginBottom": "26px"})

    by_day = df.groupby("date").agg(
        cost=("cost", "sum"), tin=("tokens_input", "sum"), tout=("tokens_output", "sum"),
        lat=("latency_ms", "median")).reset_index()

    f_cost = go.Figure(go.Scatter(x=by_day["date"], y=by_day["cost"].round(5), mode="lines",
                                  fill="tozeroy", line=dict(color=C["orange"], width=2.5)))
    f_tok = go.Figure()
    f_tok.add_bar(x=by_day["date"], y=by_day["tin"], name="Input", marker_color=C["gray_light"])
    f_tok.add_bar(x=by_day["date"], y=by_day["tout"], name="Output", marker_color=C["orange"])
    f_tok.update_layout(barmode="stack")
    by_role = df.groupby("role").size()
    f_role = go.Figure(go.Pie(labels=list(by_role.index), values=list(by_role.values), hole=0.55,
                              marker=dict(colors=[C["orange"], C["gray_dark"], C["info"], C["warning"]])))
    f_lat = go.Figure(go.Scatter(x=by_day["date"], y=by_day["lat"], mode="lines+markers",
                                 line=dict(color=C["gray_dark"], width=2.5)))
    for f in (f_cost, f_tok, f_role, f_lat):
        kpi_catalog._theme(f, height=240, legend=(f in (f_tok, f_role)))

    g = lambda f: dcc.Graph(figure=f, config={"displayModeBar": False})
    charts = html.Div([
        _panel("Costo por día (USD)", "💵", g(f_cost)),
        _panel("Tokens por día", "🔠", g(f_tok)),
        _panel("Consultas por rol", "👤", g(f_role)),
        _panel("Latencia mediana por día (ms)", "⏱", g(f_lat)),
    ], style={"display": "grid", "gridTemplateColumns": "repeat(2, 1fr)", "gap": "18px", "marginBottom": "26px"})

    return html.Div([cards, charts, _panel("Historial Reciente", "🕒", _metrics_table(df))])


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8051))
    app.run(host="0.0.0.0", port=port, debug=False)
