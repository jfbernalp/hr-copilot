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
import plotly.express as px
import plotly.graph_objects as go
import google.genai as genai
import dash
from dash import dcc, html, Input, Output, State, callback_context
from dotenv import load_dotenv
from vanna.legacy.chromadb.chromadb_vector import ChromaDB_VectorStore
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
from rls import rls_intercept, ROLES, DEPT_NAMES

load_dotenv(os.path.join(BASE_DIR, ".env"))
API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    print("ERROR: No API key found. Add GEMINI_API_KEY or GOOGLE_API_KEY to .env")
    sys.exit(1)

COST_INPUT_PER_1M  = 0.075
COST_OUTPUT_PER_1M = 0.30


# ── Vanna + Gemini ─────────────────────────────────────────────────────────────
class HRCopilot(ChromaDB_VectorStore, VannaBase):
    def __init__(self, config=None):
        ChromaDB_VectorStore.__init__(self, config=config)
        VannaBase.__init__(self, config=config)
        self._client    = genai.Client(api_key=config.get("api_key"))
        self.model_name = config.get("model", "gemini-2.5-flash")
        self.last_input_tokens = self.last_output_tokens = self.last_total_tokens = 0

    def system_message(self, message): return message
    def user_message(self, message):   return message
    def assistant_message(self, message): return message

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
def kpi_card(icon, label, value, unit="", color=None, sublabel=""):
    accent = color or C["orange"]
    return html.Div([
        html.Div([
            html.Div([
                html.Span(str(value), style={
                    "fontSize": "46px", "fontWeight": "900", "color": accent, "lineHeight": "1", "fontFamily": FONT,
                }),
                html.Span(f" {unit}", style={
                    "fontSize": "16px", "fontWeight": "600", "color": C["gray_mid"],
                }) if unit else None,
            ]),
        ], style={"display": "flex", "justifyContent": "flex-start", "alignItems": "center"}),
        
        html.Div([
            html.Div(label, style={
                "fontSize": "12px", "fontWeight": "700", "color": C["gray_dark"],
                "textTransform": "uppercase", "letterSpacing": "0.05em",
            }),
            html.Div(sublabel, style={
                "fontSize": "11px", "color": C["gray_mid"], "fontWeight": "500", "marginTop": "4px",
            }) if sublabel else None,
        ], style={"marginTop": "15px"})
    ], style={
        "background": C["white"], "borderRadius": "25px", "padding": "24px",
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
app = dash.Dash(__name__, title="HR Copilot — Práxedes v2")
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

def build_layout():
    kpis = get_kpis()

    return html.Div([
        dcc.Store(id="store-role", data="hr_admin"),

        # ── MAIN LAYOUT (Sidebar + Content) ──────────────────────────────────
        html.Div([
            
            # ── SIDEBAR ────────────────────────────────────────────────────────
            html.Div([
                # Logo Area
                html.Div([
                    html.Div(style={"width": "32px", "height": "32px", "background": C["orange"], "borderRadius": "8px", "marginRight": "12px"}),
                    html.Div([
                        html.Div("práxedes", style={"fontFamily": FONT, "fontSize": "20px", "fontWeight": "900", "color": C["white"], "letterSpacing": "-0.02em", "lineHeight": "1"}),
                        html.Div("HR Copilot", style={"fontSize": "11px", "color": C["orange"], "fontWeight": "700", "marginTop": "2px"}),
                    ])
                ], style={"display": "flex", "alignItems": "center", "marginBottom": "40px"}),

                # Role Selector
                html.Div([
                    html.Div("TU ROL DE ACCESO", style={"fontSize": "10px", "fontWeight": "700", "color": "#888", "letterSpacing": "0.1em", "marginBottom": "10px"}),
                    dcc.Dropdown(
                        id="dropdown-role",
                        options=[{"label": v, "value": k} for k, v in ROLE_LABELS.items()],
                        value="hr_admin",
                        clearable=False,
                        style={"fontFamily": FONT, "fontSize": "12px", "color": C["gray_dark"], "borderRadius": "10px"}
                    ),
                    html.Div(id="rls-badge", style={"marginTop": "10px"}),
                ], style={"marginBottom": "40px", "background": "rgba(255,255,255,0.05)", "padding": "15px", "borderRadius": "15px"}),

                # Suggested Prompts
                html.Div([
                    html.Div("SUGERENCIAS DE IA", style={"fontSize": "10px", "fontWeight": "700", "color": "#888", "letterSpacing": "0.1em", "marginBottom": "15px"}),
                    html.Div([
                        html.Button(q,
                            id={"type": "suggestion", "index": i}, n_clicks=0,
                            style={
                                "display": "block", "width": "100%", "textAlign": "left",
                                "background": "transparent", "border": "1px solid rgba(255,255,255,0.1)",
                                "borderRadius": "12px", "color": "#ccc", "fontSize": "12px",
                                "fontWeight": "500", "padding": "10px 14px", "cursor": "pointer",
                                "fontFamily": FONT, "marginBottom": "8px", "transition": "all 0.2s"
                            },
                        ) for i, q in enumerate(SUGGESTED)
                    ])
                ]),
                
                # Footer Sidebar
                html.Div([
                    html.Div("v2.0 • Security Enforced", style={"fontSize": "10px", "color": "#666", "textAlign": "center"})
                ], style={"marginTop": "auto", "paddingTop": "20px"})

            ], style={
                "width": "280px", "background": C["gray_dark"], "minHeight": "100vh",
                "padding": "30px 20px", "display": "flex", "flexDirection": "column",
                "position": "fixed", "left": "0", "top": "0", "zIndex": "100"
            }),

            # ── MAIN CONTENT CANVAS ─────────────────────────────────────────────
            html.Div([
                
                # ── HERO BANNER ────────────────────────────────────────────────
                html.Div([
                    html.Div(style={"position": "absolute", "top": "-50px", "right": "-50px", "width": "200px", "height": "200px", "borderRadius": "50%", "background": "rgba(255,255,255,0.15)"}),
                    html.Div(style={"position": "absolute", "bottom": "-30px", "right": "100px", "width": "100px", "height": "100px", "borderRadius": "50%", "background": "rgba(255,255,255,0.1)"}),
                    html.Div([
                        html.H1("Hola, ¿qué datos necesitas hoy?", style={"color": C["white"], "fontSize": "28px", "fontWeight": "800", "marginBottom": "8px"}),
                        html.P("Explora la información de talento humano usando lenguaje natural.", style={"color": C["orange_light"], "fontSize": "14px", "margin": "0"}),
                    ], style={"position": "relative", "zIndex": "1"}),
                    
                    # Profile Mock (From Manual)
                    html.Div([
                        html.Div(style={"width": "40px", "height": "40px", "borderRadius": "50%", "background": C["white"], "marginRight": "12px", "display": "flex", "alignItems": "center", "justifyContent": "center", "fontSize": "20px"}),
                        html.Div([
                            html.Div("Juan Felipe Bernal", style={"color": C["white"], "fontSize": "13px", "fontWeight": "700"}),
                            html.Div("ID: 1019011143", style={"color": "rgba(255,255,255,0.7)", "fontSize": "11px"}),
                        ])
                    ], style={"position": "absolute", "right": "40px", "top": "50%", "transform": "translateY(-50%)", "display": "flex", "alignItems": "center", "background": "rgba(0,0,0,0.2)", "padding": "10px 20px", "borderRadius": "25px"})
                    
                ], className="fade-in-up", style={
                    "background": f"linear-gradient(135deg, {C['orange']} 0%, {C['orange_dark']} 100%)",
                    "borderRadius": "25px", "padding": "40px", "marginBottom": "30px",
                    "position": "relative", "overflow": "hidden", "boxShadow": "0 10px 20px rgba(255,139,0,0.2)"
                }),

                # ── KPI SECTION ────────────────────────────────────────────────
                html.Div([
                    kpi_card("👥", "Headcount", f"{kpis.get('headcount', 0):,}", "emp", C["gray_dark"], "Fuerza laboral"),
                    kpi_card("📉", "Attrition", kpis.get("attrition", 0), "%", C["danger"], "Rotación general"),
                    kpi_card("💰", "Avg. Income", f"${kpis.get('avg_income', 0):,}", "", C["info"], "Salario mensual"),
                    kpi_card("⭐", "Performance", kpis.get("avg_perf", 0), "/ 4", C["success"], "Desempeño medio"),
                ], className="fade-in-up delay-1", style={"display": "grid", "gridTemplateColumns": "repeat(4, 1fr)", "gap": "20px", "marginBottom": "30px"}),

                # ── CONVERSATION & CHART SPLIT ─────────────────────────────────
                html.Div([
                    
                    # Left: Chat Area
                    html.Div([
                        _panel_header("Consultor Inteligente", "💬"),
                        
                        # Input Moderno
                        html.Div([
                            dcc.Input(
                                id="input-question", type="text", debounce=False, n_submit=0,
                                placeholder="Ej: ¿Cuáles son los departamentos con mayor rotación?",
                                style={
                                    "width": "100%", "background": C["gray_bg"],
                                    "border": "2px solid transparent", "borderRadius": "20px",
                                    "color": C["gray_dark"], "fontSize": "14px", "padding": "16px 20px",
                                    "fontFamily": FONT, "fontWeight": "500", "transition": "all 0.3s",
                                    "boxShadow": "inset 0 2px 4px rgba(0,0,0,0.02)", "minHeight": "55px",
                                    "lineHeight": "1.5", "boxSizing": "border-box"
                                },
                            ),
                            html.Button("Generar Insight ✨", id="btn-ask", n_clicks=0, style={
                                "background": C["gray_dark"], "border": "none",
                                "borderRadius": "20px", "color": C["white"],
                                "fontWeight": "700", "fontSize": "13px",
                                "padding": "16px 24px", "cursor": "pointer",
                                "fontFamily": FONT, "whiteSpace": "nowrap",
                                "marginTop": "15px", "width": "100%", "boxShadow": "0 4px 10px rgba(0,0,0,0.1)"
                            }),
                        ], style={"marginBottom": "25px"}),

                        # Results Area
                        dcc.Loading(
                            type="dot", color=C["orange"],
                            children=[
                                html.Div(id="output-sql-block"),
                                html.Div(id="output-token-block"),
                                html.Div(id="output-error-block"),
                            ]
                        )
                        
                    ], className="glass-panel fade-in-up delay-2", style={
                        "borderRadius": "25px", "padding": "30px", "flex": "1"
                    }),

                    # Right: Chart & Table Area
                    html.Div([
                        _panel_header("Visualización de Datos", "📊"),
                        dcc.Loading(
                            type="dot", color=C["orange"],
                            children=[
                                html.Div(
                                    dcc.Graph(
                                        id="output-chart",
                                        style={"height": "350px"},
                                        config={"displayModeBar": True, "displaylogo": False},
                                        figure=_empty_chart(),
                                    ),
                                    style={"background": C["gray_bg"], "borderRadius": "20px", "padding": "10px", "marginBottom": "20px"}
                                ),
                                html.Div(id="output-table-block"),
                            ]
                        )
                    ], className="glass-panel fade-in-up delay-3", style={
                        "borderRadius": "25px", "padding": "30px", "flex": "1.5"
                    }),

                ], style={"display": "flex", "gap": "25px"})

            ], style={"marginLeft": "280px", "padding": "30px 40px", "width": "calc(100% - 280px)"})

        ], style={"display": "flex"})
    ])


app.layout = build_layout


# ── Callbacks ──────────────────────────────────────────────────────────────────
@app.callback(
    Output("store-role",  "data"),
    Output("rls-badge",   "children"),
    Input("dropdown-role", "value"),
)
def update_role(role):
    role = role if role in ROLES else "hr_admin"
    config = ROLES[role]

    parts = []
    if config["dept_filter"] is not None:
        parts.append(f"Solo {DEPT_NAMES.get(config['dept_filter'], 'dept ' + str(config['dept_filter']))}")
    if not config["can_see_salary"]:
        parts.append("Sin salarios")

    text   = " · ".join(parts) if parts else "Sin restricciones"
    active = bool(parts)
    badge  = html.Span(text, style={
        "fontSize": "11px", "fontWeight": "600",
        "color":      C["orange"]     if active else C["gray_mid"],
        "background": C["orange_light"] if active else C["gray_bg"],
        "border":     f"1.5px solid {C['orange'] if active else C['gray_light']}",
        "padding": "4px 12px", "borderRadius": "20px",
    })
    return role, badge


@app.callback(
    Output("input-question", "value"),
    Input({"type": "suggestion", "index": dash.ALL}, "n_clicks"),
    State("input-question", "value"),
    prevent_initial_call=True,
)
def fill_suggestion(n_clicks_list, current_value):
    ctx = callback_context
    if not ctx.triggered:
        return current_value or ""
    idx = json.loads(ctx.triggered[0]["prop_id"].split(".")[0])["index"]
    return SUGGESTED[idx]


@app.callback(
    Output("output-sql-block",   "children"),
    Output("output-token-block", "children"),
    Output("output-chart",       "figure"),
    Output("output-table-block", "children"),
    Output("output-error-block", "children"),
    Input("btn-ask",        "n_clicks"),
    Input("input-question", "n_submit"),
    State("input-question", "value"),
    State("store-role",     "data"),
    prevent_initial_call=True,
)
def run_query(n_clicks, n_submit, question, current_role):
    empty_fig = _empty_chart()

    if not question or not question.strip():
        return "", "", empty_fig, "", html.Div(
            "⚠ Por favor escribe una pregunta.",
            style={"color": C["warning"], "fontSize": "13px", "fontWeight": "500"},
        )

    current_role = current_role or "hr_admin"

    # ── SQL generation ─────────────────────────────────────────────────────────
    cached_sql, _ = cache_lookup(question)
    if cached_sql:
        sql        = cached_sql
        from_cache = True
        input_tok  = output_tok = total_tok = 0
    else:
        from_cache = False
        try:
            sql = clean_sql(vn.generate_sql(question=question, allow_llm_to_see_data=True))
            input_tok  = vn.last_input_tokens
            output_tok = vn.last_output_tokens
            total_tok  = vn.last_total_tokens
        except Exception as e:
            return "", "", empty_fig, "", html.Div([
                html.Span("✕  Error: ", style={"fontWeight": "700", "color": C["danger"]}),
                html.Span(str(e), style={"fontSize": "12px"}),
            ], style={"color": C["danger"], "padding": "10px 0", "fontSize": "13px"})

    # ── RLS intercept ──────────────────────────────────────────────────────────
    try:
        sql_run = rls_intercept(sql, current_role, conn)
    except PermissionError as pe:
        return "", "", empty_fig, "", html.Div([
            html.Span("Acceso denegado: ", style={"fontWeight": "700", "color": C["danger"]}),
            html.Span(str(pe), style={"fontSize": "12px"}),
        ], style={"color": C["danger"], "padding": "10px 0", "fontSize": "13px"})

    # ── Execute SQL ────────────────────────────────────────────────────────────
    try:
        df = pd.read_sql_query(sql_run, conn)
        if not from_cache:
            cache_store(question, sql, "")
    except Exception as e:
        return "", "", empty_fig, "", html.Div([
            html.Span("✕  Error de ejecución: ", style={"fontWeight": "700", "color": C["danger"]}),
            html.Span(str(e), style={"fontSize": "12px"}),
        ], style={"color": C["danger"], "padding": "10px 0", "fontSize": "13px"})

    # ── SQL block ──────────────────────────────────────────────────────────────
    rls_modified = sql_run.strip() != sql.strip()

    badges = []
    if from_cache:
        badges.append(html.Span("caché ⚡", style={
            "background": "#fff3e0", "color": C["orange"],
            "fontSize": "10px", "fontWeight": "600",
            "padding": "2px 8px", "borderRadius": "20px", "marginLeft": "8px",
        }))
    if rls_modified:
        badges.append(html.Span("RLS aplicado", style={
            "background": C["orange_light"], "color": C["orange_dark"],
            "fontSize": "10px", "fontWeight": "600",
            "padding": "2px 8px", "borderRadius": "20px", "marginLeft": "8px",
        }))

    sql_block = html.Div([
        html.Div([
            html.Span("SQL generado", style={
                "fontSize": "10px", "fontWeight": "700", "color": C["gray_mid"],
                "textTransform": "uppercase", "letterSpacing": "0.07em",
            }),
            *badges,
        ], style={"marginBottom": "8px", "display": "flex", "alignItems": "center"}),
        html.Pre(sql_run.strip(), style={
            "background": C["gray_bg"],
            "border": f"1.5px solid {C['gray_light']}",
            "borderLeft": f"4px solid {C['orange']}",
            "borderRadius": "0 12px 12px 0",
            "padding": "12px 14px", "fontSize": "11px",
            "color": C["gray_dark"],
            "fontFamily": "'Courier New', monospace",
            "overflowX": "auto", "whiteSpace": "pre-wrap", "margin": "0",
        }),
    ])

    # ── Token block ────────────────────────────────────────────────────────────
    if from_cache:
        token_block = html.Div(
            html.Span("⚡ Respuesta desde caché · 0 tokens · $0.0000", style={
                "fontSize": "11px", "color": C["orange"], "fontWeight": "500",
            }),
            style={"marginTop": "8px"},
        )
    else:
        cost = (input_tok * COST_INPUT_PER_1M + output_tok * COST_OUTPUT_PER_1M) / 1_000_000
        token_block = html.Div([
            html.Span("◈ ", style={"color": C["orange"]}),
            html.Span(
                f"{total_tok:,} tokens  ·  in {input_tok:,}  out {output_tok:,}  ·  ",
                style={"fontSize": "11px", "color": C["gray_mid"], "fontWeight": "500"},
            ),
            html.Span(f"${cost:.5f}", style={
                "fontSize": "11px", "color": C["orange"], "fontWeight": "700",
            }),
        ], style={"marginTop": "8px"})

    # ── Chart ──────────────────────────────────────────────────────────────────
    try:
        fig = generate_chart(df, question, sql)
    except Exception as chart_err:
        print(f"Chart error: {chart_err}")
        fig = empty_fig

    # ── Table ──────────────────────────────────────────────────────────────────
    if len(df) == 0:
        table = html.Div("Sin resultados.",
                         style={"color": C["gray_mid"], "fontSize": "13px", "marginTop": "12px"})
    else:
        rows = min(15, len(df))
        table = html.Div([
            html.Div(style={
                "height": "3px", "borderRadius": "25px",
                "background": C["gray_light"], "margin": "14px 0 12px",
            }),
            html.Div(f"Resultados · {len(df)} filas", style={
                "fontSize": "10px", "fontWeight": "700", "color": C["gray_mid"],
                "textTransform": "uppercase", "letterSpacing": "0.07em",
                "marginBottom": "10px",
            }),
            html.Div([
                html.Table([
                    html.Thead(html.Tr([
                        html.Th(c, style={
                            "padding": "8px 14px", "textAlign": "left",
                            "color": C["white"], "background": C["gray_dark"],
                            "fontSize": "11px", "fontWeight": "700",
                            "letterSpacing": "0.04em", "whiteSpace": "nowrap",
                        }) for c in df.columns
                    ])),
                    html.Tbody([
                        html.Tr([
                            html.Td(str(df.iloc[i][c]), style={
                                "padding": "7px 14px", "fontSize": "12px",
                                "color": C["gray_dark"], "fontWeight": "500",
                                "borderBottom": f"1px solid {C['gray_light']}",
                                "whiteSpace": "nowrap",
                                "background": C["white"] if i % 2 == 0 else C["gray_bg"],
                            }) for c in df.columns
                        ]) for i in range(rows)
                    ]),
                ], style={
                    "borderCollapse": "collapse", "width": "100%",
                    "borderRadius": "12px", "overflow": "hidden",
                }),
            ], style={"overflowX": "auto", "borderRadius": "12px"}),
        ])

    return sql_block, token_block, fig, table, ""


# ── Run ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("  Dashboard Práxedes starting at http://127.0.0.1:8051")
    app.run(debug=False, port=8051)
