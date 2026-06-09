"""
dashboard_praxedes.py
---------------------
HR Copilot — Práxedes Edition
Styled to match Práxedes S.A.S. web design manual:
  - Montserrat font family
  - Colors: #ff8b00 orange, #383838 dark gray, #dddddd light gray, #ffffff white
  - Rounded corners (25px), flat backgrounds, clean professional layout

Run from project root:
    python app/dashboard_praxedes.py
"""

import os
import re
import sys
import json
import hashlib
import sqlite3
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import google.genai as genai
import dash
from dash import dcc, html, Input, Output, State, callback_context
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
CHROMA_DIR = BASE_DIR

sys.path.insert(0, _SCRIPT_DIR)
sys.path.insert(0, BASE_DIR)
from rls import rls_intercept, ROLES, DEPT_NAMES
from setup.train_vanna import DDL, DOCUMENTATION, KPI_DOCUMENTATION, VISUALIZATION_DOCUMENTATION, EXAMPLES, KPI_EXAMPLES

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
    def get_related_ddl(self, question, **kwargs): return [DDL]
    def get_related_documentation(self, question, **kwargs): return [DOCUMENTATION, KPI_DOCUMENTATION, VISUALIZATION_DOCUMENTATION]
    def get_similar_question_sql(self, question, **kwargs): return EXAMPLES + KPI_EXAMPLES
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
            "\n\nIMPORTANT: The database has exactly 4 tables: "
            "employees, departments, job_roles, satisfaction. "
            "Always use lowercase table names. Never invent table names."
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
vn = HRCopilot(config={
    "api_key":                  API_KEY,
    "model":                    "gemini-2.5-flash",
    "chroma_persist_directory": CHROMA_DIR,
})
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
try:
    conn.execute("ALTER TABLE usage_metrics ADD COLUMN sql_generated TEXT")
except:
    pass
conn.commit()
vn.run_sql = lambda sql: pd.read_sql_query(sql, conn)
vn.run_sql_is_set = True
print("  Ready.")

ROLE_LABELS = {
    "hr_admin":        "HR Admin — sin restricciones",
    "sales_manager":   "Sales Manager — solo Sales",
    "rd_manager":      "R&D Manager — solo R&D",
    "employee_viewer": "Employee Viewer — sin salarios",
}


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

RULE 1 — Two categorical columns + one numeric (e.g. dept + gender + count):
  → px.bar, color=<second_categorical>, barmode='group'
  → Apply semantic color_discrete_map when column is Gender/Attrition/OverTime

RULE 2 — One categorical + one numeric (ranking/comparison):
  → rows > 6 → horizontal bar orientation='h', sorted ascending, color='#ff8b00'
  → rows ≤ 6 → vertical bar, color_discrete_sequence=['#ff8b00','#383838','#5b8db8']

RULE 3 — Single row result (exactly 1 row):
  → go.Indicator(mode='number'), number font color='#ff8b00'
  → NEVER use a bar chart for a single KPI value

RULE 4 — Sequential numeric X (YearsAtCompany, JobLevel, YearsInCurrentRole, tenure_band, age range):
  → px.line with markers=True, color_discrete_sequence=['#ff8b00']
  → Use this whenever X represents progression, not categories

RULE 5 — Percentage/proportion column (name contains pct/rate/porcentaje/ratio):
  → 2–6 rows → px.pie with hole=0.38, color_discrete_sequence=['#ff8b00','#383838','#5b8db8']
  → > 6 rows → horizontal bar instead (Rule 2)

RULE 6 — Distribution question (distribucion/distribution/rango/spread/histograma):
  → Categorical x available → px.box, color_discrete_sequence=['#ff8b00','#383838']
  → No categorical x → px.histogram, nbins=25, color_discrete_sequence=['#ff8b00']

RULE 7 — Two numeric columns, many rows (correlation):
  → px.scatter, color='#ff8b00', opacity=0.65

RULE 8 — Multiple score/metric columns per category (e.g. 4 satisfaction dimensions):
  → pd.melt to long format + px.bar barmode='group'
  → color_discrete_sequence=['#ff8b00','#383838','#5b8db8','#e67e22']

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

    # 2. Two categorical dims + one numeric → grouped bar (Rule 1 from training)
    if len(cats) >= 2 and nums:
        fig = px.bar(
            df, x=cats[0], y=nums[0], color=cats[1],
            barmode="group", title=question[:60],
            text=df[nums[0]].round(1),
            color_discrete_sequence=colorway,
        )
        fig.update_traces(textposition="outside")
        return fig

    # 3. Time series → line
    if times and nums:
        y_cols = [c for c in nums if c not in times][:3]
        if y_cols:
            fig = px.line(
                df, x=times[0], y=y_cols, title=question[:60],
                markers=True, color_discrete_sequence=colorway,
            )
            fig.update_traces(line=dict(width=2.5))
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
    "What is the overall attrition rate?",
    "Which departments have the highest turnover?",
    "Is there a gender pay gap?",
    "Who is at highest burnout risk?",
    "What is the average salary by job level?",
    "How does overtime affect attrition?",
]


# ── UI helpers ─────────────────────────────────────────────────────────────────
def kpi_card(icon, label, value, unit="", color=None, sublabel="", trend=None):
    accent = color or C["orange"]
    
    trend_pill = None
    if trend:
        t_color = C["success"] if trend["dir"] == "up" else (C["danger"] if trend["dir"] == "down" else C["gray_dark"])
        t_bg = f"rgba(0, 200, 83, 0.1)" if trend["dir"] == "up" else (f"rgba(244, 67, 54, 0.1)" if trend["dir"] == "down" else f"rgba(158, 158, 158, 0.1)")
        t_arrow = "↗" if trend["dir"] == "up" else ("↘" if trend["dir"] == "down" else "")
        trend_pill = html.Div(f"{t_arrow} {trend['value']}", style={
            "background": t_bg, "color": t_color, "padding": "4px 8px", "borderRadius": "12px",
            "fontSize": "11px", "fontWeight": "bold", "marginLeft": "auto"
        })
        
    return html.Div([
        html.Div([
            html.Div(icon, style={"fontSize": "20px", "background": "rgba(255, 139, 0, 0.1)", "color": C["orange"], "width": "40px", "height": "40px", "borderRadius": "50%", "display": "flex", "alignItems": "center", "justifyContent": "center", "marginRight": "10px"}),
            trend_pill
        ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "15px"}),
        
        html.Div([
            html.Span(str(value), style={"fontSize": "42px", "fontWeight": "900", "color": C["gray_dark"], "lineHeight": "1", "fontFamily": FONT}),
            html.Span(f" {unit}", style={"fontSize": "16px", "fontWeight": "600", "color": C["gray_mid"]}) if unit else None,
        ], style={"marginBottom": "10px"}),
        
        html.Div([
            html.Div(label, style={"fontSize": "11px", "fontWeight": "800", "color": C["gray_dark"], "textTransform": "uppercase", "letterSpacing": "0.05em"}),
            html.Div(sublabel, style={"fontSize": "11px", "color": C["gray_mid"], "fontWeight": "500", "marginTop": "2px"}) if sublabel else None,
        ])
    ], style={
        "background": C["white"], "borderRadius": "20px", "padding": "24px",
        "flex": "1", "minWidth": "200px",
        "boxShadow": "0 4px 15px rgba(0,0,0,0.03)",
        "border": "1px solid rgba(0,0,0,0.05)",
        "transition": "transform 0.3s ease, box-shadow 0.3s ease",
        "className": "kpi-card-hover"
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
app = dash.Dash(__name__, title="HR Copilot — Práxedes v2", suppress_callback_exceptions=True)
server = app.server

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



def _navbar(active_page="dashboard"):
    navs = [
        ("Dashboard", "/dashboard", "dashboard"),
        ("People Analytics", "/analytics", "analytics"),
        ("Métricas", "/metrics", "metrics")
    ]
    
    links = []
    for label, href, page_id in navs:
        is_active = (active_page == page_id)
        color = C["orange"] if is_active else C["gray_light"]
        border = f"2px solid {C['orange']}" if is_active else "none"
        padding_bottom = "20px" if is_active else "0px"
        links.append(dcc.Link(label, href=href, style={"color": color, "marginRight": "30px", "textDecoration": "none", "fontWeight": "bold", "fontSize": "13px", "borderBottom": border, "paddingBottom": padding_bottom, "transition": "all 0.2s ease"}))
        
    links.append(dcc.Link("→ Salir", href="/", style={"color": C["gray_light"], "textDecoration": "none", "fontSize": "13px"}))
    
    return html.Div([
        html.Div([
            html.Div(style={"width": "18px", "height": "18px", "background": C["orange"], "borderRadius": "4px", "marginRight": "10px"}),
            html.Span("HR Copilot", style={"fontWeight": "900", "color": C["white"], "fontSize": "18px"})
        ], style={"display": "flex", "alignItems": "center"}),
        html.Div(links, style={"display": "flex", "alignItems": "center", "paddingTop": "20px"})
    ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "padding": "0 40px", "background": C["gray_dark"], "borderBottom": "1px solid rgba(255,255,255,0.1)"})

def layout_login():
    return html.Div([
        html.Div([
            # Left side (Dark panel)
            html.Div([
                html.Div([
                    html.Div(style={"width": "18px", "height": "18px", "background": C["orange"], "borderRadius": "4px", "marginRight": "10px"}),
                    html.Span("HR Copilot", style={"color": C["white"], "fontWeight": "800", "fontSize": "18px"})
                ], style={"display": "flex", "alignItems": "center", "marginBottom": "60px"}),
                
                html.Div("PEOPLE ANALYTICS", style={"color": C["orange"], "fontSize": "10px", "fontWeight": "800", "letterSpacing": "0.1em", "marginBottom": "20px"}),
                html.H1("Bienvenido a\nHR Copilot", style={"color": C["white"], "fontSize": "36px", "fontWeight": "900", "lineHeight": "1.1", "marginBottom": "20px", "whiteSpace": "pre-line"}),
                html.P("Métricas de talento, rotación y desempeño en un\nsolo lugar, listas para tomar decisiones.", style={"color": C["gray_mid"], "fontSize": "12px", "lineHeight": "1.5", "marginBottom": "40px"}),
                
                html.Div([
                    html.Div(style={"width": "20px", "height": "2px", "background": C["orange"], "marginRight": "10px"}),
                    html.Span("Plataforma Práxedes", style={"color": C["gray_mid"], "fontSize": "10px"})
                ], style={"display": "flex", "alignItems": "center", "marginTop": "auto"})
            ], style={"flex": "1", "background": C["gray_dark"], "padding": "50px", "display": "flex", "flexDirection": "column", "position": "relative", "overflow": "hidden"}),
            
            # Right side (White panel)
            html.Div([
                html.Div("ACCESO POR PERFIL", style={"display": "inline-block", "background": "rgba(255, 139, 0, 0.1)", "color": C["orange"], "padding": "5px 12px", "borderRadius": "15px", "fontSize": "9px", "fontWeight": "800", "marginBottom": "30px"}),
                html.P("Por favor selecciona tu perfil para ingresar al sistema.", style={"color": C["gray_mid"], "fontSize": "14px", "marginBottom": "40px"}),
                
                html.Div("SELECCIONA TU ROL", style={"fontSize": "10px", "fontWeight": "800", "color": C["gray_dark"], "marginBottom": "10px"}),
                html.Div(
                    dcc.Dropdown(
                        id="login-role",
                        options=[{"label": v, "value": k} for k, v in ROLE_LABELS.items()],
                        placeholder="Selecciona un rol...",
                        style={"textAlign": "left"}
                    ),
                    style={"marginBottom": "30px", "position": "relative", "zIndex": 9999}
                ),
                html.Button("Ingresar al Sistema →", id="btn-login", n_clicks=0, style={
                    "width": "100%", "padding": "15px", "background": C["gray_dark"], 
                    "color": C["white"], "border": "none", "borderRadius": "10px", "cursor": "pointer",
                    "fontWeight": "bold", "fontSize": "14px", "marginBottom": "20px"
                }),
                
                html.Div("¿Problemas para ingresar? Contacta a Talento Humano", style={"textAlign": "center", "fontSize": "10px", "color": C["gray_mid"]})
            ], style={"flex": "1", "background": C["white"], "padding": "60px 50px", "display": "flex", "flexDirection": "column", "justifyContent": "center"})
            
        ], style={"display": "flex", "width": "900px", "minHeight": "550px", "background": C["white"], "borderRadius": "20px", "overflow": "hidden", "boxShadow": "0 20px 40px rgba(0,0,0,0.1)"})
    ], style={"height": "100vh", "display": "flex", "alignItems": "center", "justifyContent": "center", "background": "#e5e5e5", "fontFamily": FONT})

def layout_dashboard(role):
    kpis = get_kpis()
    return html.Div([
        _navbar("dashboard"),
        
        html.Div([
            # Input Section (Top)
            html.Div([
                html.H2([html.Span("☼", style={"background": C["orange"], "color": C["white"], "borderRadius": "8px", "padding": "4px 8px", "marginRight": "10px", "fontSize": "16px"}), "¿Qué datos necesitas hoy?"], style={"color": C["orange"], "marginBottom": "20px", "display": "flex", "alignItems": "center"}),
                html.Div([
                    dcc.Textarea(id="input-question", placeholder="Necesito entender el comportamiento de salarios por departamento...", style={"flex": "1", "padding": "15px", "borderRadius": "10px", "border": "1px solid " + C["gray_light"], "fontSize": "14px", "resize": "vertical", "minHeight": "60px", "fontFamily": FONT}),
                    html.Button([html.Span("✨", style={"marginRight": "8px"}), "Generar Insight"], id="btn-ask", n_clicks=0, style={"padding": "15px 30px", "background": C["orange"], "color": C["white"], "border": "none", "borderRadius": "10px", "fontWeight": "bold", "cursor": "pointer", "marginLeft": "20px", "height": "60px", "display": "flex", "alignItems": "center"})
                ], style={"display": "flex", "alignItems": "flex-start"})
            ], className="fade-in-up", style={"background": C["white"], "padding": "40px", "borderRadius": "20px", "marginBottom": "30px", "boxShadow": "0 4px 15px rgba(0,0,0,0.03)"}),
            
            # ── KPI SECTION ────────────────────────────────────────────────
            html.Div([
                kpi_card("👥", "Headcount", f"{kpis.get('headcount', 0):,}", "emp", C["gray_dark"], "Fuerza laboral", trend={"dir": "up", "value": "2.4%"}),
                kpi_card("🔄", "Attrition", kpis.get("attrition", 0), "%", C["gray_dark"], "Rotación general", trend={"dir": "down", "value": "1.2%"}),
                kpi_card("💰", "Avg. Income", f"${kpis.get('avg_income', 0):,}", "", C["gray_dark"], "Salario mensual", trend={"dir": "up", "value": "3.1%"}),
                kpi_card("⭐", "Performance", kpis.get("avg_perf", 0), "/ 4", C["gray_dark"], "Desempeño medio", trend={"dir": "flat", "value": "estable"}),
            ], className="fade-in-up delay-1", style={"display": "grid", "gridTemplateColumns": "repeat(4, 1fr)", "gap": "20px", "marginBottom": "30px"}),
            
            # Results Section
            html.Div([
                # Top: Large Chart
                html.Div([
                    _panel_header("Visualización", "📊"),
                    dcc.Loading(type="dot", color=C["orange"], children=[
                        dcc.Graph(id="output-chart", style={"height": "500px"}, figure=_empty_chart())
                    ])
                ], className="glass-panel fade-in-up delay-1", style={"background": C["white"], "padding": "40px", "borderRadius": "20px", "marginBottom": "30px", "boxShadow": "0 4px 15px rgba(0,0,0,0.03)"}),
                
                # Bottom: Table Output
                html.Div([
                    _panel_header("Resultados de Datos", "📋"),
                    dcc.Loading(type="dot", color=C["orange"], children=[
                        html.Div(id="output-error-block"),
                        html.Div(id="output-table-block")
                    ])
                ], className="glass-panel fade-in-up delay-2", style={"background": C["white"], "padding": "40px", "borderRadius": "20px", "boxShadow": "0 4px 15px rgba(0,0,0,0.03)"}),
            ])
            
        ], style={"padding": "40px", "background": "#f5f5f5"})
    ])

def layout_metrics():
    # Load metrics from DB
    try:
        df = pd.read_sql_query("SELECT * FROM usage_metrics", conn)
        total_queries = len(df)
        total_cost = df["cost"].sum() if total_queries > 0 else 0
        total_tokens = (df["tokens_input"] + df["tokens_output"]).sum() if total_queries > 0 else 0
    except:
        total_queries = total_cost = total_tokens = 0
        df = pd.DataFrame()

    return html.Div([
        _navbar("metrics"),
        html.Div([
            html.H2("Métricas de Uso de IA", style={"color": C["orange"], "marginBottom": "30px"}),
            html.Div([
                kpi_card("📊", "Total Prompts", total_queries, "", C["info"], "Preguntas realizadas"),
                kpi_card("🔠", "Total Tokens", f"{total_tokens:,}", "", C["gray_dark"], "Procesados por Gemini"),
                kpi_card("💵", "Costo Acumulado", f"${total_cost:.4f}", "USD", C["danger"], "Estimado API"),
            ], style={"display": "grid", "gridTemplateColumns": "repeat(3, 1fr)", "gap": "20px", "marginBottom": "40px"}),
            
            _panel_header("Historial Reciente", "🕒"),
            html.Div([
                html.Table([
                    html.Thead(html.Tr([
                        html.Th(c, style={"padding": "10px", "textAlign": "left", "background": C["gray_dark"], "color": C["white"]})
                        for c in ["Fecha", "Pregunta", "Tokens In", "Tokens Out", "Costo", "SQL Generado"]
                    ])),
                    html.Tbody([
                        html.Tr([
                            html.Td(row["timestamp"], style={"padding": "10px", "borderBottom": "1px solid #ddd"}),
                            html.Td(row["question"], style={"padding": "10px", "borderBottom": "1px solid #ddd"}),
                            html.Td(row["tokens_input"], style={"padding": "10px", "borderBottom": "1px solid #ddd"}),
                            html.Td(row["tokens_output"], style={"padding": "10px", "borderBottom": "1px solid #ddd"}),
                            html.Td(f"${row['cost']:.5f}", style={"padding": "10px", "borderBottom": "1px solid #ddd"}),
                            html.Td(html.Pre(row.get("sql_generated", "N/A") or "N/A", style={"fontSize": "10px", "maxWidth": "300px", "overflowX": "auto", "margin": 0}), style={"padding": "10px", "borderBottom": "1px solid #ddd"})
                        ]) for _, row in df.tail(10).iterrows()
                    ])
                ], style={"width": "100%", "borderCollapse": "collapse"})
            ] if len(df) > 0 else html.Div("No hay datos todavía."))
        ], className="glass-panel", style={"padding": "40px", "margin": "40px", "borderRadius": "20px"})
    ])

def layout_analytics(role):
    # Determine allowed departments if role has RLS
    allowed_dept = ROLES.get(role, {}).get("dept_filter")
    
    dept_options = [{'label': 'Todos', 'value': 'all'}]
    if allowed_dept is None:
        dept_options += [{'label': v, 'value': str(k)} for k, v in DEPT_NAMES.items()]
    else:
        dept_options += [{'label': DEPT_NAMES[allowed_dept], 'value': str(allowed_dept)}]
        
    filters_container = html.Div([
        html.Div([
            html.Div("Género", style={"fontSize": "11px", "fontWeight": "bold", "color": C["gray_dark"], "marginBottom": "5px"}),
            dcc.Dropdown(id='filter-gender', options=[{'label': 'Todos', 'value': 'all'}, {'label': 'Masculino', 'value': 'Male'}, {'label': 'Femenino', 'value': 'Female'}], value='all', clearable=False, style={"minWidth": "150px"})
        ], style={"marginRight": "20px"}),
        html.Div([
            html.Div("Nivel de Cargo", style={"fontSize": "11px", "fontWeight": "bold", "color": C["gray_dark"], "marginBottom": "5px"}),
            dcc.Dropdown(id='filter-joblevel', options=[{'label': 'Todos', 'value': 'all'}, {'label': 'Nivel 1', 'value': '1'}, {'label': 'Nivel 2', 'value': '2'}, {'label': 'Nivel 3', 'value': '3'}, {'label': 'Nivel 4', 'value': '4'}, {'label': 'Nivel 5', 'value': '5'}], value='all', clearable=False, style={"minWidth": "150px"})
        ], style={"marginRight": "20px"}),
        html.Div([
            html.Div("Departamento", style={"fontSize": "11px", "fontWeight": "bold", "color": C["gray_dark"], "marginBottom": "5px"}),
            dcc.Dropdown(id='filter-dept', options=dept_options, value='all' if allowed_dept is None else str(allowed_dept), disabled=(allowed_dept is not None), clearable=False, style={"minWidth": "200px"})
        ])
    ], style={"display": "flex", "background": C["white"], "padding": "20px 30px", "borderRadius": "15px", "marginBottom": "30px", "boxShadow": "0 4px 15px rgba(0,0,0,0.03)"})

    return html.Div([
        _navbar("analytics"),
        
        html.Div([
            html.Div([
                html.H2("People Analytics: Métricas Clave", style={"color": C["orange"], "margin": "0"}),
            ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "20px"}),
            
            filters_container,
            
            # Row 0: New KPIs
            dcc.Loading(html.Div([
                html.Div(id="kpi-stagnation"),
                html.Div(id="kpi-tenure"),
                html.Div(id="kpi-training")
            ], className="fade-in-up delay-1", style={"display": "grid", "gridTemplateColumns": "repeat(3, 1fr)", "gap": "20px", "marginBottom": "30px"})),
            
            # Row 1: Absenteeism and Overtime
            html.Div([
                # Absenteeism
                html.Div([
                    _panel_header("Tasa de Ausentismo (Simulada)", "📅"),
                    dcc.Loading(dcc.Graph(id="chart-absent", style={"height": "350px"}))
                ], className="glass-panel fade-in-up delay-1", style={"flex": "1.5", "padding": "25px", "borderRadius": "20px", "background": C["white"], "boxShadow": "0 4px 15px rgba(0,0,0,0.03)"}),
                
                # Overtime
                html.Div([
                    _panel_header("Frecuencia de Horas Extras", "⏰"),
                    html.Div(id="kpi-overtime", style={"marginBottom": "20px"}),
                    dcc.Loading(dcc.Graph(id="chart-overtime", style={"height": "200px"}))
                ], className="glass-panel fade-in-up delay-2", style={"flex": "1", "padding": "25px", "borderRadius": "20px", "marginLeft": "25px", "background": C["white"], "boxShadow": "0 4px 15px rgba(0,0,0,0.03)"})
            ], style={"display": "flex", "marginBottom": "30px"}),
            
            # Row 2: Compa-Ratio
            html.Div([
                _panel_header("Equidad Salarial Interna", "⚖️"),
                dcc.Loading(dcc.Graph(id="chart-compa", style={"height": "400px"}))
            ], className="glass-panel fade-in-up delay-3", style={"padding": "25px", "borderRadius": "20px", "background": C["white"], "boxShadow": "0 4px 15px rgba(0,0,0,0.03)"})
            
        ], style={"padding": "40px", "background": "#f5f5f5"})
    ], style={"background": "#f5f5f5", "minHeight": "100vh"})


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
    if pathname == '/dashboard':
        if not role: return dcc.Location(pathname="/", id="redirect-login")
        return layout_dashboard(role)
    elif pathname == '/metrics':
        if not role: return dcc.Location(pathname="/", id="redirect-login")
        return layout_metrics()
    elif pathname == '/analytics':
        if not role: return dcc.Location(pathname="/", id="redirect-login")
        return layout_analytics(role)
    else:
        return layout_login()

@app.callback(
    Output('store-role', 'data'),
    Output('url', 'pathname', allow_duplicate=True),
    Input('btn-login', 'n_clicks'),
    State('login-role', 'value'),
    prevent_initial_call=True
)
def handle_login(n_clicks, role):
    if role:
        return role, '/dashboard'
    return dash.no_update, dash.no_update

from datetime import datetime

@app.callback(
    Output("output-chart",       "figure"),
    Output("output-table-block", "children"),
    Output("output-error-block", "children"),
    Input("btn-ask",        "n_clicks"),
    State("input-question", "value"),
    State("store-role",     "data"),
    prevent_initial_call=True,
)
def run_query(n_clicks, question, current_role):
    empty_fig = _empty_chart()

    if not question or not question.strip():
        return empty_fig, "", html.Div("⚠ Por favor escribe una pregunta.", style={"color": C["warning"]})

    current_role = current_role or "hr_admin"

    cached_sql, _ = cache_lookup(question)
    if cached_sql:
        sql = cached_sql
        from_cache = True
        input_tok = output_tok = total_tok = cost = 0
    else:
        from_cache = False
        try:
            sql = clean_sql(vn.generate_sql(question=question, allow_llm_to_see_data=True))
            input_tok  = vn.last_input_tokens
            output_tok = vn.last_output_tokens
            cost = (input_tok * COST_INPUT_PER_1M + output_tok * COST_OUTPUT_PER_1M) / 1_000_000
            
            # Save metrics
            conn.execute(
                "INSERT INTO usage_metrics (timestamp, question, tokens_input, tokens_output, cost, sql_generated) VALUES (?,?,?,?,?,?)",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), question, input_tok, output_tok, cost, sql)
            )
            conn.commit()
        except Exception as e:
            return empty_fig, "", html.Div(f"✕ Error: {str(e)}", style={"color": C["danger"]})

    try:
        sql_run = rls_intercept(sql, current_role, conn)
    except PermissionError as pe:
        return empty_fig, "", html.Div(f"Acceso denegado: {str(pe)}", style={"color": C["danger"]})

    try:
        df = pd.read_sql_query(sql_run, conn)
        if not from_cache:
            cache_store(question, sql, "")
    except Exception as e:
        return empty_fig, "", html.Div(f"✕ Error de ejecución: {str(e)}", style={"color": C["danger"]})

    try:
        fig = generate_chart(df, question, sql)
    except Exception:
        fig = empty_fig

    if len(df) == 0:
        table = html.Div("Sin resultados.", style={"color": C["gray_mid"]})
    else:
        table = html.Div([
            html.Div(f"Resultados · {len(df)} filas", style={"fontSize": "10px", "fontWeight": "700", "color": C["gray_mid"]}),
            html.Table([
                html.Thead(html.Tr([html.Th(c, style={"padding": "8px", "background": C["gray_dark"], "color": C["white"], "fontSize": "11px"}) for c in df.columns])),
                html.Tbody([html.Tr([html.Td(str(df.iloc[i][c]), style={"padding": "7px", "fontSize": "12px", "borderBottom": "1px solid #ddd"}) for c in df.columns]) for i in range(min(15, len(df)))])
            ], style={"width": "100%", "borderCollapse": "collapse"})
        ])

    return fig, table, ""


@app.callback(
    [Output('chart-absent', 'figure'),
     Output('kpi-overtime', 'children'),
     Output('chart-overtime', 'figure'),
     Output('chart-compa', 'figure'),
     Output('kpi-stagnation', 'children'),
     Output('kpi-tenure', 'children'),
     Output('kpi-training', 'children')],
    [Input('filter-gender', 'value'),
     Input('filter-joblevel', 'value'),
     Input('filter-dept', 'value')],
    State('store-role', 'data')
)
def update_analytics_charts(gender, joblevel, dept, role):
    if not role:
        raise dash.exceptions.PreventUpdate

    # 1. Query Data securely
    query = "SELECT * FROM employees WHERE 1=1"
    if gender != 'all':
        query += f" AND Gender = '{gender}'"
    if joblevel != 'all':
        query += f" AND JobLevel = {joblevel}"
    if dept != 'all':
        query += f" AND department_id = {dept}"
        
    # Apply RLS
    query = rls_intercept(query, role, conn)
    df_emp = pd.read_sql_query(query, conn)
    
    # 2. Mock Absenteeism
    # Varies slightly based on data size to simulate filtering effect
    np.random.seed(len(df_emp))
    months = pd.date_range(end=pd.Timestamp.today(), periods=12, freq='ME').strftime('%b %Y').tolist()
    
    emp_count = len(df_emp) if len(df_emp) > 0 else 1
    absent_days = np.random.randint(int(emp_count*0.1), int(emp_count*0.8) + 1, size=12)
    work_days_total = 20 * emp_count
    absent_rate = (absent_days / work_days_total) * 100

    fig_absent = make_subplots(specs=[[{"secondary_y": True}]])
    fig_absent.add_trace(go.Bar(x=months, y=absent_days, name="Días Ausencia", marker_color=C["gray_light"]), secondary_y=False)
    fig_absent.add_trace(go.Scatter(x=months, y=absent_rate, name="Tasa %", mode="lines+markers", line=dict(color=C["orange"], width=3)), secondary_y=True)
    fig_absent.update_layout(title="Tasa de Ausentismo", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color=C["gray_dark"], family=FONT), margin=dict(l=20, r=20, t=50, b=20), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    fig_absent.update_yaxes(title_text="Días Perdidos", secondary_y=False, showgrid=False)
    fig_absent.update_yaxes(title_text="Tasa %", secondary_y=True, showgrid=False)
    
    # 3. Overtime
    ot_count = len(df_emp[df_emp['OverTime'] == 'Yes'])
    ot_rate = (ot_count / emp_count) * 100 if len(df_emp) > 0 else 0
    kpi_ot = kpi_card("⏰", "Overtime Actual", f"{ot_rate:.1f}", "%", C["danger"] if ot_rate > 10 else C["gray_dark"], "Empleados con HE")
    
    ot_trend = np.clip(np.random.normal(ot_rate, 2, 12), 0, 100)
    ot_trend[-1] = ot_rate
    fig_ot = px.line(x=months, y=ot_trend, markers=True, title="Tendencia")
    fig_ot.update_traces(line=dict(color=C["danger"], width=3))
    fig_ot.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color=C["gray_dark"], family=FONT), margin=dict(l=20, r=20, t=50, b=20), yaxis_title="% Empleados")
    fig_ot.update_yaxes(showgrid=True, gridcolor=C["gray_light"])
    fig_ot.update_xaxes(showgrid=False)
    
    # 4. Compa-Ratio
    fig_compa = _empty_chart()
    
    config = ROLES.get(role, {})
    if config.get("can_see_salary", False) and len(df_emp) > 0:
        midpoints = df_emp.groupby("JobLevel")["MonthlyIncome"].median().to_dict()
        df_emp["Midpoint"] = df_emp["JobLevel"].map(midpoints)
        df_emp["Midpoint"] = df_emp["Midpoint"].replace(0, 1)
        df_emp["CompaRatio"] = df_emp["MonthlyIncome"] / df_emp["Midpoint"]
        
        df_emp["Status"] = "En Rango"
        df_emp.loc[df_emp["CompaRatio"] > 1.15, "Status"] = "Por Encima"
        df_emp.loc[df_emp["CompaRatio"] < 0.85, "Status"] = "Por Debajo"
        
        color_map = {"En Rango": C["gray_dark"], "Por Encima": C["warning"], "Por Debajo": C["danger"]}
        fig_compa = px.scatter(df_emp, x="JobLevel", y="CompaRatio", color="Status", color_discrete_map=color_map, opacity=0.7)
        fig_compa.add_hline(y=1.15, line_dash="dash", line_color=C["orange"])
        fig_compa.add_hline(y=0.85, line_dash="dash", line_color=C["orange"])
        fig_compa.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color=C["gray_dark"], family=FONT), margin=dict(l=20, r=20, t=50, b=20), legend_title="Estado")
        fig_compa.update_yaxes(showgrid=True, gridcolor=C["gray_light"])
        fig_compa.update_xaxes(type='category', showgrid=False)
        
    # 5. Nuevos KPIs
    if len(df_emp) > 0:
        stagnant_count = len(df_emp[df_emp['YearsSinceLastPromotion'] > 5])
        stagnant_rate = (stagnant_count / emp_count) * 100
        kpi_stag = kpi_card("🛑", "Estancamiento Promocional", f"{stagnant_rate:.1f}", "%", C["danger"] if stagnant_rate > 15 else C["warning"], "Más de 5 años")
        
        avg_tenure = df_emp['YearsAtCompany'].mean()
        kpi_tenure = kpi_card("🏢", "Antigüedad Promedio", f"{avg_tenure:.1f}", "años", C["info"], "Permanencia laboral")
        
        avg_train = df_emp['TrainingTimesLastYear'].mean()
        kpi_train = kpi_card("🎓", "Capacitación Anual", f"{avg_train:.1f}", "veces", C["success"], "Promedio por empleado")
    else:
        kpi_stag = kpi_card("🛑", "Estancamiento", "0", "%", C["gray_mid"], "Sin datos")
        kpi_tenure = kpi_card("🏢", "Antigüedad", "0", "años", C["gray_mid"], "Sin datos")
        kpi_train = kpi_card("🎓", "Capacitación", "0", "veces", C["gray_mid"], "Sin datos")

    return fig_absent, kpi_ot, fig_ot, fig_compa, kpi_stag, kpi_tenure, kpi_train

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8051))
    app.run(host="0.0.0.0", port=port, debug=False)
