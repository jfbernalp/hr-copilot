"""
dashboard.py
------------
HR Copilot — People Analytics Text-to-SQL Dashboard
Dark theme with purple accents. Full layout: KPI cards + chat interface.

Run from project root:
    python dashboard.py
"""

import os
import sys
import json
import hashlib
import sqlite3
import pandas as pd
import plotly.graph_objects as go
import google.genai as genai
import dash
from dash import dcc, html, Input, Output, State, callback_context
from dotenv import load_dotenv
from vanna.legacy.chromadb.chromadb_vector import ChromaDB_VectorStore
from vanna.legacy.base.base import VannaBase

# ── Paths & Config ────────────────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR    = (
    os.path.dirname(_SCRIPT_DIR)
    if os.path.basename(_SCRIPT_DIR) == "app"
    else _SCRIPT_DIR
)
DB_PATH    = os.path.join(BASE_DIR, "data", "hr_analytics.db")
CHROMA_DIR = os.path.join(BASE_DIR, "chroma_db")

load_dotenv(os.path.join(BASE_DIR, ".env"))
API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    print("ERROR: No API key found. Add GEMINI_API_KEY or GOOGLE_API_KEY to .env")
    sys.exit(1)

# Gemini 2.5 Flash pricing (USD per 1M tokens, as of 2025)
COST_INPUT_PER_1M  = 0.075
COST_OUTPUT_PER_1M = 0.30


# ── Vanna class ───────────────────────────────────────────────────────────────
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


# ── Initialize Vanna ──────────────────────────────────────────────────────────
# ── SQL safety net ────────────────────────────────────────────────────────────
def clean_sql(sql: str) -> str:
    """Catches common Gemini SQL generation errors before execution."""
    import re as _re
    sql = _re.sub(r"```sql|```", "", sql).strip()
    if sql.count("(") != sql.count(")"):
        raise ValueError(
            f"Generated SQL has unbalanced parentheses "
            f"({sql.count(chr(40))} open, {sql.count(chr(41))} close). "
            "Try rephrasing your question."
        )
    return sql


print("Initializing HR Copilot...")
vn = HRCopilot(config={
    "api_key":                  API_KEY,
    "model":                    "gemini-2.5-flash",
    "chroma_persist_directory": CHROMA_DIR,
})
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
vn.run_sql = lambda sql: pd.read_sql_query(sql, conn)
vn.run_sql_is_set = True
print("  Vanna ready.")


# ── Smart chart selector v2 ───────────────────────────────────────────────────
import re
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

def _is_cat(series):
    """Robust categorical detection — handles pandas 2.x StringDtype."""
    dt = series.dtype
    return (dt == object or
            'str' in str(dt).lower() or
            'object' in str(dt).lower() or
            str(dt) == 'category' or
            pd.api.types.is_string_dtype(dt))

def _cat_cols(df):
    return [c for c in df.columns if _is_cat(df[c])]

def _num_cols(df):
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]

def _time_cols(df):
    """Only match time keywords as whole words (not substrings of 'monthly' etc.)"""
    kw = ["year","month","date","time","periodo","mes","ano","trimestre","quarter"]
    result = []
    for c in df.columns:
        # Split column name into tokens by underscore, space, camelCase boundary
        tokens = re.split(r'[_\s]', c.lower())
        if any(t in kw for t in tokens):
            result.append(c)
    return result

def smart_chart(df: pd.DataFrame, question: str, colorway: list) -> go.Figure:
    """
    Selects the best Plotly chart based on data shape + question intent.
    Priority:
      1. Single row       → KPI scorecard
      2. Time column      → line chart
      3. Pct col + cats   → donut chart
      4. Distribution kw  → box plot
      5. Correlation kw   → scatter (many rows, no cats) OR grouped bar
      6. 2 rows           → horizontal comparison bar
      7. >6 rows + cat    → horizontal bar
      8. ≤6 rows + cat    → vertical bar
      9. Fallback         → vertical bar / line
    """
    if df is None or len(df) == 0:
        return go.Figure()

    q     = question.lower()
    nrows = len(df)
    cats  = _cat_cols(df)
    nums  = _num_cols(df)
    times = _time_cols(df)

    # ── 1. Single row → KPI scorecard ────────────────────────────────────────
    if nrows == 1:
        fig = go.Figure()
        for i, col in enumerate(nums[:4]):
            fig.add_trace(go.Indicator(
                mode="number", value=float(df.iloc[0][col]),
                title={"text": col.replace("_"," ").title()},
                domain={"row":0,"column":i},
                number={"font":{"size":48,"color":colorway[i%len(colorway)]}},
            ))
        fig.update_layout(grid={"rows":1,"columns":max(len(nums[:4]),1)},
                          title=question[:60])
        return fig

    # ── 2. Time series → line ─────────────────────────────────────────────────
    if times and nums:
        y_cols = [c for c in nums if c not in times][:3]
        if y_cols:
            fig = px.line(df, x=times[0], y=y_cols, title=question[:60],
                          markers=True, color_discrete_sequence=colorway)
            fig.update_traces(line=dict(width=2.5))
            return fig

    # ── 3. Percentage col + few cats → donut ─────────────────────────────────
    pct_kw = ["pct","percent","porcentaje","ratio","rate","tasa","proporcion"]
    pct    = [c for c in nums if any(k in c.lower() for k in pct_kw)]
    if pct and cats and nrows <= 6:
        fig = px.pie(df, names=cats[0], values=pct[0], title=question[:60],
                     color_discrete_sequence=colorway, hole=0.38)
        fig.update_traces(textposition="inside", textinfo="percent+label")
        return fig

    # ── 4. Distribution intent → box plot ────────────────────────────────────
    dist_kw = ["distribucion","distribución","distribution","spread",
               "variacion","variación","dispersion","boxplot","box","rango"]
    if any(k in q for k in dist_kw) and cats and nums:
        fig = px.box(df, x=cats[0], y=nums[0], title=question[:60],
                     color=cats[0], color_discrete_sequence=colorway,
                     points="outliers")
        return fig

    # ── 5. Correlation / comparison intent ───────────────────────────────────
    corr_kw = ["relacion","relación","correlacion","correlación","correlation",
               "vs","versus","impacto","impact","afecta","influye",
               "between","entre","comparar","compare"]
    is_corr = any(k in q for k in corr_kw)

    if is_corr:
        # Only scatter when many rows AND purely numeric (no categories)
        if nrows >= 10 and len(nums) >= 2 and not cats:
            fig = px.scatter(df, x=nums[0], y=nums[1], title=question[:60],
                             color_discrete_sequence=colorway)
            fig.update_traces(marker=dict(size=8, opacity=0.7))
            return fig
        # Categorical groups → bar is always clearer
        if cats and nums:
            cnt_kw = ["count","total","n_","empleados","employees","headcount"]
            metric = next((c for c in nums
                           if not any(k in c.lower() for k in cnt_kw)), nums[0])
            fig = px.bar(df, x=cats[0], y=metric, title=question[:60],
                         color=cats[0], text=df[metric].round(1),
                         color_discrete_sequence=colorway)
            fig.update_traces(textposition="outside")
            fig.update_layout(showlegend=False)
            return fig

    # ── 6. Exactly 2 rows → horizontal comparison bar ────────────────────────
    if nrows == 2 and cats and nums:
        cnt_kw = ["count","total","n_","empleados","employees","headcount"]
        metrics = [c for c in nums
                   if not any(k in c.lower() for k in cnt_kw)] or nums
        fig = go.Figure()
        for i, col in enumerate(metrics[:2]):
            fig.add_trace(go.Bar(
                y=df[cats[0]], x=df[col],
                name=col.replace("_"," ").title(),
                orientation="h",
                marker_color=colorway[i%len(colorway)],
                text=df[col].round(1), textposition="outside",
            ))
        fig.update_layout(barmode="group", title=question[:60])
        return fig

    # ── 7. Many rows + category → horizontal bar ─────────────────────────────
    if cats and nums and nrows > 6:
        sdf = df.head(20).sort_values(nums[0], ascending=True)
        fig = go.Figure(go.Bar(
            y=sdf[cats[0]], x=sdf[nums[0]], orientation="h",
            marker_color=colorway[0],
            text=sdf[nums[0]].round(1), textposition="outside",
        ))
        fig.update_layout(title=question[:60])
        return fig

    # ── 8. Few rows + category → vertical bar ────────────────────────────────
    if cats and nums:
        fig = px.bar(df, x=cats[0], y=nums[0], title=question[:60],
                     color=cats[0], text=df[nums[0]].round(1),
                     color_discrete_sequence=colorway)
        fig.update_traces(textposition="outside")
        fig.update_layout(showlegend=False)
        return fig

    # ── 9. Pure numeric → line ────────────────────────────────────────────────
    if len(nums) >= 2:
        fig = px.line(df, y=nums[:3], title=question[:60],
                      color_discrete_sequence=colorway, markers=True)
        return fig

    return go.Figure()


# ── KPI helpers ───────────────────────────────────────────────────────────────
def get_kpis():
    try:
        total        = pd.read_sql("SELECT COUNT(*) AS n FROM employees", conn).iloc[0]["n"]
        attrition    = pd.read_sql("SELECT ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) AS r FROM employees", conn).iloc[0]["r"]
        avg_income   = pd.read_sql("SELECT ROUND(AVG(MonthlyIncome),0) AS r FROM employees", conn).iloc[0]["r"]
        overtime_pct = pd.read_sql("SELECT ROUND(100.0*SUM(CASE WHEN OverTime='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) AS r FROM employees", conn).iloc[0]["r"]
        avg_perf     = pd.read_sql("SELECT ROUND(AVG(PerformanceRating),2) AS r FROM satisfaction", conn).iloc[0]["r"]
        avg_sat      = pd.read_sql("SELECT ROUND(AVG(JobSatisfaction),2) AS r FROM satisfaction", conn).iloc[0]["r"]
        return {
            "headcount":    int(total),
            "attrition":    float(attrition),
            "avg_income":   int(avg_income),
            "overtime_pct": float(overtime_pct),
            "avg_perf":     float(avg_perf),
            "avg_sat":      float(avg_sat),
        }
    except Exception as e:
        print(f"KPI error: {e}")
        return {}


# ── Query cache ───────────────────────────────────────────────────────────────
def cache_lookup(question: str):
    h = hashlib.md5(question.strip().lower().encode()).hexdigest()
    try:
        row = pd.read_sql(
            "SELECT sql_generated, result_json FROM query_cache WHERE question_hash=?",
            conn, params=(h,)
        )
        if len(row):
            return row.iloc[0]["sql_generated"], row.iloc[0]["result_json"]
    except Exception:
        pass
    return None, None

def cache_store(question: str, sql: str, result_json: str):
    h = hashlib.md5(question.strip().lower().encode()).hexdigest()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO query_cache(question_hash,question,sql_generated,result_json) VALUES(?,?,?,?)",
            (h, question, sql, result_json)
        )
        conn.commit()
    except Exception:
        pass


# ── Design tokens ─────────────────────────────────────────────────────────────
C = {
    "bg":        "#0E0B1A",
    "surface":   "#16112B",
    "surface2":  "#1E1836",
    "border":    "#2D2550",
    "purple":    "#9B6DFF",
    "purple_dim":"#6B45CC",
    "teal":      "#2DD4BF",
    "text":      "#EDE9FE",
    "muted":     "#7C6FA0",
    "danger":    "#F87171",
    "success":   "#34D399",
    "warning":   "#FBBF24",
}

FONT_MONO = "'JetBrains Mono', 'Fira Code', monospace"
FONT_BODY = "'DM Sans', 'IBM Plex Sans', sans-serif"

SUGGESTED = [
    "What is the overall attrition rate?",
    "Which departments have the highest turnover?",
    "Is there a gender pay gap?",
    "Who is at highest burnout risk?",
    "What is the average salary by job level?",
    "How does overtime affect attrition?",
]


# ── Layout ────────────────────────────────────────────────────────────────────
app = dash.Dash(__name__, title="HR Copilot")

app.index_string = """
<!DOCTYPE html>
<html>
<head>
    {%metas%}
    <title>{%title%}</title>
    {%favicon%}
    {%css%}
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #0E0B1A; color: #EDE9FE; font-family: 'DM Sans', sans-serif; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #16112B; }
        ::-webkit-scrollbar-thumb { background: #2D2550; border-radius: 3px; }
        input:focus { outline: none !important; }
    </style>
</head>
<body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body>
</html>
"""

def kpi_card(label, value, unit="", color=None, sublabel=""):
    accent = color or C["purple"]
    return html.Div([
        html.Div(label, style={
            "fontSize": "11px", "letterSpacing": "0.08em",
            "color": C["muted"], "textTransform": "uppercase",
            "marginBottom": "10px", "fontWeight": "500",
        }),
        html.Div([
            html.Span(str(value), style={
                "fontSize": "32px", "fontWeight": "700",
                "color": accent, "fontFamily": "'Space Grotesk', sans-serif",
                "lineHeight": "1",
            }),
            html.Span(unit, style={
                "fontSize": "14px", "color": C["muted"],
                "marginLeft": "4px", "fontWeight": "400",
            }),
        ]),
        html.Div(sublabel, style={
            "fontSize": "11px", "color": C["muted"],
            "marginTop": "6px",
        }) if sublabel else None,
        html.Div(style={
            "position": "absolute", "bottom": "0", "left": "0",
            "right": "0", "height": "2px",
            "background": f"linear-gradient(90deg, {accent}60, transparent)",
            "borderRadius": "0 0 8px 8px",
        }),
    ], style={
        "background": C["surface"],
        "border": f"1px solid {C['border']}",
        "borderRadius": "10px",
        "padding": "18px 20px 20px",
        "position": "relative",
        "overflow": "hidden",
        "flex": "1",
        "minWidth": "140px",
    })

def build_layout():
    kpis = get_kpis()
    return html.Div([

        # ── Header ────────────────────────────────────────────────────────────
        html.Div([
            html.Div([
                html.Div("⬡", style={
                    "fontSize": "22px", "color": C["purple"],
                    "marginRight": "10px", "lineHeight": "1",
                }),
                html.Div([
                    html.Span("HR", style={
                        "fontFamily": "'Space Grotesk', sans-serif",
                        "fontSize": "20px", "fontWeight": "700",
                        "color": C["text"],
                    }),
                    html.Span(" Copilot", style={
                        "fontFamily": "'Space Grotesk', sans-serif",
                        "fontSize": "20px", "fontWeight": "400",
                        "color": C["purple"],
                    }),
                ]),
            ], style={"display": "flex", "alignItems": "center"}),
            html.Div([
                html.Span("IBM HR Analytics · 1,470 employees · Gemini 2.5 Flash", style={
                    "fontSize": "12px", "color": C["muted"],
                    "fontFamily": FONT_MONO,
                }),
            ]),
        ], style={
            "display": "flex", "justifyContent": "space-between",
            "alignItems": "center",
            "padding": "16px 28px",
            "borderBottom": f"1px solid {C['border']}",
            "background": C["surface"],
        }),

        # ── KPI Cards ─────────────────────────────────────────────────────────
        html.Div([
            kpi_card("Total headcount", f"{kpis.get('headcount', 0):,}", "employees",
                     C["purple"], "Active workforce"),
            kpi_card("Attrition rate", kpis.get("attrition", 0), "%",
                     C["danger"], "Employees who left"),
            kpi_card("Avg. monthly income", f"${kpis.get('avg_income', 0):,}",
                     "/ month", C["teal"], "All employees"),
            kpi_card("Overtime rate", kpis.get("overtime_pct", 0), "%",
                     C["warning"], "Working overtime"),
            kpi_card("Avg. performance", kpis.get("avg_perf", 0), "/ 4",
                     C["success"], "PerformanceRating score"),
            kpi_card("Avg. job satisfaction", kpis.get("avg_sat", 0), "/ 4",
                     C["purple"], "JobSatisfaction score"),
        ], style={
            "display": "flex", "gap": "14px",
            "padding": "20px 28px",
            "flexWrap": "wrap",
        }),

        # ── Divider ───────────────────────────────────────────────────────────
        html.Div(style={
            "height": "1px", "background": C["border"],
            "margin": "0 28px",
        }),

        # ── Suggested questions ───────────────────────────────────────────────
        html.Div([
            html.Div("Try asking:", style={
                "fontSize": "11px", "color": C["muted"],
                "textTransform": "uppercase", "letterSpacing": "0.08em",
                "marginBottom": "10px", "fontWeight": "500",
            }),
            html.Div([
                html.Button(q, id={"type": "suggestion", "index": i},
                    n_clicks=0,
                    style={
                        "background": C["surface2"],
                        "border": f"1px solid {C['border']}",
                        "borderRadius": "20px",
                        "color": C["text"], "fontSize": "12px",
                        "padding": "6px 14px", "cursor": "pointer",
                        "fontFamily": FONT_BODY,
                        "transition": "all 0.15s",
                        "whiteSpace": "nowrap",
                    })
                for i, q in enumerate(SUGGESTED)
            ], style={"display": "flex", "gap": "8px", "flexWrap": "wrap"}),
        ], style={"padding": "18px 28px 0"}),

        # ── Input bar ─────────────────────────────────────────────────────────
        html.Div([
            dcc.Input(
                id="input-question",
                type="text",
                placeholder="Ask anything about your workforce data...",
                debounce=False,
                n_submit=0,
                style={
                    "flex": "1", "background": C["surface2"],
                    "border": f"1px solid {C['border']}",
                    "borderRadius": "8px", "color": C["text"],
                    "fontSize": "14px", "padding": "12px 16px",
                    "fontFamily": FONT_BODY,
                    "caretColor": C["purple"],
                },
            ),
            html.Button([
                html.Span("Ask"),
                html.Span(" →", style={"fontFamily": FONT_MONO, "marginLeft": "4px"}),
            ], id="btn-ask", n_clicks=0, style={
                "background": C["purple"],
                "border": "none", "borderRadius": "8px",
                "color": "#0E0B1A", "fontWeight": "600",
                "fontSize": "14px", "padding": "12px 24px",
                "cursor": "pointer", "fontFamily": FONT_BODY,
                "whiteSpace": "nowrap",
            }),
        ], style={
            "display": "flex", "gap": "10px",
            "padding": "14px 28px",
        }),

        # ── Results area ──────────────────────────────────────────────────────
        html.Div([

            # Left: SQL + table + token info
            html.Div([
                html.Div(id="output-sql-block", style={"marginBottom": "16px"}),
                html.Div(id="output-token-block", style={"marginBottom": "16px"}),
                html.Div(id="output-table-block"),
                html.Div(id="output-error-block"),
            ], style={
                "flex": "1", "minWidth": "0",
                "padding": "0 14px 0 28px",
            }),

            # Right: chart
            html.Div([
                dcc.Graph(
                    id="output-chart",
                    style={"height": "420px"},
                    config={"displayModeBar": True, "displaylogo": False},
                    figure=go.Figure().update_layout(
                        paper_bgcolor=C["surface"],
                        plot_bgcolor=C["surface"],
                        font=dict(color=C["muted"]),
                        xaxis=dict(showgrid=False, zeroline=False),
                        yaxis=dict(showgrid=False, zeroline=False),
                        annotations=[dict(
                            text="Ask a question to generate a chart",
                            x=0.5, y=0.5, xref="paper", yref="paper",
                            showarrow=False,
                            font=dict(color=C["muted"], size=13),
                        )],
                    ),
                ),
            ], style={
                "flex": "1.2", "minWidth": "0",
                "padding": "0 28px 0 14px",
            }),

        ], style={
            "display": "flex", "gap": "0",
            "padding": "20px 0",
            "minHeight": "460px",
        }),

        # ── Footer ────────────────────────────────────────────────────────────
        html.Div([
            html.Span("HR Copilot · Built with Vanna AI + Gemini 2.5 Flash + Plotly Dash",
                style={"fontSize": "11px", "color": C["muted"], "fontFamily": FONT_MONO}),
        ], style={
            "padding": "12px 28px",
            "borderTop": f"1px solid {C['border']}",
            "textAlign": "center",
        }),

    ], style={
        "background": C["bg"],
        "minHeight": "100vh",
        "fontFamily": FONT_BODY,
    })

app.layout = build_layout


# ── Callback ──────────────────────────────────────────────────────────────────
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
    trigger = ctx.triggered[0]
    idx = json.loads(trigger["prop_id"].split(".")[0])["index"]
    return SUGGESTED[idx]


@app.callback(
    Output("output-sql-block",   "children"),
    Output("output-token-block", "children"),
    Output("output-chart",       "figure"),
    Output("output-table-block", "children"),
    Output("output-error-block", "children"),
    Input("btn-ask",       "n_clicks"),
    Input("input-question","n_submit"),
    State("input-question","value"),
    prevent_initial_call=True,
)
def run_query(n_clicks, n_submit, question):
    empty_fig = go.Figure().update_layout(
        paper_bgcolor=C["surface"], plot_bgcolor=C["surface"],
        font=dict(color=C["muted"]),
        xaxis=dict(showgrid=False), yaxis=dict(showgrid=False),
    )

    if not question or not question.strip():
        return "", "", empty_fig, "", html.Div(
            "⚠ Please enter a question.",
            style={"color": C["warning"], "fontSize": "13px"}
        )

    # ── Cache lookup ──────────────────────────────────────────────────────────
    cached_sql, cached_json = cache_lookup(question)
    if cached_sql and cached_json:
        df = pd.read_json(cached_json)
        from_cache = True
        sql = cached_sql
        input_tok = output_tok = total_tok = 0
    else:
        from_cache = False
        try:
            sql = clean_sql(vn.generate_sql(question=question, allow_llm_to_see_data=True))
            df  = vn.run_sql(sql=sql)
            input_tok  = vn.last_input_tokens
            output_tok = vn.last_output_tokens
            total_tok  = vn.last_total_tokens
            cache_store(question, sql, df.to_json())
        except Exception as e:
            return "", "", empty_fig, "", html.Div([
                html.Span("✕  ", style={"color": C["danger"]}),
                html.Span(str(e), style={"fontFamily": FONT_MONO, "fontSize": "12px"}),
            ], style={"color": C["danger"], "padding": "12px 0"})

    # ── SQL block ─────────────────────────────────────────────────────────────
    cache_badge = html.Span(" · from cache",
        style={"color": C["teal"], "fontSize": "11px", "marginLeft": "8px"}
    ) if from_cache else None

    sql_block = html.Div([
        html.Div([
            html.Span("SQL generated", style={
                "fontSize": "11px", "color": C["muted"],
                "textTransform": "uppercase", "letterSpacing": "0.06em",
                "fontWeight": "500",
            }),
            cache_badge,
        ], style={"marginBottom": "8px", "display": "flex", "alignItems": "center"}),
        html.Pre(sql.strip(), style={
            "background": C["surface2"],
            "border": f"1px solid {C['border']}",
            "borderLeft": f"3px solid {C['purple']}",
            "borderRadius": "6px",
            "padding": "12px 14px",
            "fontSize": "12px",
            "color": C["teal"],
            "fontFamily": FONT_MONO,
            "overflowX": "auto",
            "whiteSpace": "pre-wrap",
            "margin": "0",
        }),
    ])

    # ── Token block ───────────────────────────────────────────────────────────
    if from_cache:
        token_block = html.Div([
            html.Span("⚡ Served from cache · ", style={"color": C["teal"], "fontSize": "12px"}),
            html.Span("0 tokens · $0.0000", style={
                "color": C["muted"], "fontSize": "12px", "fontFamily": FONT_MONO,
            }),
        ], style={"marginTop": "8px"})
    else:
        cost = (input_tok * COST_INPUT_PER_1M + output_tok * COST_OUTPUT_PER_1M) / 1_000_000
        token_block = html.Div([
            html.Span("◈ ", style={"color": C["purple"]}),
            html.Span(f"{total_tok:,} tokens  ·  ", style={
                "color": C["muted"], "fontSize": "12px", "fontFamily": FONT_MONO,
            }),
            html.Span(f"in {input_tok:,}  out {output_tok:,}", style={
                "color": C["muted"], "fontSize": "11px", "fontFamily": FONT_MONO,
            }),
            html.Span(f"  ·  ${cost:.5f}", style={
                "color": C["warning"], "fontSize": "12px",
                "fontFamily": FONT_MONO, "marginLeft": "8px",
            }),
        ], style={"marginTop": "8px"})

    # ── Chart ─────────────────────────────────────────────────────────────────
    try:
        colorway = [C["purple"], C["teal"], C["warning"], C["danger"],
                    C["success"], "#818CF8", "#F472B6"]
        fig = smart_chart(df, question, colorway)
        fig.update_layout(
            paper_bgcolor=C["surface"],
            plot_bgcolor=C["surface2"],
            font=dict(color=C["text"], family=FONT_BODY, size=12),
            title=dict(font=dict(color=C["text"], size=14, family="'Space Grotesk', sans-serif")),
            xaxis=dict(gridcolor=C["border"], zerolinecolor=C["border"]),
            yaxis=dict(gridcolor=C["border"], zerolinecolor=C["border"]),
            legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=C["muted"])),
            margin=dict(l=40, r=20, t=50, b=40),
        )
    except Exception as chart_err:
        print(f"Chart error: {chart_err}")
        fig = empty_fig

    # ── Table ─────────────────────────────────────────────────────────────────
    if len(df) == 0:
        table = html.Div("No results returned.",
            style={"color": C["muted"], "fontSize": "13px", "marginTop": "12px"})
    else:
        rows = min(15, len(df))
        table = html.Div([
            html.Div([
                html.Span(f"Results · {len(df)} rows", style={
                    "fontSize": "11px", "color": C["muted"],
                    "textTransform": "uppercase", "letterSpacing": "0.06em",
                    "fontWeight": "500",
                }),
            ], style={"marginBottom": "8px", "marginTop": "14px"}),
            html.Div([
                html.Table([
                    html.Thead(html.Tr([
                        html.Th(c, style={
                            "padding": "8px 12px", "textAlign": "left",
                            "color": C["purple"], "fontSize": "11px",
                            "fontWeight": "600", "letterSpacing": "0.04em",
                            "borderBottom": f"1px solid {C['border']}",
                            "whiteSpace": "nowrap",
                        }) for c in df.columns
                    ])),
                    html.Tbody([
                        html.Tr([
                            html.Td(str(df.iloc[i][c]), style={
                                "padding": "7px 12px", "fontSize": "12px",
                                "color": C["text"], "fontFamily": FONT_MONO,
                                "borderBottom": f"1px solid {C['border']}22",
                                "whiteSpace": "nowrap",
                            }) for c in df.columns
                        ]) for i in range(rows)
                    ]),
                ], style={"borderCollapse": "collapse", "width": "100%"}),
            ], style={"overflowX": "auto"}),
        ])

    return sql_block, token_block, fig, table, ""


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"  Dashboard starting at http://127.0.0.1:8050")
    app.run(debug=False, port=8050)
