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

_SALARY_COLS = {"monthlyincome", "dailyrate", "hourlyrate", "monthlyrate"}


def _has_salary_cols(sql: str) -> bool:
    sql_lower = sql.lower()
    return any(col in sql_lower for col in _SALARY_COLS)


def _inject_dept_filter(sql: str, dept_id: int) -> str:
    """
    Inyecta WHERE e.department_id = <dept_id> en el SQL.
    Maneja queries con y sin WHERE existente.
    """
    sql = sql.strip().rstrip(";")
    filter_clause = f"department_id = {dept_id}"

    where_match = re.search(r"\bWHERE\b", sql, re.IGNORECASE)
    if where_match:
        pos = where_match.end()
        sql = sql[:pos] + f" {filter_clause} AND" + sql[pos:]
    else:
        boundary = re.search(r"\b(GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT)\b", sql, re.IGNORECASE)
        if boundary:
            pos = boundary.start()
            sql = sql[:pos].rstrip() + f"\nWHERE {filter_clause}\n" + sql[pos:]
        else:
            sql = sql + f"\nWHERE {filter_clause}"

    return sql


def rls_intercept(sql: str, rol: str, conn=None) -> str:
    """
    Aplica las reglas RLS al SQL.

    Lanza:
        ValueError    — rol desconocido
        PermissionError — el rol no tiene acceso a las columnas solicitadas

    Retorna el SQL (posiblemente modificado con filtros de departamento).
    """
    if rol not in ROLES:
        raise ValueError(f"Rol desconocido: '{rol}'. Roles válidos: {list(ROLES.keys())}")

    config = ROLES[rol]

    # Bloquear acceso a columnas salariales
    if not config["can_see_salary"] and _has_salary_cols(sql):
        _audit_log(conn, rol, sql, "BLOCKED")
        raise PermissionError(
            f"El rol '{rol}' no tiene permiso para consultar columnas salariales "
            "(MonthlyIncome, DailyRate, HourlyRate, MonthlyRate)."
        )

    # Inyectar filtro de departamento
    if config["dept_filter"] is not None:
        sql = _inject_dept_filter(sql, config["dept_filter"])

    _audit_log(conn, rol, sql, "ALLOWED")
    return sql


def _audit_log(conn, rol: str, sql: str, action: str):
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
                sql_query TEXT
            )"""
        )
        conn.execute(
            "INSERT INTO rls_audit_log (ts, rol, action, sql_query) VALUES (?,?,?,?)",
            (datetime.utcnow().isoformat(), rol, action, sql),
        )
        conn.commit()
    except Exception:
        pass
