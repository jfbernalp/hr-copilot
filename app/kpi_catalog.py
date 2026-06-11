"""
kpi_catalog.py
--------------
Motor del dashboard estático de KPIs (utilidad 2).

Carga el catálogo de 44 KPIs (data/kpi_catalog.csv) y registra, por índice de
catálogo, una función de cálculo que produce valor + semáforo + figura Plotly
usando el tipo de gráfico que recomienda el propio catálogo. Los datos vienen
de las 4 tablas núcleo IBM + las 14 tablas sintéticas (build_synthetic_data.py).

RLS: build_all() recibe la config del rol (dept_filter, can_see_salary).
El filtro de departamento se aplica al contexto de datos; los KPIs salariales
se marcan locked=True para roles sin permiso y el dashboard los renderiza
bloqueados sin calcular nada.
"""

import os
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── Paleta Práxedes (Manual Web — sin verde, sin morado) ───────────────────────
ORANGE, DARK, LIGHT, WHITE = "#ff8b00", "#383838", "#dddddd", "#ffffff"
RED, AMBER, BLUE, GRAY_MID = "#c0392b", "#e67e22", "#5b8db8", "#666666"
FONT     = "'Montserrat', sans-serif"
HEATSCALE = [[0.0, "#f5f5f5"], [0.55, ORANGE], [1.0, RED]]
LIKERT    = {1: RED, 2: AMBER, 3: LIGHT, 4: BLUE, 5: DARK}

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG_CSV = os.path.join(BASE_DIR, "data", "kpi_catalog.csv")

CATEGORY_ORDER = [
    ("Estructura y Demografía",            "🏢", "estructura"),
    ("Gestión de la Rotación y Retención", "🔄", "rotacion"),
    ("Desarrollo y Talento",               "🎓", "desarrollo"),
    ("Clima Laboral y Bienestar",          "💬", "clima"),
    ("Eficiencia Operativa de RR.HH.",     "⚙️", "eficiencia"),
    ("Nómina y Compensación",              "💰", "nomina"),
    ("Horarios y Control de Asistencia",   "🕒", "horarios"),
    ("Plazas y Gestión de Vacantes",       "📋", "plazas"),
]
SLUG_TO_CAT = {slug: cat for cat, _, slug in CATEGORY_ORDER}

# Hoja "Resumen": vista ejecutiva con los KPIs más consultados, en este orden
SUMMARY_KPIS = [25, 39, 15, 16, 5, 43, 20, 53]

# KPIs que exponen cifras salariales → bloqueados si can_see_salary=False
SALARY_KPIS = {17, 27, 35, 51, 53, 54, 55, 57, 58, 60, 70, 73}

_CATALOG = None


def load_catalog() -> pd.DataFrame:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = pd.read_csv(CATALOG_CSV, sep=";")
    return _CATALOG


# ── Registro de KPIs ────────────────────────────────────────────────────────────
REGISTRY = {}

def kpi(indice, wide=False):
    def deco(fn):
        REGISTRY[indice] = {"fn": fn, "wide": wide}
        return fn
    return deco


# ── Contexto de datos (RLS de departamento + segmentadores de la hoja) ─────────
LEAVE_FILTER = {"EPS": "EPS", "AT": "Accidente", "EL": "Enfermedad Laboral"}

def _norm_filters(filters) -> dict:
    f = dict(filters or {})
    return {k: (None if f.get(k) in (None, "all", "") else f.get(k))
            for k in ("dept", "gender", "level", "cargo", "period", "leave", "progcat", "cycle")}


def build_context(conn, role_cfg: dict, filters=None) -> dict:
    f = _norm_filters(filters)
    dept = role_cfg.get("dept_filter")
    if dept is None and f["dept"] is not None:   # el RLS manda sobre el segmentador
        dept = int(f["dept"])
    where = f"WHERE e.department_id = {int(dept)}" if dept is not None else ""
    emp = pd.read_sql_query(f"""
        SELECT e.*, d.department_name, jr.role_name,
               s.JobSatisfaction, s.EnvironmentSatisfaction, s.RelationshipSatisfaction,
               s.WorkLifeBalance, s.JobInvolvement, s.PerformanceRating
        FROM employees e
        LEFT JOIN departments  d  ON e.department_id = d.department_id
        LEFT JOIN job_roles    jr ON e.role_id = jr.role_id
        LEFT JOIN satisfaction s  ON e.employee_id = s.employee_id
        {where}
    """, conn)
    if f["gender"]:
        emp = emp[emp["Gender"] == f["gender"]]
    if f["level"]:
        emp = emp[emp["JobLevel"] == int(f["level"])]
    if f["cargo"]:
        emp = emp[emp["role_id"] == int(f["cargo"])]
    ids = set(emp["employee_id"])
    dept_of = emp.set_index("employee_id")["department_name"]

    def t(name):
        return pd.read_sql_query(f"SELECT * FROM {name}", conn)

    def by_emp(df):
        df = df[df["employee_id"].isin(ids)].copy()
        df["dept"] = df["employee_id"].map(dept_of)
        return df

    dates  = by_emp(t("employment_dates"))
    att    = by_emp(t("attendance_monthly"))
    pay    = by_emp(t("payroll_monthly"))
    leaves = by_emp(t("medical_leaves"))
    resp   = by_emp(t("survey_responses"))
    parts  = by_emp(t("training_participants"))
    vacat  = by_emp(t("vacation_balances"))

    # Ventana temporal del segmentador "período"
    months_all = sorted(att["month"].unique()) or ["2026-05"]
    months = months_all[-int(f["period"]):] if f["period"] else months_all
    att = att[att["month"].isin(months)]
    pay = pay[pay["month"].isin(months)]
    leaves = leaves[leaves["start_date"].str[:7].isin(months)]
    if f["leave"]:
        leaves = leaves[leaves["leave_type"].str.contains(LEAVE_FILTER[f["leave"]])]

    # Headcount histórico derivado de employment_dates → respeta TODOS los filtros
    hire, exit_ = pd.to_datetime(dates["hire_date"]), pd.to_datetime(dates["exit_date"])
    hm = hire.dt.to_period("M").astype(str)
    em = exit_.dt.to_period("M").astype(str)
    hist_rows = []
    for m in months:
        end = pd.Timestamp(m + "-01") + pd.offsets.MonthEnd(0)
        out = dates[em == m]
        hist_rows.append({
            "month": m,
            "headcount": int(((hire <= end) & (exit_.isna() | (exit_ > end))).sum()),
            "hires": int((hm == m).sum()),
            "exits_voluntary":   int((out["exit_type"] == "voluntary").sum()),
            "exits_involuntary": int((out["exit_type"] == "involuntary").sum()),
        })
    hist = pd.DataFrame(hist_rows)

    vac = t("vacancies")
    if dept is not None:
        vac = vac[vac["department_id"] == int(dept)]
    if f["level"]:
        vac = vac[vac["job_level"] == int(f["level"])]
    if f["cargo"]:
        vac = vac[vac["role_id"] == int(f["cargo"])]
    if f["period"]:
        vac = vac[vac["opened_date"] >= months[0] + "-01"]
    dept_names = dict(pd.read_sql_query("SELECT * FROM departments", conn).values)
    vac["dept"] = vac["department_id"].map(dept_names)

    # Participación de encuestas: invitados recalculados bajo los filtros activos
    cycles = t("survey_cycles")
    cycles["invited"] = [
        int(((hire <= d) & (exit_.isna() | (exit_ >= d))).sum())
        for d in pd.to_datetime(cycles["survey_date"])
    ]
    sel_cycle = f["cycle"] or (resp["cycle"].max() if len(resp) else None)

    progs = t("training_programs")
    if f["progcat"]:
        progs = progs[progs["category"] == f["progcat"]]
        parts = parts[parts["program_id"].isin(progs["program_id"])]

    runs = t("payroll_runs")
    fin  = t("company_financials")
    pay_company = pd.read_sql_query(
        "SELECT month, SUM(total_cost) AS total_cost, SUM(overtime_pay) AS overtime_pay, "
        "SUM(base_salary) AS base_salary FROM payroll_monthly GROUP BY month", conn)
    runs, fin = runs[runs["month"].isin(months)], fin[fin["month"].isin(months)]
    pay_company = pay_company[pay_company["month"].isin(months)]

    return {
        "emp": emp, "dates": dates, "att": att, "pay": pay, "leaves": leaves,
        "hist": hist, "vac": vac, "cycles": cycles, "resp": resp, "sel_cycle": sel_cycle,
        "progs": progs, "parts": parts, "vacat": vacat,
        "runs": runs, "bands": t("salary_bands"), "fin": fin, "pay_company": pay_company,
        "months": months, "last_month": months[-1],
    }


# ── Helpers ─────────────────────────────────────────────────────────────────────
def _theme(fig, height=270, legend=False):
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=DARK, family=FONT, size=10),
        margin=dict(l=10, r=10, t=15, b=10), height=height, showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, bgcolor="rgba(0,0,0,0)", font=dict(size=9)),
    )
    fig.update_xaxes(showgrid=False, zerolinecolor=LIGHT)
    fig.update_yaxes(gridcolor="#eeeeee", zerolinecolor=LIGHT)
    return fig


def _res(value, unit="", sublabel="", status=None, fig=None):
    return {"value": value, "unit": unit, "sublabel": sublabel, "status": status, "fig": fig}


def _empty(sublabel="Sin datos para los filtros seleccionados"):
    return _res("—", sublabel=sublabel)


def _short(dept):
    return {"Research & Development": "R&D", "Human Resources": "HR"}.get(dept, dept)


def _quarter(month_str):
    return f"{month_str[:4]}-Q{(int(month_str[5:7]) - 1) // 3 + 1}"


def _money(x):
    return f"${x:,.0f}"


def _minmax(s):
    s = s.astype(float)
    rng = s.max() - s.min()
    return (s - s.min()) / rng if rng > 0 else s * 0


# ════════════════════════════════════════════════════════════════════════════════
# 1. ESTRUCTURA Y DEMOGRAFÍA
# ════════════════════════════════════════════════════════════════════════════════

@kpi(25, wide=True)   # Headcount Total — línea neta + barras ingresos/egresos
def k_headcount(ctx):
    h = ctx["hist"].groupby("month", as_index=False).agg(
        headcount=("headcount", "sum"), hires=("hires", "sum"),
        ev=("exits_voluntary", "sum"), ei=("exits_involuntary", "sum"))
    h["exits"] = h["ev"] + h["ei"]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=h["month"], y=h["hires"], name="Ingresos", marker_color=ORANGE)
    fig.add_bar(x=h["month"], y=-h["exits"], name="Egresos", marker_color=RED)
    fig.add_scatter(x=h["month"], y=h["headcount"], name="Headcount", mode="lines+markers",
                    line=dict(color=DARK, width=2.5), secondary_y=True)
    fig.update_layout(barmode="relative")
    last = h["headcount"].iloc[-1]
    delta = f"Variación último mes: {last - h['headcount'].iloc[-2]:+d}" if len(h) > 1 else ""
    return _res(f"{last:,}", "empleados", delta, fig=_theme(fig, height=300, legend=True))


@kpi(26)   # Distribución por Rango de Antigüedad
def k_tenure(ctx):
    act = ctx["emp"][ctx["emp"]["Attrition"] == "No"]
    bins, labels = [-1, 1, 3, 5, 10, 100], ["0–1", "1–3", "3–5", "5–10", "10+"]
    d = pd.cut(act["YearsAtCompany"], bins=bins, labels=labels).value_counts().reindex(labels)
    fig = go.Figure(go.Bar(x=labels, y=d.values, marker_color=[ORANGE, DARK, BLUE, AMBER, LIGHT]))
    fig.update_xaxes(title_text="Años en la compañía", title_font_size=9)
    return _res(f"{act['YearsAtCompany'].median():.0f}", "años (mediana)",
                f"{100 * (act['YearsAtCompany'] <= 2).mean():.0f}% con ≤2 años (zona de mayor riesgo de fuga)",
                fig=_theme(fig))


@kpi(33)   # Proyección de Headcount — tendencia + proyección punteada
def k_forecast(ctx):
    h = ctx["hist"].groupby("month")["headcount"].sum()
    y = h.values.astype(float)
    if len(y) < 8:
        return _empty("Se requieren al menos 8 meses de histórico para proyectar")
    x = np.arange(len(y))
    w = min(18, len(y))
    coef = np.polyfit(x[-w:], y[-w:], 1)
    fx = np.arange(len(y) - 1, len(y) + 6)
    fy = np.polyval(coef, fx)
    fut = [f"{p}" for p in pd.period_range(h.index[-1], periods=7, freq="M")]
    fig = go.Figure()
    fig.add_scatter(x=list(h.index), y=y, mode="lines", name="Histórico", line=dict(color=DARK, width=2.5))
    fig.add_scatter(x=fut, y=fy, mode="lines+markers", name="Proyección",
                    line=dict(color=ORANGE, width=2.5, dash="dash"))
    return _res(f"{fy[-1]:,.0f}", "empleados", "Proyección a 6 meses (tendencia lineal 18m)",
                fig=_theme(fig, legend=True))


@kpi(27)   # Gender Pay Ratio (salarial)
def k_gender_pay(ctx):
    e = ctx["emp"]
    by = e.groupby(["JobLevel", "Gender"])["MonthlyIncome"].median().unstack()
    if "Female" not in by or "Male" not in by:
        return _res("N/A", sublabel="Sin ambos géneros en el alcance del rol")
    ratio = (by["Female"] / by["Male"]).round(2)
    fig = go.Figure(go.Bar(x=[f"Nivel {i}" for i in ratio.index], y=ratio.values, marker_color=ORANGE))
    fig.add_hline(y=1.0, line_color=DARK, line_dash="dash",
                  annotation_text="paridad", annotation_font_size=9)
    overall = e.groupby("Gender")["MonthlyIncome"].median()
    val = overall["Female"] / overall["Male"]
    return _res(f"{val:.2f}", "ratio F/M", "Mediana salarial mujeres / hombres (1.0 = paridad)",
                status="ok" if 0.95 <= val <= 1.05 else "warn", fig=_theme(fig))


@kpi(28)   # Distribución Demográfica y Diversidad
def k_diversity(ctx):
    e = ctx["emp"][ctx["emp"]["Attrition"] == "No"]
    d = e.groupby(["department_name", "Gender"]).size().unstack(fill_value=0)
    fig = go.Figure()
    for g, color in [("Female", ORANGE), ("Male", BLUE)]:
        if g in d:
            fig.add_bar(y=[_short(i) for i in d.index], x=d[g], name=g, orientation="h", marker_color=color)
    fig.update_layout(barmode="stack")
    pf = 100 * (e["Gender"] == "Female").mean()
    return _res(f"{pf:.0f}%", "mujeres", f"Edad promedio {e['Age'].mean():.0f} años · {len(e):,} activos",
                fig=_theme(fig, legend=True))


@kpi(67)   # Vacation Liability — días de vacaciones pendientes
def k_vacation(ctx):
    v = ctx["vacat"].copy()
    v["dept"] = v["employee_id"].map(ctx["emp"].set_index("employee_id")["department_name"])
    by = v.groupby("dept")["pending_days"].mean().sort_values()
    fig = go.Figure(go.Bar(y=[_short(i) for i in by.index], x=by.round(1), orientation="h", marker_color=ORANGE))
    fig.update_xaxes(title_text="días pendientes promedio", title_font_size=9)
    total = int(v["pending_days"].sum())
    crit = int((v["pending_days"] > 30).sum())
    return _res(f"{total:,}", "días acumulados", f"{crit} empleados con >30 días sin disfrutar",
                status="warn" if crit > 20 else "ok", fig=_theme(fig, height=220))


# ════════════════════════════════════════════════════════════════════════════════
# 2. GESTIÓN DE LA ROTACIÓN Y RETENCIÓN
# ════════════════════════════════════════════════════════════════════════════════

@kpi(34, wide=True)   # Flight Risk Index — top 15 priorizado
def k_flight_risk(ctx):
    act = ctx["dates"][ctx["dates"]["exit_date"].isna()][["employee_id", "dept"]]
    e = ctx["emp"].set_index("employee_id")
    recent = ctx["att"][ctx["att"]["month"] >= ctx["months"][-min(6, len(ctx["months"]))]]
    g = recent.groupby("employee_id").agg(absd=("absence_days", "mean"), ot=("overtime_hours", "mean"))
    df = act.join(g, on="employee_id").dropna()
    df["tenure"] = df["employee_id"].map(e["YearsAtCompany"])
    df["perf"]   = df["employee_id"].map(e["PerformanceRating"]).fillna(3)
    df["score"] = (0.30 * _minmax(df["absd"]) + 0.20 * _minmax(df["ot"])
                   + 0.25 * (1 - _minmax(df["tenure"])) + 0.25 * (1 - _minmax(df["perf"]))) * 100
    df = df.sort_values("score", ascending=False)
    top = df.head(15).iloc[::-1]
    colors = [RED if s >= 70 else (AMBER if s >= 55 else DARK) for s in top["score"]]
    fig = go.Figure(go.Bar(
        y=[f"Emp #{i} · {_short(d)}" for i, d in zip(top["employee_id"], top["dept"])],
        x=top["score"].round(1), orientation="h", marker_color=colors,
        text=top["score"].round(0), textposition="outside"))
    fig.add_vline(x=70, line_color=RED, line_dash="dash", annotation_text="riesgo alto", annotation_font_size=9)
    fig.update_xaxes(range=[0, 105])
    n_high = int((df["score"] >= 70).sum())
    return _res(f"{n_high}", "en riesgo alto", "Score ≥70 — pesos: ausentismo 30% · OT 20% · antigüedad 25% · desempeño 25%",
                status="bad" if n_high > 25 else ("warn" if n_high > 0 else "ok"),
                fig=_theme(fig, height=340))


@kpi(35)   # Costo Estimado de Rotación (salarial)
def k_turnover_cost(ctx):
    leavers = ctx["dates"][ctx["dates"]["exit_date"].notna()].copy()
    e = ctx["emp"].set_index("employee_id")
    leavers["income"] = leavers["employee_id"].map(e["MonthlyIncome"])
    leavers["level"]  = leavers["employee_id"].map(e["JobLevel"])
    factor = {1: 0.6, 2: 0.6, 3: 1.0, 4: 1.5, 5: 2.0}
    leavers["cost"] = leavers["income"] * 12 * leavers["level"].map(factor)
    by = leavers.groupby("dept").agg(cost=("cost", "sum"), n=("employee_id", "count")).sort_values("cost")
    fig = go.Figure(go.Bar(y=[_short(i) for i in by.index], x=by["cost"], orientation="h",
                           marker_color=RED, text=[f"{n} bajas" for n in by["n"]], textposition="inside"))
    fig.update_xaxes(title_text="USD acumulado (24 meses)", title_font_size=9)
    return _res(_money(by["cost"].sum() / 1e6) + "M", "USD / 24 meses",
                f"{int(by['n'].sum())} bajas × (reclutamiento + onboarding + productividad perdida)",
                fig=_theme(fig, height=220))


@kpi(37)   # Tasa de Ingresos (Hiring Rate)
def k_hiring(ctx):
    h = ctx["hist"].groupby("month").agg(hires=("hires", "sum"), hc=("headcount", "sum"))
    rate = 100 * h["hires"] / h["hc"]
    fig = go.Figure(go.Scatter(x=list(h.index), y=rate.round(2), mode="lines", fill="tozeroy",
                               line=dict(color=ORANGE, width=2.5)))
    fig.update_yaxes(title_text="% mensual", title_font_size=9)
    return _res(f"{int(h['hires'].tail(12).sum())}", "ingresos (12m)",
                f"Tasa promedio mensual: {rate.tail(12).mean():.1f}% del headcount", fig=_theme(fig))


@kpi(39)   # Tasa de Rotación General
def k_turnover(ctx):
    h = ctx["hist"].groupby("month").agg(ex=("exits_voluntary", "sum"), ei=("exits_involuntary", "sum"),
                                         hc=("headcount", "sum"))
    h["exits"] = h["ex"] + h["ei"]
    w = min(12, len(h))
    rolling = 100 * h["exits"].rolling(w).sum() * (12 / w) / h["hc"].rolling(w).mean()
    fig = go.Figure()
    fig.add_scatter(x=list(h.index), y=rolling.round(2), mode="lines", name="Anualizada",
                    line=dict(color=DARK, width=2.5))
    fig.add_bar(x=list(h.index), y=(100 * h["exits"] / h["hc"]).round(2), name="Mensual", marker_color=LIGHT)
    if rolling.dropna().empty:
        return _empty()
    val = rolling.dropna().iloc[-1]
    total_exits = h["exits"].sum()
    sub = (f"{100 * h['ex'].sum() / total_exits:.0f}% de las salidas son voluntarias"
           if total_exits else "Sin salidas en el período seleccionado")
    return _res(f"{val:.1f}%", "anualizada", sub,
                status="warn" if val > 12 else "ok", fig=_theme(fig, legend=True))


@kpi(43)   # Burnout Risk Score
def k_burnout(ctx):
    e = ctx["emp"][ctx["emp"]["Attrition"] == "No"]
    risk = (e["OverTime"] == "Yes") & (e["WorkLifeBalance"] <= 2) & (e["JobSatisfaction"] <= 2)
    by = (100 * risk.groupby(e["department_name"]).mean()).sort_values()
    fig = go.Figure(go.Bar(y=[_short(i) for i in by.index], x=by.round(1), orientation="h",
                           marker_color=[RED if v > 5 else ORANGE for v in by]))
    fig.update_xaxes(title_text="% plantilla en riesgo", title_font_size=9)
    val = 100 * risk.mean()
    return _res(f"{val:.1f}%", "en riesgo", "Horas extra + bajo balance vida-trabajo + baja satisfacción",
                status="bad" if val > 5 else ("warn" if val > 3 else "ok"), fig=_theme(fig, height=220))


# ════════════════════════════════════════════════════════════════════════════════
# 3. DESARROLLO Y TALENTO
# ════════════════════════════════════════════════════════════════════════════════

@kpi(66, wide=True)   # Training Effectiveness — barras horizontales con línea en 0
def k_training(ctx):
    m = ctx["parts"].merge(ctx["progs"], on="program_id")
    if m.empty:
        return _empty()
    by = m.groupby("program_name").agg(pre=("perf_score_pre", "mean"), post=("perf_score_post", "mean"),
                                       n=("employee_id", "count"))
    by["var"] = 100 * (by["post"] - by["pre"]) / by["pre"]
    by = by.sort_values("var")
    colors = [ORANGE if v > 5 else (LIGHT if v > 0 else RED) for v in by["var"]]
    fig = go.Figure(go.Bar(y=by.index, x=by["var"].round(1), orientation="h", marker_color=colors,
                           text=[f"{v:+.1f}%  (n={n})" for v, n in zip(by["var"], by["n"])],
                           textposition="outside"))
    fig.add_vline(x=0, line_color=DARK)
    fig.add_vline(x=5, line_color=GRAY_MID, line_dash="dot", annotation_text="umbral impacto", annotation_font_size=9)
    fig.update_xaxes(title_text="Δ% desempeño pre → post capacitación", title_font_size=9)
    eff = int((by["var"] > 5).sum())
    return _res(f"{eff}/{len(by)}", "programas efectivos", "Variación >5% = impacto demostrable; ≤0% = rediseñar",
                status="ok" if eff >= len(by) * 0.6 else "warn", fig=_theme(fig, height=320))


@kpi(7)   # Performance Score — distribución de calificaciones
def k_performance(ctx):
    e = ctx["emp"]
    d = e.groupby(["department_name", "PerformanceRating"]).size().unstack(fill_value=0)
    fig = go.Figure()
    for rating, color in [(3, LIGHT), (4, ORANGE)]:
        if rating in d:
            fig.add_bar(x=[_short(i) for i in d.index], y=d[rating], name=f"Nota {rating}", marker_color=color)
    fig.update_layout(barmode="group")
    p4 = 100 * (e["PerformanceRating"] == 4).mean()
    return _res(f"{e['PerformanceRating'].mean():.2f}", "/ 4",
                f"Solo {p4:.0f}% con nota 4 — curva concentrada: revisar calibración de evaluadores",
                status="warn", fig=_theme(fig, legend=True))


@kpi(11)   # Tasa de Promoción Interna — dona
def k_promotion(ctx):
    closed = ctx["vac"][ctx["vac"]["closed_date"].notna()]
    if closed.empty:
        return _empty()
    counts = closed["filled_by"].value_counts()
    fig = go.Figure(go.Pie(labels=["Interna", "Externa"],
                           values=[counts.get("internal", 0), counts.get("external", 0)],
                           hole=0.6, marker=dict(colors=[ORANGE, LIGHT]), textinfo="percent"))
    val = 100 * counts.get("internal", 0) / max(len(closed), 1)
    return _res(f"{val:.0f}%", "interna", f"{counts.get('internal', 0)} de {len(closed)} vacantes cubiertas con talento propio",
                status="ok" if val >= 25 else "warn", fig=_theme(fig, legend=True))


# ════════════════════════════════════════════════════════════════════════════════
# 4. CLIMA LABORAL Y BIENESTAR
# ════════════════════════════════════════════════════════════════════════════════

@kpi(1, wide=True)   # Engagement — barras apiladas 100% por pregunta (Likert)
def k_engagement(ctx):
    r = ctx["resp"][ctx["resp"]["cycle"] == ctx["sel_cycle"]]
    if r.empty:
        return _empty()
    qs = [("q_pride", "Orgullo de pertenencia"), ("q_effort", "Esfuerzo discrecional"),
          ("q_stay", "Intención de permanencia")]
    fig = go.Figure()
    for level in [1, 2, 3, 4, 5]:
        pcts = [100 * (r[q] == level).mean() for q, _ in qs]
        fig.add_bar(y=[lbl for _, lbl in qs], x=pcts, name=f"{level}", orientation="h",
                    marker_color=LIKERT[level])
    fig.update_layout(barmode="stack")
    fig.update_xaxes(title_text="% de respuestas (1=muy en desacuerdo · 5=muy de acuerdo)", title_font_size=9)
    score = r[[q for q, _ in qs]].mean().mean()
    return _res(f"{score:.2f}", "/ 5", f"Ciclo {r['cycle'].iloc[0]} · {len(r):,} respuestas",
                status="ok" if score >= 3.4 else "warn", fig=_theme(fig, height=240, legend=True))


@kpi(2, wide=True)   # Workplace Incident Rate — heatmap área × mes
def k_incidents(ctx):
    acc = ctx["leaves"][ctx["leaves"]["leave_type"].str.contains("Accidente")].copy()
    acc["month"] = acc["start_date"].str[:7]
    hours = ctx["att"].groupby(["dept", "month"]).apply(
        lambda g: g["regular_hours"].sum() + g["overtime_hours"].sum(), include_groups=False)
    n_acc = acc.groupby(["dept", "month"]).size()
    rate = (n_acc.reindex(hours.index, fill_value=0) / hours * 200_000).unstack(fill_value=0)
    rate = rate.reindex(columns=ctx["months"], fill_value=0)
    fig = go.Figure(go.Heatmap(z=rate.values, x=rate.columns, y=[_short(i) for i in rate.index],
                               colorscale=HEATSCALE, colorbar=dict(thickness=8, tickfont=dict(size=8))))
    tot_h = ctx["att"]["regular_hours"].sum() + ctx["att"]["overtime_hours"].sum()
    val = len(acc) / tot_h * 200_000
    return _res(f"{val:.2f}", "por 200k horas", f"Estándar OSHA · {len(acc)} accidentes ARL en 24 meses",
                status="warn" if val > 3.9 else "ok", fig=_theme(fig, height=240))


@kpi(3)   # Wellbeing Index
def k_wellbeing(ctx):
    e = ctx["emp"][ctx["emp"]["Attrition"] == "No"]
    score = e[["WorkLifeBalance", "EnvironmentSatisfaction", "RelationshipSatisfaction"]].mean(axis=1)
    by = (100 * (score.groupby(e["department_name"]).mean() - 1) / 3).sort_values()
    fig = go.Figure(go.Bar(y=[_short(i) for i in by.index], x=by.round(0), orientation="h", marker_color=BLUE))
    fig.update_xaxes(title_text="índice 0–100", title_font_size=9)
    val = 100 * (score.mean() - 1) / 3
    return _res(f"{val:.0f}", "/ 100", "Balance vida-trabajo + entorno + relaciones",
                status="ok" if val >= 55 else "warn", fig=_theme(fig, height=220))


@kpi(4)   # Participación en Encuestas — tarjeta + línea por ciclo
def k_participation(ctx):
    if ctx["resp"].empty:
        return _empty()
    p = ctx["resp"].groupby("cycle").size().to_frame("n").join(ctx["cycles"].set_index("cycle"))
    p["rate"] = 100 * p["n"] / p["invited"]
    fig = go.Figure(go.Scatter(x=list(p.index), y=p["rate"].round(1), mode="lines+markers",
                               line=dict(color=ORANGE, width=2.5)))
    fig.add_hline(y=70, line_color=RED, line_dash="dash", annotation_text="mínimo representativo", annotation_font_size=9)
    fig.add_hline(y=80, line_color=GRAY_MID, line_dash="dot", annotation_text="meta", annotation_font_size=9)
    val = p["rate"].iloc[-1]
    return _res(f"{val:.0f}%", "último ciclo", "Bajo 70% la muestra pierde representatividad estadística",
                status="ok" if val >= 70 else "warn", fig=_theme(fig))


@kpi(5)   # eNPS — composición + score
def k_enps(ctx):
    r = ctx["resp"]
    if r.empty or ctx["sel_cycle"] is None:
        return _empty()
    by = r.groupby("cycle")["q_recommend_nps"].agg(
        prom=lambda s: 100 * (s >= 9).mean(), det=lambda s: 100 * (s <= 6).mean())
    by["enps"] = by["prom"] - by["det"]
    last = r[r["cycle"] == ctx["sel_cycle"]]["q_recommend_nps"]
    if last.empty:
        return _empty()
    comp = [100 * (last <= 6).mean(), 100 * ((last >= 7) & (last <= 8)).mean(), 100 * (last >= 9).mean()]
    fig = make_subplots(rows=2, cols=1, row_heights=[0.35, 0.65], vertical_spacing=0.18)
    for v, lbl, color in zip(comp, ["Detractores", "Pasivos", "Promotores"], [RED, LIGHT, ORANGE]):
        fig.add_bar(y=["hoy"], x=[v], name=lbl, orientation="h", marker_color=color, row=1, col=1)
    fig.add_scatter(x=list(by.index), y=by["enps"].round(1), mode="lines+markers", name="eNPS",
                    line=dict(color=DARK, width=2.5), showlegend=False, row=2, col=1)
    fig.update_layout(barmode="stack")
    fig.update_yaxes(visible=False, row=1, col=1)
    val = by.loc[ctx["sel_cycle"], "enps"]
    return _res(f"{val:+.0f}", "eNPS", f"Ciclo {ctx['sel_cycle']} · Promotores {comp[2]:.0f}% − Detractores {comp[0]:.0f}%",
                status="ok" if val >= 0 else "warn", fig=_theme(fig, height=280, legend=True))


# ════════════════════════════════════════════════════════════════════════════════
# 5. EFICIENCIA OPERATIVA DE RR.HH.
# ════════════════════════════════════════════════════════════════════════════════

@kpi(15, wide=True)   # Tasa de Ausentismo — barras días + línea tasa
def k_absenteeism(ctx):
    a = ctx["att"].groupby("month").agg(absd=("absence_days", "sum"), sched=("scheduled_days", "sum"))
    a["rate"] = 100 * a["absd"] / a["sched"]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=list(a.index), y=a["absd"], name="Días perdidos", marker_color=LIGHT)
    fig.add_scatter(x=list(a.index), y=a["rate"].round(2), name="Tasa %", mode="lines",
                    line=dict(color=ORANGE, width=2.5), secondary_y=True)
    val = a["rate"].iloc[-1]
    return _res(f"{val:.1f}%", "último mes", f"{int(a['absd'].tail(12).sum()):,} días perdidos en 12 meses",
                status="bad" if val > 5 else ("warn" if val > 4 else "ok"),
                fig=_theme(fig, height=280, legend=True))


@kpi(16)   # Overtime Rate — tarjeta + tendencia
def k_overtime(ctx):
    a = ctx["att"].groupby("month").agg(ot=("overtime_hours", "sum"), reg=("regular_hours", "sum"))
    a["rate"] = 100 * a["ot"] / a["reg"]
    fig = go.Figure(go.Scatter(x=list(a.index), y=a["rate"].round(2), mode="lines", fill="tozeroy",
                               line=dict(color=ORANGE, width=2.5)))
    fig.add_hline(y=10, line_color=RED, line_dash="dash", annotation_text="zona crítica", annotation_font_size=9)
    val = a["rate"].iloc[-1]
    return _res(f"{val:.1f}%", "OT/regulares", ">10% sostenido = dotación insuficiente para la carga real",
                status="bad" if val > 10 else ("warn" if val > 7 else "ok"), fig=_theme(fig))


@kpi(17)   # Costo Total de Ausentismo (salarial)
def k_abs_cost(ctx):
    pay = ctx["pay"].set_index(["employee_id", "month"])["base_salary"]
    a = ctx["att"].set_index(["employee_id", "month"])
    cost = (a["absence_days"] * (pay / 21.7)).groupby(level="month").sum()
    fig = go.Figure(go.Bar(x=list(cost.index), y=cost.round(0), marker_color=RED))
    fig.update_yaxes(title_text="USD/mes", title_font_size=9)
    return _res(_money(cost.tail(12).sum()), "últimos 12m", "Días de ausencia × costo diario salarial",
                fig=_theme(fig))


@kpi(18)   # Payroll Error Rate
def k_payroll_errors(ctx):
    r = ctx["runs"]
    rate = 100 * r["payslips_with_errors"] / r["payslips_total"]
    fig = go.Figure(go.Scatter(x=r["month"], y=rate.round(2), mode="lines+markers",
                               line=dict(color=DARK, width=2)))
    fig.add_hline(y=1, line_color=RED, line_dash="dash", annotation_text="umbral 1%", annotation_font_size=9)
    val = rate.mean()
    return _res(f"{val:.2f}%", "promedio", f"{int(r['payslips_with_errors'].sum())} desprendibles con error en 24 meses",
                status="ok" if val <= 1 else "warn", fig=_theme(fig))


@kpi(20)   # Time to Fill — barras por depto + benchmark 44 días
def k_time_to_fill(ctx):
    v = ctx["vac"][ctx["vac"]["closed_date"].notna()].copy()
    if v.empty:
        return _empty()
    v["days"] = (pd.to_datetime(v["closed_date"]) - pd.to_datetime(v["opened_date"])).dt.days
    by = v.groupby("dept")["days"].mean().sort_values()
    fig = go.Figure(go.Bar(y=[_short(i) for i in by.index], x=by.round(0), orientation="h",
                           marker_color=[RED if d > 44 else ORANGE for d in by]))
    fig.add_vline(x=44, line_color=DARK, line_dash="dash", annotation_text="benchmark SHRM", annotation_font_size=9)
    val = v["days"].mean()
    return _res(f"{val:.0f}", "días promedio", f"{len(v)} vacantes cerradas en la ventana",
                status="ok" if val <= 44 else "warn", fig=_theme(fig, height=220))


@kpi(19)   # Vacancy Fill Rate
def k_fill_rate(ctx):
    v = ctx["vac"].copy()
    if v.empty:
        return _empty()
    v["q"] = v["opened_date"].str[:7].map(_quarter)
    by = v.groupby("q").agg(total=("vacancy_id", "count"),
                            filled=("closed_date", lambda s: s.notna().sum()))
    by["rate"] = 100 * by["filled"] / by["total"]
    fig = go.Figure(go.Bar(x=list(by.index), y=by["rate"].round(0), marker_color=ORANGE,
                           text=[f"{f}/{t}" for f, t in zip(by["filled"], by["total"])], textposition="inside"))
    fig.update_yaxes(title_text="% cubiertas", title_font_size=9)
    val = 100 * v["closed_date"].notna().mean()
    return _res(f"{val:.0f}%", "cubiertas", "Los trimestres recientes bajan: vacantes aún en proceso",
                fig=_theme(fig))


# ════════════════════════════════════════════════════════════════════════════════
# 6. NÓMINA Y COMPENSACIÓN
# ════════════════════════════════════════════════════════════════════════════════

@kpi(51, wide=True)   # Compa-Ratio — dispersión con banda de equidad
def k_compa(ctx):
    e = ctx["emp"].merge(ctx["bands"], left_on="JobLevel", right_on="job_level")
    e["ratio"] = e["MonthlyIncome"] / e["band_mid"]
    jitter = np.random.default_rng(7).uniform(-0.18, 0.18, len(e))
    colors = np.where(e["ratio"] < 0.85, RED, np.where(e["ratio"] > 1.15, AMBER, DARK))
    fig = go.Figure(go.Scatter(x=e["JobLevel"] + jitter, y=e["ratio"].round(2), mode="markers",
                               marker=dict(color=colors, size=4, opacity=0.55)))
    fig.add_hline(y=0.85, line_color=RED, line_dash="dash")
    fig.add_hline(y=1.15, line_color=AMBER, line_dash="dash",
                  annotation_text="zona de equidad 0.85–1.15", annotation_font_size=9)
    fig.update_xaxes(title_text="Nivel de cargo", title_font_size=9, dtick=1)
    n_low = int((e["ratio"] < 0.85).sum())
    return _res(f"{e['ratio'].mean():.2f}", "promedio",
                f"{n_low} empleados subcompensados (<0.85) con riesgo de fuga",
                status="warn" if n_low > 100 else "ok", fig=_theme(fig, height=300))


@kpi(53)   # Labor Cost per FTE (salarial)
def k_cost_fte(ctx):
    p = ctx["pay"][ctx["pay"]["month"] >= ctx["months"][-min(12, len(ctx["months"]))]]
    if p.empty:
        return _empty()
    by = (p.groupby("dept")["total_cost"].sum() / p.groupby("dept")["employee_id"].count()).sort_values()
    fig = go.Figure(go.Bar(y=[_short(i) for i in by.index], x=by.round(0), orientation="h", marker_color=ORANGE))
    fig.update_xaxes(title_text="USD/FTE/mes (todo incluido)", title_font_size=9)
    val = p["total_cost"].sum() / len(p)
    return _res(_money(val), "/FTE/mes", "Salario + beneficios + cargas (factor 1.4×)", fig=_theme(fig, height=220))


@kpi(54)   # Salario Medio por Área (salarial)
def k_salary_dept(ctx):
    by = ctx["emp"].groupby("department_name")["MonthlyIncome"].median().sort_values()
    fig = go.Figure(go.Bar(y=[_short(i) for i in by.index], x=by.round(0), orientation="h", marker_color=DARK))
    fig.update_xaxes(title_text="mediana USD/mes", title_font_size=9)
    return _res(_money(ctx["emp"]["MonthlyIncome"].median()), "mediana", "Salario base mensual por departamento",
                fig=_theme(fig, height=220))


@kpi(55)   # Benefits-to-Base Ratio (salarial)
def k_benefits(ctx):
    p = ctx["pay"]
    by = (100 * (p.groupby("dept")[["benefits", "employer_contributions", "overtime_pay"]].sum().sum(axis=1)
          / p.groupby("dept")["base_salary"].sum())).sort_values()
    fig = go.Figure(go.Bar(y=[_short(i) for i in by.index], x=by.round(1), orientation="h", marker_color=BLUE))
    fig.update_xaxes(title_text="% sobre salario base", title_font_size=9)
    val = 100 * (p["benefits"].sum() + p["employer_contributions"].sum() + p["overtime_pay"].sum()) / p["base_salary"].sum()
    return _res(f"{val:.0f}%", "sobre base", "Beneficios + cargas + recargos de horas extra", fig=_theme(fig, height=220))


@kpi(57)   # Incremento Salarial Promedio (salarial)
def k_increase(ctx):
    p = ctx["pay"]
    incs = []
    for year, prev in [("2025", "2024-12"), ("2026", "2025-12")]:
        a = p[p["month"] == prev].groupby("dept")["base_salary"].mean()
        b = p[p["month"] == f"{year}-01"].groupby("dept")["base_salary"].mean()
        if len(a) and len(b):
            incs.append((year, 100 * (b / a - 1)))
    if not incs:
        return _empty("El período seleccionado no incluye un ciclo de ajuste salarial (enero)")
    fig = go.Figure()
    for (year, s), color in zip(incs, [LIGHT, ORANGE]):
        fig.add_bar(x=[_short(i) for i in s.index], y=s.round(1), name=f"Ciclo {year}", marker_color=color)
    fig.add_hline(y=5.2, line_color=RED, line_dash="dash", annotation_text="inflación ref.", annotation_font_size=9)
    fig.update_layout(barmode="group")
    val = incs[-1][1].mean()
    return _res(f"{val:.1f}%", "ciclo 2026", "Incremento real positivo: supera la inflación de referencia",
                status="ok" if val > 5.2 else "warn", fig=_theme(fig, legend=True))


@kpi(58)   # Labor Cost Ratio (salarial — toda la compañía)
def k_cost_ratio(ctx):
    p = ctx["pay_company"].set_index("month")["total_cost"]
    f = ctx["fin"].set_index("month")["operating_revenue"]
    ratio = (100 * p / f).dropna()
    fig = go.Figure(go.Scatter(x=list(ratio.index), y=ratio.round(1), mode="lines", fill="tozeroy",
                               line=dict(color=DARK, width=2.5)))
    fig.add_hline(y=35, line_color=RED, line_dash="dash", annotation_text="umbral sostenibilidad", annotation_font_size=9)
    val = ratio.iloc[-1]
    return _res(f"{val:.1f}%", "de los ingresos", "Toda la compañía · rango saludable 20–35%",
                status="ok" if val <= 35 else "bad", fig=_theme(fig))


@kpi(56)   # Payroll On-Time Rate
def k_ontime(ctx):
    r = ctx["runs"].copy()
    r["delay"] = (pd.to_datetime(r["actual_pay_date"]) - pd.to_datetime(r["scheduled_pay_date"])).dt.days
    fig = go.Figure(go.Bar(x=r["month"], y=r["delay"],
                           marker_color=[RED if d > 0 else LIGHT for d in r["delay"]]))
    fig.update_yaxes(title_text="días de atraso", title_font_size=9)
    val = 100 * (r["delay"] == 0).mean()
    return _res(f"{val:.0f}%", "pagos puntuales", f"{int((r['delay'] > 0).sum())} meses con atraso en 24",
                status="ok" if val >= 90 else "warn", fig=_theme(fig))


@kpi(73)   # Revenue per Labor Cost (salarial — toda la compañía)
def k_revenue_ratio(ctx):
    p = ctx["pay_company"].set_index("month")["total_cost"]
    f = ctx["fin"].set_index("month")["operating_revenue"]
    ratio = (f / p).dropna()
    fig = go.Figure(go.Scatter(x=list(ratio.index), y=ratio.round(2), mode="lines",
                               line=dict(color=BLUE, width=2.5)))
    fig.update_yaxes(title_text="$ ingreso por $ de nómina", title_font_size=9)
    return _res(f"{ratio.mean():.1f}x", "promedio", "Toda la compañía · productividad del gasto laboral",
                fig=_theme(fig))


# ════════════════════════════════════════════════════════════════════════════════
# 7. HORARIOS Y CONTROL DE ASISTENCIA
# ════════════════════════════════════════════════════════════════════════════════

@kpi(70, wide=True)   # Índice de Horas Extras — barras costo + línea % nómina (salarial)
def k_ot_index(ctx):
    p = ctx["pay"].groupby("month").agg(ot=("overtime_pay", "sum"), total=("total_cost", "sum"))
    p["idx"] = 100 * p["ot"] / p["total"]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=list(p.index), y=p["ot"].round(0), name="Costo OT (USD)", marker_color=ORANGE)
    fig.add_scatter(x=list(p.index), y=p["idx"].round(2), name="% de la nómina", mode="lines",
                    line=dict(color=DARK, width=2.5), secondary_y=True)
    fig.add_hline(y=5, line_color=RED, line_dash="dash", secondary_y=True)
    val = p["idx"].iloc[-1]
    return _res(f"{val:.1f}%", "de la nómina", ">5% estructural = turnos subdimensionados",
                status="warn" if val > 5 else "ok", fig=_theme(fig, height=280, legend=True))


@kpi(71, wide=True)   # Frecuencia de Incapacidades — heatmap + desglose
def k_disabilities(ctx):
    lv = ctx["leaves"].copy()
    lv["month"] = lv["start_date"].str[:7]
    n = lv.groupby(["dept", "month"]).size()
    active = ctx["att"].groupby(["dept", "month"])["employee_id"].count()
    freq = (100 * n.reindex(active.index, fill_value=0) / active).unstack(fill_value=0)
    freq = freq.reindex(columns=ctx["months"], fill_value=0)
    fig = go.Figure(go.Heatmap(z=freq.values, x=freq.columns, y=[_short(i) for i in freq.index],
                               colorscale=HEATSCALE, colorbar=dict(thickness=8, tickfont=dict(size=8))))
    per_q = len(lv) / len(ctx["att"]) * 3
    mix = lv["leave_type"].value_counts(normalize=True) * 100
    return _res(f"{per_q:.2f}", "por empleado/trimestre",
                " · ".join(f"{t.split(' (')[0]}: {v:.0f}%" for t, v in mix.items()),
                status="warn" if per_q > 0.3 else "ok", fig=_theme(fig, height=240))


@kpi(45)   # OT Hours per FTE
def k_ot_fte(ctx):
    a = ctx["att"]
    by = a.groupby("dept")["overtime_hours"].mean().sort_values()
    fig = go.Figure(go.Bar(y=[_short(i) for i in by.index], x=by.round(1), orientation="h", marker_color=AMBER))
    fig.update_xaxes(title_text="horas extra/empleado/mes", title_font_size=9)
    return _res(f"{a['overtime_hours'].mean():.1f}", "h/FTE/mes",
                f"{100 * (a.groupby('employee_id')['overtime_hours'].mean() > 20).mean():.0f}% de empleados promedia >20h extra/mes",
                fig=_theme(fig, height=220))


@kpi(47)   # Tasa de Puntualidad
def k_punctuality(ctx):
    a = ctx["att"].groupby("month").agg(late=("late_arrivals", "sum"), sched=("scheduled_days", "sum"))
    a["rate"] = 100 * (1 - a["late"] / a["sched"])
    fig = go.Figure(go.Scatter(x=list(a.index), y=a["rate"].round(2), mode="lines",
                               line=dict(color=DARK, width=2.5)))
    fig.update_yaxes(title_text="% llegadas a tiempo", title_font_size=9)
    val = a["rate"].iloc[-1]
    return _res(f"{val:.1f}%", "puntualidad", "Días con llegada a tiempo sobre días programados",
                status="ok" if val >= 94 else "warn", fig=_theme(fig))


# ════════════════════════════════════════════════════════════════════════════════
# 8. PLAZAS Y GESTIÓN DE VACANTES
# ════════════════════════════════════════════════════════════════════════════════

@kpi(60)   # Cost of Vacancy (salarial) — barras por vacante abierta
def k_cost_vacancy(ctx):
    anchor = pd.Timestamp(ctx["last_month"] + "-01") + pd.offsets.MonthEnd(0)
    v = ctx["vac"][ctx["vac"]["closed_date"].isna()].copy()
    if v.empty:
        return _res("$0", sublabel="Sin vacantes abiertas en el alcance del rol")
    v["months_open"] = (anchor - pd.to_datetime(v["opened_date"])).dt.days / 30.44
    v["cost"] = v["monthly_salary"] * v["productivity_factor"] * v["months_open"]
    v = v.sort_values("cost").tail(10)
    fig = go.Figure(go.Bar(
        y=[f"V{i:03d} · {_short(d)} · Nivel {l}" for i, d, l in zip(v["vacancy_id"], v["dept"], v["job_level"])],
        x=v["cost"].round(0), orientation="h",
        marker_color=[RED if c > 50_000 else ORANGE for c in v["cost"]]))
    fig.update_xaxes(title_text="USD acumulado desde apertura", title_font_size=9)
    return _res(_money(v["cost"].sum()), "acumulado", f"{len(ctx['vac'][ctx['vac']['closed_date'].isna()])} plazas abiertas — priorizar las más costosas",
                status="warn", fig=_theme(fig, height=280))


@kpi(61)   # Offer Acceptance Rate — línea trimestral
def k_offer_acceptance(ctx):
    v = ctx["vac"][ctx["vac"]["closed_date"].notna()].copy()
    if v.empty:
        return _empty()
    v["q"] = v["closed_date"].str[:7].map(_quarter)
    by = v.groupby("q").agg(acc=("offers_accepted", "sum"), ext=("offers_extended", "sum"))
    by["rate"] = 100 * by["acc"] / by["ext"]
    fig = go.Figure(go.Scatter(x=list(by.index), y=by["rate"].round(1), mode="lines+markers",
                               line=dict(color=ORANGE, width=2.5)))
    fig.add_hline(y=84, line_color=GRAY_MID, line_dash="dot", annotation_text="benchmark Gem 84%", annotation_font_size=9)
    fig.add_hline(y=75, line_color=RED, line_dash="dash", annotation_text="alerta", annotation_font_size=9)
    val = 100 * by["acc"].sum() / by["ext"].sum()
    return _res(f"{val:.0f}%", "aceptación", "Bajo 75% = pérdida de competitividad salarial o employer branding",
                status="ok" if val >= 75 else "warn", fig=_theme(fig))


@kpi(62)   # Quality of Hire — barras por cohorte trimestral
def k_quality_hire(ctx):
    v = ctx["vac"][(ctx["vac"]["closed_date"].notna()) & (ctx["vac"]["quality_of_hire"].notna())].copy()
    if v.empty:
        return _empty()
    v["q"] = v["closed_date"].str[:7].map(_quarter)
    by = v.groupby("q")["quality_of_hire"].mean()
    fig = go.Figure(go.Bar(x=list(by.index), y=by.round(1), marker_color=ORANGE))
    fig.add_hline(y=70, line_color=GRAY_MID, line_dash="dot", annotation_text="meta 70", annotation_font_size=9)
    fig.update_yaxes(title_text="score 0–100", title_font_size=9)
    val = v["quality_of_hire"].mean()
    return _res(f"{val:.0f}", "/ 100", "Desempeño 1er año + retención + evaluación del manager",
                status="ok" if val >= 70 else "warn", fig=_theme(fig))


@kpi(64)   # Open Position Rate
def k_open_rate(ctx):
    open_v = ctx["vac"][ctx["vac"]["closed_date"].isna()]
    hc = ctx["hist"][ctx["hist"]["month"] == ctx["last_month"]]["headcount"].sum()
    by = open_v.groupby("dept").size().sort_values()
    fig = go.Figure(go.Bar(y=[_short(i) for i in by.index], x=by.values, orientation="h", marker_color=DARK))
    fig.update_xaxes(title_text="plazas abiertas hoy", title_font_size=9)
    val = 100 * len(open_v) / max(hc + len(open_v), 1)
    return _res(f"{val:.1f}%", "de la estructura", f"{len(open_v)} plazas sin cubrir sobre {hc:,} ocupadas",
                fig=_theme(fig, height=220))


# ── Ensamble final ──────────────────────────────────────────────────────────────
def _build_items(rows, ctx, can_salary, no_match) -> list:
    items = []
    for _, meta in rows.iterrows():
        idx = int(meta["Indice"])
        reg = REGISTRY.get(idx)
        locked = idx in SALARY_KPIS and not can_salary
        result = None
        if reg and not locked:
            if no_match:
                result = _empty("Sin empleados que coincidan con los filtros")
            else:
                try:
                    result = reg["fn"](ctx)
                except Exception:
                    result = _empty("No calculable con los filtros actuales")
        items.append({
            "meta":    meta.to_dict(),
            "result":  result,
            "locked":  locked,
            "wide":    bool(reg["wide"]) if reg else False,
            "no_data": reg is None,
        })
    return items


def build_all(conn, role_cfg: dict, category: str | None = None, filters=None) -> list:
    """Devuelve [{category, icon, slug, items:[{meta, result, locked, wide, no_data}]}].
    Con category (nombre o slug, o "resumen") construye solo esa hoja; filters son
    los segmentadores de la hoja."""
    catalog = load_catalog()
    can_salary = bool(role_cfg.get("can_see_salary", True))
    ctx = build_context(conn, role_cfg, filters)
    no_match = ctx["emp"].empty

    if category == "resumen":
        rows = catalog.set_index("Indice").loc[SUMMARY_KPIS].reset_index()
        return [{"category": "Resumen Ejecutivo", "icon": "📌", "slug": "resumen",
                 "items": _build_items(rows, ctx, can_salary, no_match)}]

    category = SLUG_TO_CAT.get(category, category)
    sections = []
    for cat, icon, slug in CATEGORY_ORDER:
        if category and cat != category:
            continue
        rows = catalog[catalog["Categoria"] == cat].sort_values("Puntaje Relevancia", ascending=False)
        sections.append({"category": cat, "icon": icon, "slug": slug,
                         "items": _build_items(rows, ctx, can_salary, no_match)})
    return sections
