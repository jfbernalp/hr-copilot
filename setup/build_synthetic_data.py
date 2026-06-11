"""
build_synthetic_data.py
-----------------------
Genera las tablas sintéticas que el catálogo de KPIs (data/kpi_catalog.csv)
necesita y que el dataset IBM no trae: asistencia, incapacidades, nómina,
vacantes, encuestas de clima, capacitación, vacaciones y financieros.

Principio de coherencia: a cada empleado se le asigna una fecha de ingreso
derivada de YearsAtCompany y, si Attrition='Yes', una fecha de salida dentro
de la ventana de 24 meses. Asistencia, nómina y headcount histórico se
derivan de esas fechas, así los KPIs cruzados cuadran entre sí.

Reproducible: seed fija (42). Correr desde el root del proyecto:
    python setup/build_synthetic_data.py
"""

import os
import sqlite3
import numpy as np
import pandas as pd

# ── Paths & Config ─────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "data", "hr_analytics.db")

SEED   = 42
rng    = np.random.default_rng(SEED)
MONTHS = pd.period_range("2024-06", "2026-05", freq="M")   # ventana de 24 meses
END_TS = MONTHS[-1].to_timestamp(how="end").normalize()

# Incrementos salariales anuales aplicados en enero (el salario actual de la BD
# es el vigente en 2026; hacia atrás se deflacta)
INCREASE_2025 = 0.09
INCREASE_2026 = 0.08

SYNTH_TABLES = [
    "employment_dates", "attendance_monthly", "medical_leaves",
    "payroll_monthly", "payroll_runs", "salary_bands", "headcount_history",
    "vacancies", "survey_cycles", "survey_responses",
    "training_programs", "training_participants",
    "company_financials", "vacation_balances",
]


def load_employees(conn) -> pd.DataFrame:
    return pd.read_sql_query("""
        SELECT e.employee_id, e.MonthlyIncome, e.OverTime, e.Attrition,
               e.YearsAtCompany, e.JobLevel, e.department_id, e.role_id,
               e.TrainingTimesLastYear,
               s.JobSatisfaction, s.WorkLifeBalance, s.JobInvolvement,
               s.EnvironmentSatisfaction, s.PerformanceRating
        FROM employees e LEFT JOIN satisfaction s USING (employee_id)
    """, conn)


# ── Fechas de empleo (tabla base de coherencia) ─────────────────────────────────
def build_employment_dates(emp: pd.DataFrame) -> pd.DataFrame:
    n = len(emp)
    leavers = emp["Attrition"] == "Yes"

    # Salida: mes aleatorio dentro de la ventana para quienes se fueron
    exit_month_idx = rng.integers(0, len(MONTHS), size=n)
    exit_day       = rng.integers(1, 28, size=n)
    exit_date = pd.Series(
        [MONTHS[i].to_timestamp() + pd.Timedelta(days=int(d) - 1)
         for i, d in zip(exit_month_idx, exit_day)]
    )
    exit_date[~leavers] = pd.NaT

    # Ingreso: ancla (salida o hoy) menos la antigüedad reportada
    anchor = exit_date.fillna(END_TS)
    extra_months = rng.integers(1, 12, size=n)  # YearsAtCompany trunca: añadir meses
    hire_date = anchor - pd.to_timedelta(
        (emp["YearsAtCompany"].values * 12 + extra_months) * 30.44, unit="D")

    # Tipo de salida (para headcount_history y costos de rotación)
    exit_type = np.where(leavers, np.where(rng.random(n) < 0.65, "voluntary", "involuntary"), None)

    return pd.DataFrame({
        "employee_id": emp["employee_id"],
        "hire_date":   hire_date.dt.strftime("%Y-%m-%d"),
        "exit_date":   exit_date.dt.strftime("%Y-%m-%d"),
        "exit_type":   exit_type,
    })


def active_matrix(dates: pd.DataFrame) -> pd.DataFrame:
    """DataFrame booleano empleado × mes: estuvo activo (algún día) ese mes."""
    hire = pd.to_datetime(dates["hire_date"])
    exit_ = pd.to_datetime(dates["exit_date"])
    out = {}
    for m in MONTHS:
        start, end = m.to_timestamp(), m.to_timestamp(how="end")
        out[str(m)] = (hire <= end) & (exit_.isna() | (exit_ >= start))
    df = pd.DataFrame(out)          # index posicional: alineado con emp/dates
    df.index = dates["employee_id"].values
    return df


# ── Asistencia mensual ──────────────────────────────────────────────────────────
def build_attendance(emp: pd.DataFrame, active: pd.DataFrame) -> pd.DataFrame:
    sched_by_month = {str(m): int(rng.integers(20, 24)) for m in MONTHS}

    # Propensión al ausentismo ligada a satisfacción y balance (señal Flight Risk)
    job_sat = emp["JobSatisfaction"].fillna(3).values
    wlb     = emp["WorkLifeBalance"].fillna(3).values
    lam_abs = 0.25 + 0.22 * (4 - job_sat) + 0.18 * (4 - wlb)
    ot_yes  = (emp["OverTime"] == "Yes").values

    rows = []
    for col in active.columns:
        mask  = active[col].values
        idx   = np.where(mask)[0]
        sched = sched_by_month[col]
        absd  = np.minimum(rng.poisson(lam_abs[idx]), sched)
        ot    = np.where(ot_yes[idx],
                         np.clip(rng.normal(28, 9, len(idx)), 6, 60),
                         np.clip(rng.poisson(1.2, len(idx)).astype(float), 0, 6))
        rows.append(pd.DataFrame({
            "employee_id":    emp["employee_id"].values[idx],
            "month":          col,
            "scheduled_days": sched,
            "absence_days":   absd,
            "regular_hours":  (sched - absd) * 8,
            "overtime_hours": np.round(ot, 1),
            "late_arrivals":  rng.poisson(0.9, len(idx)),
        }))
    return pd.concat(rows, ignore_index=True)


# ── Incapacidades médicas ───────────────────────────────────────────────────────
def build_medical_leaves(att: pd.DataFrame) -> pd.DataFrame:
    # Frecuencia objetivo ≈ 0.13 incapacidades/empleado/trimestre (benchmark del catálogo)
    n_leaves = int(len(att) * 0.045)
    sample   = att.sample(n=n_leaves, random_state=SEED)
    types = rng.choice(
        ["Enfermedad General (EPS)", "Accidente de Trabajo (ARL)", "Enfermedad Laboral (ARL)"],
        p=[0.81, 0.135, 0.055], size=n_leaves)
    days = np.select(
        [types == "Enfermedad General (EPS)", types == "Accidente de Trabajo (ARL)"],
        [np.clip(rng.gamma(2.0, 2.0, n_leaves), 1, 20),
         np.clip(rng.gamma(2.5, 4.0, n_leaves), 1, 45)],
        default=np.clip(rng.gamma(3.0, 8.0, n_leaves), 5, 90)).round().astype(int)
    start = [f"{m}-{d:02d}" for m, d in zip(sample["month"], rng.integers(1, 28, n_leaves))]
    return pd.DataFrame({
        "employee_id": sample["employee_id"].values,
        "start_date":  start,
        "days":        days,
        "leave_type":  types,
    }).reset_index(drop=True)


# ── Nómina mensual y corridas de pago ──────────────────────────────────────────
def deflator(month: str) -> float:
    year = int(month[:4])
    if year >= 2026:
        return 1.0
    if year == 2025:
        return 1 / (1 + INCREASE_2026)
    return 1 / ((1 + INCREASE_2026) * (1 + INCREASE_2025))


def build_payroll(emp: pd.DataFrame, att: pd.DataFrame) -> pd.DataFrame:
    income = emp.set_index("employee_id")["MonthlyIncome"]
    base   = att["employee_id"].map(income) * att["month"].map(deflator)
    ot_pay = att["overtime_hours"] * (base / 192) * 1.25
    benefits = base * 0.10
    contrib  = base * 0.30   # prestaciones + seguridad social + parafiscales (aprox.)
    return pd.DataFrame({
        "employee_id":            att["employee_id"],
        "month":                  att["month"],
        "base_salary":            base.round(0),
        "benefits":               benefits.round(0),
        "employer_contributions": contrib.round(0),
        "overtime_pay":           ot_pay.round(0),
        "total_cost":             (base + benefits + contrib + ot_pay).round(0),
    })


def build_payroll_runs(payroll: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for m in MONTHS:
        col = str(m)
        scheduled = m.to_timestamp(how="end").normalize()
        delay     = int(rng.choice([0, 0, 0, 0, 0, 0, 0, 0, 1, 2]))  # ~80% puntual
        n_slips   = int((payroll["month"] == col).sum())
        rows.append({
            "month":                 col,
            "scheduled_pay_date":    scheduled.strftime("%Y-%m-%d"),
            "actual_pay_date":       (scheduled + pd.Timedelta(days=delay)).strftime("%Y-%m-%d"),
            "payslips_total":        n_slips,
            "payslips_with_errors":  int(rng.binomial(n_slips, 0.008)),
        })
    return pd.DataFrame(rows)


# ── Bandas salariales (Compa-Ratio) ─────────────────────────────────────────────
def build_salary_bands(emp: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for level, grp in emp.groupby("JobLevel"):
        mid = float(grp["MonthlyIncome"].median())
        rows.append({
            "job_level": int(level),
            "band_min":  round(mid * 0.72),
            "band_mid":  round(mid),
            "band_max":  round(mid * 1.28),
        })
    return pd.DataFrame(rows)


# ── Headcount histórico ─────────────────────────────────────────────────────────
def build_headcount_history(emp: pd.DataFrame, dates: pd.DataFrame) -> pd.DataFrame:
    d = dates.copy()
    d["department_id"] = emp["department_id"].values
    d["hire_month"] = pd.to_datetime(d["hire_date"]).dt.to_period("M").astype(str)
    d["exit_month"] = pd.to_datetime(d["exit_date"]).dt.to_period("M").astype(str)
    hire = pd.to_datetime(d["hire_date"])
    exit_ = pd.to_datetime(d["exit_date"])

    rows = []
    for m in MONTHS:
        col, end = str(m), m.to_timestamp(how="end")
        active_eom = (hire <= end) & (exit_.isna() | (exit_ > end))
        for dept, grp in d.groupby("department_id"):
            in_dept = d["department_id"] == dept
            exits   = grp[grp["exit_month"] == col]
            rows.append({
                "month":            col,
                "department_id":    int(dept),
                "headcount":        int((active_eom & in_dept).sum()),
                "hires":            int((grp["hire_month"] == col).sum()),
                "exits_voluntary":   int((exits["exit_type"] == "voluntary").sum()),
                "exits_involuntary": int((exits["exit_type"] == "involuntary").sum()),
            })
    return pd.DataFrame(rows)


# ── Vacantes ────────────────────────────────────────────────────────────────────
def build_vacancies(emp: pd.DataFrame, bands: pd.DataFrame) -> pd.DataFrame:
    n = 130
    dept_w = emp["department_id"].value_counts(normalize=True)
    levels = rng.choice([1, 2, 3, 4, 5], p=[0.42, 0.28, 0.16, 0.09, 0.05], size=n)
    ttf_mu = {1: 28, 2: 40, 3: 55, 4: 75, 5: 95}
    mids   = bands.set_index("job_level")["band_mid"]
    roles  = emp.groupby("department_id")["role_id"].apply(lambda s: s.unique())

    opened = pd.to_datetime([
        MONTHS[i].to_timestamp() + pd.Timedelta(days=int(d))
        for i, d in zip(rng.integers(0, len(MONTHS), n), rng.integers(0, 27, n))])
    depts = rng.choice(dept_w.index.values, p=dept_w.values, size=n)
    ttf   = np.array([max(7, rng.normal(ttf_mu[lv], ttf_mu[lv] * 0.28)) for lv in levels]).round()
    closed = opened + pd.to_timedelta(ttf, unit="D")
    is_closed = closed <= END_TS

    offers_ext = np.where(rng.random(n) < 0.72, 1, rng.integers(2, 4, size=n))
    filled_by  = np.where(is_closed, np.where(rng.random(n) < 0.30, "internal", "external"), None)
    quality    = np.where(is_closed, np.clip(rng.normal(74, 9, n), 40, 95).round(1), np.nan)

    return pd.DataFrame({
        "vacancy_id":          range(1, n + 1),
        "department_id":       depts.astype(int),
        "role_id":             [int(rng.choice(roles[d])) for d in depts],
        "job_level":           levels.astype(int),
        "opened_date":         opened.strftime("%Y-%m-%d"),
        "closed_date":         np.where(is_closed, closed.strftime("%Y-%m-%d"), None),
        "monthly_salary":      (mids.loc[levels].values * rng.normal(1, 0.08, n)).round(0),
        "productivity_factor": (0.5 + 0.3 * levels).round(1),
        "offers_extended":     np.where(is_closed, offers_ext, 0).astype(int),
        "offers_accepted":     is_closed.astype(int),
        "filled_by":           filled_by,
        "quality_of_hire":     quality,
    })


# ── Encuestas de clima (engagement, eNPS, participación) ───────────────────────
def build_surveys(emp: pd.DataFrame, active: pd.DataFrame):
    quarters = [q for q in pd.period_range("2024Q3", "2026Q2", freq="Q")]
    cycles, responses = [], []
    job_sat = emp["JobSatisfaction"].fillna(3).values
    env_sat = emp["EnvironmentSatisfaction"].fillna(3).values
    invol   = emp["JobInvolvement"].fillna(3).values

    for q in quarters:
        month_col = str(q.asfreq("M", how="end"))
        if month_col not in active.columns:
            month_col = active.columns[-1]
        mask = active[month_col].values
        invited = int(mask.sum())
        part_rate = float(np.clip(rng.normal(0.72, 0.06), 0.55, 0.88))
        idx = np.where(mask)[0]
        respondents = rng.choice(idx, size=int(invited * part_rate), replace=False)

        cycles.append({"cycle": str(q), "survey_date": q.asfreq("M", how="end").to_timestamp(how="end").strftime("%Y-%m-%d"), "invited": invited})
        nr = len(respondents)
        responses.append(pd.DataFrame({
            "employee_id":     emp["employee_id"].values[respondents],
            "cycle":           str(q),
            "q_pride":         np.clip(rng.normal(job_sat[respondents] * 1.05, 0.7), 1, 5).round().astype(int),
            "q_recommend_nps": np.clip(rng.normal(2.4 + 1.8 * job_sat[respondents], 1.4), 0, 10).round().astype(int),
            "q_effort":        np.clip(rng.normal(invol[respondents] * 1.1, 0.6), 1, 5).round().astype(int),
            "q_stay":          np.clip(rng.normal(env_sat[respondents], 0.8), 1, 5).round().astype(int),
            "q_satisfaction":  np.clip(rng.normal(1.0 + 1.6 * env_sat[respondents], 1.4), 0, 10).round().astype(int),
        }))
    return pd.DataFrame(cycles), pd.concat(responses, ignore_index=True)


# ── Capacitación (Training Effectiveness) ──────────────────────────────────────
def build_trainings(emp: pd.DataFrame, active: pd.DataFrame):
    catalog = [
        ("Liderazgo para mandos medios",        "Liderazgo"),
        ("Atención al cliente",                 "Comercial"),
        ("Seguridad y salud en el trabajo",     "SST"),
        ("Excel y analítica de datos",          "Datos"),
        ("Ventas consultivas",                  "Comercial"),
        ("Metodologías ágiles",                 "Procesos"),
        ("Comunicación efectiva",               "Habilidades blandas"),
        ("Innovación y mejora continua",        "Procesos"),
        ("Gestión del tiempo",                  "Habilidades blandas"),
        ("Inteligencia artificial aplicada",    "Datos"),
    ]
    trainable = emp["TrainingTimesLastYear"].fillna(0).values > 0
    programs, participants = [], []
    for pid, (name, cat) in enumerate(catalog, start=1):
        m = str(rng.choice(MONTHS[:-3]))  # deja 3 meses para medir el "post"
        date = f"{m}-15"
        effect = float(rng.normal(0.22, 0.18))   # algunos programas casi no mueven la aguja
        programs.append({"program_id": pid, "program_name": name, "category": cat,
                         "program_date": date, "cost_usd": int(rng.integers(3000, 25000))})
        mask = active[m].values & trainable
        idx = np.where(mask)[0]
        chosen = rng.choice(idx, size=min(int(rng.integers(40, 130)), len(idx)), replace=False)
        pre  = np.clip(rng.normal(3.1, 0.5, len(chosen)), 1, 5)
        post = np.clip(pre + effect + rng.normal(0, 0.15, len(chosen)), 1, 5)
        participants.append(pd.DataFrame({
            "program_id":     pid,
            "employee_id":    emp["employee_id"].values[chosen],
            "perf_score_pre":  pre.round(2),
            "perf_score_post": post.round(2),
        }))
    return pd.DataFrame(programs), pd.concat(participants, ignore_index=True)


# ── Financieros y vacaciones ────────────────────────────────────────────────────
def build_financials(payroll: pd.DataFrame) -> pd.DataFrame:
    cost = payroll.groupby("month")["total_cost"].sum()
    rows = []
    for i, m in enumerate(MONTHS):
        season = 1 + 0.10 * np.sin(2 * np.pi * (m.month - 3) / 12)   # pico hacia fin de año
        growth = 1 + 0.004 * i
        revenue = cost[str(m)] / 0.27 * season * growth * rng.normal(1, 0.03)
        rows.append({"month": str(m), "operating_revenue": round(revenue)})
    return pd.DataFrame(rows)


def build_vacations(emp: pd.DataFrame, dates: pd.DataFrame) -> pd.DataFrame:
    act = dates["exit_date"].isna().values
    tenure = emp["YearsAtCompany"].values
    pending = np.clip(rng.normal(7 + 0.7 * tenure, 4), 0, 45).round().astype(int)
    accrued = (15 * (tenure + 0.5)).round().astype(int)
    return pd.DataFrame({
        "employee_id":  emp["employee_id"].values[act],
        "accrued_days": accrued[act],
        "taken_days":   np.maximum(accrued - pending, 0)[act],
        "pending_days": pending[act],
    })


# ── Main ────────────────────────────────────────────────────────────────────────
def main():
    conn = sqlite3.connect(DB_PATH)
    emp = load_employees(conn)
    print(f"Empleados base: {len(emp)} | Ventana: {MONTHS[0]} → {MONTHS[-1]}")

    dates  = build_employment_dates(emp)
    active = active_matrix(dates)
    att    = build_attendance(emp, active)
    leaves = build_medical_leaves(att)
    payroll = build_payroll(emp, att)
    runs   = build_payroll_runs(payroll)
    bands  = build_salary_bands(emp)
    hist   = build_headcount_history(emp, dates)
    vac    = build_vacancies(emp, bands)
    cycles, resp = build_surveys(emp, active)
    progs, parts = build_trainings(emp, active)
    fin    = build_financials(payroll)
    vacat  = build_vacations(emp, dates)

    tables = {
        "employment_dates":     dates,   "attendance_monthly": att,
        "medical_leaves":       leaves,  "payroll_monthly":    payroll,
        "payroll_runs":         runs,    "salary_bands":       bands,
        "headcount_history":    hist,    "vacancies":          vac,
        "survey_cycles":        cycles,  "survey_responses":   resp,
        "training_programs":    progs,   "training_participants": parts,
        "company_financials":   fin,     "vacation_balances":  vacat,
    }
    for name in SYNTH_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {name}")
    for name, df in tables.items():
        df.to_sql(name, conn, index=False)
        print(f"  {name:<24} {len(df):>6} filas")
    conn.commit()

    # ── Validación: KPIs de control contra rangos esperados ──
    print("\nValidación de KPIs de control:")
    q = lambda sql: pd.read_sql_query(sql, conn).iloc[0, 0]
    checks = [
        ("Tasa de ausentismo global (%)",
         q("SELECT 100.0*SUM(absence_days)/SUM(scheduled_days) FROM attendance_monthly"), 2, 6),
        ("Overtime rate (% horas)",
         q("SELECT 100.0*SUM(overtime_hours)/SUM(regular_hours) FROM attendance_monthly"), 3, 12),
        ("Time to Fill prom. (días)",
         q("SELECT AVG(julianday(closed_date)-julianday(opened_date)) FROM vacancies WHERE closed_date IS NOT NULL"), 25, 60),
        ("Aceptación de oferta (%)",
         q("SELECT 100.0*SUM(offers_accepted)/SUM(offers_extended) FROM vacancies WHERE closed_date IS NOT NULL"), 65, 95),
        ("Labor cost ratio (%)",
         q("""SELECT 100.0*(SELECT SUM(total_cost) FROM payroll_monthly)
              /(SELECT SUM(operating_revenue) FROM company_financials)"""), 20, 35),
        ("Incapacidades/empleado/trimestre",
         q("SELECT COUNT(*)*1.0/(SELECT COUNT(*) FROM attendance_monthly)*63 FROM medical_leaves") / 21, 0.08, 0.20),
        ("Rotación anualizada (%)",
         q("""SELECT 100.0*12.0*SUM(exits_voluntary+exits_involuntary)/24
              /(SELECT AVG(headcount) FROM (SELECT month, SUM(headcount) headcount
                 FROM headcount_history GROUP BY month)) FROM headcount_history"""), 6, 14),
        ("Compa-ratio promedio",
         q("""SELECT AVG(1.0*e.MonthlyIncome/b.band_mid) FROM employees e
              JOIN salary_bands b ON e.JobLevel=b.job_level"""), 0.9, 1.15),
    ]
    ok = True
    for name, val, lo, hi in checks:
        status = "OK " if lo <= val <= hi else "FUERA DE RANGO"
        ok &= lo <= val <= hi
        print(f"  [{status}] {name:<38} {val:8.2f}   (esperado {lo}–{hi})")
    conn.close()
    if not ok:
        raise SystemExit("Algún KPI de control quedó fuera de rango — revisar generación.")
    print("\nListo: tablas sintéticas generadas y validadas.")


if __name__ == "__main__":
    main()
