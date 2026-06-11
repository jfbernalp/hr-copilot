"""
rls.py
------
Interceptor Row-Level Security para HR Copilot.
Modifica el SQL según el rol antes de enviarlo a SQLite.

Uso en dashboard_praxedes.py:
    from rls import rls_intercept, ROLES
    sql_filtrado = rls_intercept(sql, current_role, conn)
    df = pd.read_sql_query(sql_filtrado, conn)
"""

import re
from datetime import datetime

ROLES = {
    "hr_admin":        {"dept_filter": None, "can_see_salary": True,  "blocked_cols": []},
    "sales_manager":   {"dept_filter": 1,    "can_see_salary": True,  "blocked_cols": []},
    "rd_manager":      {"dept_filter": 2,    "can_see_salary": True,  "blocked_cols": []},
    "employee_viewer": {"dept_filter": None, "can_see_salary": False, "blocked_cols": ["MonthlyIncome", "DailyRate", "HourlyRate", "MonthlyRate"]},
}

DEPT_NAMES = {1: "Sales", 2: "Research & Development"}

# Columnas con cifras salariales: IBM + tablas sintéticas de nómina/vacantes.
# También se bloquean tablas que son 100% salariales (payroll_monthly, salary_bands).
_SALARY_COLS = {
    "monthlyincome", "dailyrate", "hourlyrate", "monthlyrate",
    "base_salary", "benefits", "employer_contributions", "overtime_pay",
    "total_cost", "monthly_salary", "band_min", "band_mid", "band_max",
    "payroll_monthly", "salary_bands",
}

# Mecanismo de filtrado por departamento según el grano de cada tabla:
#  - department_id directo
_DEPT_TABLES = {"employees", "vacancies", "headcount_history"}
#  - grano empleado → subconsulta sobre employees
_EMP_TABLES = {"attendance_monthly", "payroll_monthly", "medical_leaves",
               "survey_responses", "training_participants", "vacation_balances",
               "employment_dates", "satisfaction"}
# El resto (payroll_runs, company_financials, salary_bands, survey_cycles,
# training_programs, departments, job_roles) es agregado global: no se filtra.


def _has_salary_cols(sql: str) -> bool:
    sql_lower = sql.lower()
    return any(col in sql_lower for col in _SALARY_COLS)


_KEYWORDS = {"where", "group", "order", "having", "limit", "on", "join", "left",
             "right", "inner", "outer", "cross", "union", "as", "select"}


def _table_ref(sql: str, table: str):
    """Devuelve la referencia usable (alias o nombre) si la tabla aparece en el SQL."""
    m = re.search(rf"\b(?:FROM|JOIN)\s+{table}\b(?:\s+(?:AS\s+)?([a-zA-Z_]\w*))?",
                  sql, re.IGNORECASE)
    if not m:
        return None
    alias = m.group(1)
    return alias if alias and alias.lower() not in _KEYWORDS else table


def _inject_dept_filter(sql: str, dept_id: int) -> str:
    """
    Inyecta el filtro de departamento adaptado a las tablas de la query:
      - tablas con department_id → <ref>.department_id = X
      - tablas con grano empleado → <ref>.employee_id IN (subconsulta)
      - tablas de agregado global → sin filtro
    """
    sql = sql.strip().rstrip(";")

    clause = None
    for table in _DEPT_TABLES:
        ref = _table_ref(sql, table)
        if ref:
            clause = f"{ref}.department_id = {dept_id}"
            break
    if clause is None:
        for table in _EMP_TABLES:
            ref = _table_ref(sql, table)
            if ref:
                clause = (f"{ref}.employee_id IN (SELECT employee_id FROM employees "
                          f"WHERE department_id = {dept_id})")
                break
    if clause is None:
        return sql   # solo tablas globales: nada que filtrar

    where_match = re.search(r"\bWHERE\b", sql, re.IGNORECASE)
    if where_match:
        pos = where_match.end()
        sql = sql[:pos] + f" {clause} AND" + sql[pos:]
    else:
        boundary = re.search(r"\b(GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT)\b", sql, re.IGNORECASE)
        if boundary:
            pos = boundary.start()
            sql = sql[:pos].rstrip() + f"\nWHERE {clause}\n" + sql[pos:]
        else:
            sql = sql + f"\nWHERE {clause}"

    return sql


def rls_intercept(sql: str, rol: str, conn=None, user: str | None = None) -> str:
    """
    Aplica las reglas RLS al SQL.

    Lanza:
        ValueError    — rol desconocido
        PermissionError — el rol no tiene acceso a las columnas solicitadas

    Retorna el SQL (posiblemente modificado con filtros de departamento).
    `user` es el username autenticado, solo para la auditoría.
    """
    if rol not in ROLES:
        raise ValueError(f"Rol desconocido: '{rol}'. Roles válidos: {list(ROLES.keys())}")

    config = ROLES[rol]

    # Bloquear acceso a columnas salariales
    if not config["can_see_salary"] and _has_salary_cols(sql):
        _audit_log(conn, rol, sql, "BLOCKED", user)
        raise PermissionError(
            f"El rol '{rol}' no tiene permiso para consultar columnas salariales "
            "(MonthlyIncome, DailyRate, HourlyRate, MonthlyRate, payroll, bandas)."
        )

    # Inyectar filtro de departamento
    if config["dept_filter"] is not None:
        sql = _inject_dept_filter(sql, config["dept_filter"])

    _audit_log(conn, rol, sql, "ALLOWED", user)
    return sql


def _audit_log(conn, rol: str, sql: str, action: str, user: str | None = None):
    """Registra la query en rls_audit_log. Falla silenciosamente."""
    if conn is None:
        return
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS rls_audit_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        TEXT,
                rol       TEXT,
                action    TEXT,
                sql_query TEXT,
                username  TEXT
            )"""
        )
        try:
            conn.execute("ALTER TABLE rls_audit_log ADD COLUMN username TEXT")
        except Exception:
            pass
        conn.execute(
            "INSERT INTO rls_audit_log (ts, rol, action, sql_query, username) VALUES (?,?,?,?,?)",
            (datetime.utcnow().isoformat(), rol, action, sql, user),
        )
        conn.commit()
    except Exception:
        pass
