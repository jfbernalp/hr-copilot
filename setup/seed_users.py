"""
seed_users.py
-------------
Crea la tabla `users` y los 4 usuarios demo del laboratorio (uno por rol RLS).
Idempotente: re-correrlo restablece los usuarios demo a su estado inicial.

    python setup/seed_users.py

Credenciales demo (solo laboratorio — cambiar en producción):
    admin          / Praxedes2026!   → hr_admin
    sales.manager  / Sales2026!      → sales_manager
    rd.manager     / RD2026!         → rd_manager
    viewer         / Viewer2026!     → employee_viewer
"""

import os
import sys
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "data", "hr_analytics.db")
sys.path.insert(0, os.path.join(BASE_DIR, "app"))

from auth import hash_password

DEMO_USERS = [
    ("admin",         "Praxedes2026!", "hr_admin",        "Administrador de Talento Humano"),
    ("sales.manager", "Sales2026!",    "sales_manager",   "Gerente Comercial"),
    ("rd.manager",    "RD2026!",       "rd_manager",      "Gerente de I+D"),
    ("viewer",        "Viewer2026!",   "employee_viewer", "Analista (sin salarios)"),
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username      TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            salt          TEXT NOT NULL,
            role          TEXT NOT NULL,
            full_name     TEXT,
            active        INTEGER DEFAULT 1
        )
    """)
    for username, password, role, full_name in DEMO_USERS:
        pw_hash, salt = hash_password(password)
        conn.execute(
            "INSERT OR REPLACE INTO users (username, password_hash, salt, role, full_name, active) "
            "VALUES (?,?,?,?,?,1)",
            (username, pw_hash, salt, role, full_name),
        )
        print(f"  {username:<14} → {role}")
    conn.commit()
    conn.close()
    print(f"\n{len(DEMO_USERS)} usuarios demo listos en {DB_PATH}")


if __name__ == "__main__":
    main()
