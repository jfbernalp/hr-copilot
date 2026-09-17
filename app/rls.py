"""
rls.py
------
Interceptor Row-Level Security para HR Copilot — NovaTech Colombia S.A.S.
Filtra por sede (Medellín / Bogotá) y bloquea columnas salariales según el rol.

Roles disponibles:
  hr_admin         → acceso completo, todas las sedes, ve salarios
  gerente_medellin → solo datos de Medellín, ve salarios
  lider_bogota     → solo datos de Bogotá, no ve salarios
  viewer           → todas las sedes, no ve salarios
"""

import re
from datetime import datetime

ROLES = {
    "hr_admin":         {"sede_filter": None,       "can_see_salary": True,  "blocked_cols": []},
    "gerente_medellin": {"sede_filter": "Medellín", "can_see_salary": True,  "blocked_cols": []},
    "lider_bogota":     {"sede_filter": "Bogotá",   "can_see_salary": False, "blocked_cols": []},
    "viewer":           {"sede_filter": None,        "can_see_salary": False, "blocked_cols": []},
}

# Columnas y vistas con información salarial
_SALARY_TOKENS = {
    "salario_basico", "salario_actual", "salario_neto", "salario_ofrecido",
    "costo_total_empresa", "valor_horas_extra", "bonificaciones", "comisiones",
    "deduccion_salud", "deduccion_pension", "aporte_salud_emp", "aporte_pension_emp",
    "aporte_arl", "aporte_caja_comp", "incremento_salarial", "salario_promedio",
    "v_nomina_mensual", "salarios", "financials_empresa",
}

DEPT_NAMES = {}   # No usado en este esquema, mantenido por compatibilidad


def _has_salary_cols(sql: str) -> bool:
    sql_lower = sql.lower()
    return any(tok in sql_lower for tok in _SALARY_TOKENS)


def _inject_sede_filter(sql: str, sede: str) -> str:
    """
    Inyecta WHERE sede = 'X' en la query principal.
    Funciona para queries simples y CTEs (inyecta en el primer WHERE encontrado).
    """
    sql = sql.strip().rstrip(";")
    clause = f"sede = $__sede__$"  # placeholder para evitar inyección SQL

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

    # Sustituye el placeholder con el valor real (entrecomillado)
    safe_sede = sede.replace("'", "''")
    return sql.replace("$__sede__$", f"'{safe_sede}'")


def rls_intercept(sql: str, rol: str, conn=None, user: str | None = None) -> str:
    """
    Aplica RLS al SQL antes de ejecutarlo.

    Lanza:
        ValueError      — rol desconocido
        PermissionError — el rol no puede ver datos salariales

    Retorna el SQL modificado.
    """
    if rol not in ROLES:
        raise ValueError(f"Rol desconocido: '{rol}'. Roles válidos: {list(ROLES.keys())}")

    config = ROLES[rol]

    if not config["can_see_salary"] and _has_salary_cols(sql):
        _audit_log(conn, rol, sql, "BLOCKED", user)
        raise PermissionError(
            f"El rol '{rol}' no tiene permiso para consultar datos salariales "
            "(salarios, nómina, costos laborales)."
        )

    if config["sede_filter"]:
        sql = _inject_sede_filter(sql, config["sede_filter"])

    _audit_log(conn, rol, sql, "ALLOWED", user)
    return sql


def _audit_log(conn, rol: str, sql: str, action: str, user: str | None = None):
    if conn is None:
        return
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rls_audit_log (
                id        SERIAL PRIMARY KEY,
                ts        TEXT,
                rol       TEXT,
                action    TEXT,
                sql_query TEXT,
                username  TEXT
            )
        """)
        conn.execute(
            "INSERT INTO rls_audit_log (ts, rol, action, sql_query, username) VALUES (%s,%s,%s,%s,%s)",
            (datetime.utcnow().isoformat(), rol, action, sql, user),
        )
    except Exception:
        pass
