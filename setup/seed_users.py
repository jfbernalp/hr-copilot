"""
seed_users.py
-------------
Crea la tabla `users` y los 4 usuarios demo de NovaTech Colombia en PostgreSQL.
Idempotente: re-correrlo restablece las contraseñas demo.

    python setup/seed_users.py

Usuarios demo (solo laboratorio — cambiar en producción):
    admin              / Praxedes2026!   → hr_admin         (acceso total)
    gerente.medellin   / Medellin2026!   → gerente_medellin (solo Medellín, ve salarios)
    lider.bogota       / Bogota2026!     → lider_bogota     (solo Bogotá, sin salarios)
    viewer             / Viewer2026!     → viewer           (lectura, sin salarios)
"""

import os
import sys
from dotenv import load_dotenv
import psycopg2

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "app"))
load_dotenv(os.path.join(BASE_DIR, ".env"))

from auth import hash_password

DEMO_USERS = [
    ("admin",             "Praxedes2026!", "hr_admin",         "Administrador RR.HH."),
    ("gerente.medellin",  "Medellin2026!", "gerente_medellin", "Gerente Medellín"),
    ("lider.bogota",      "Bogota2026!",   "lider_bogota",     "Líder de Operaciones Bogotá"),
    ("viewer",            "Viewer2026!",   "viewer",           "Analista (solo lectura)"),
]


def main():
    conn = psycopg2.connect(
        host=os.getenv("HR_DB_HOST", "localhost"),
        port=os.getenv("HR_DB_PORT", "5432"),
        dbname=os.getenv("HR_DB_NAME", "hrcopilot"),
        user=os.getenv("HR_DB_USER", "juan"),
        password=os.getenv("HR_DB_PASSWORD", ""),
    )
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username      VARCHAR(60) PRIMARY KEY,
            password_hash TEXT        NOT NULL,
            salt          TEXT        NOT NULL,
            role          VARCHAR(40) NOT NULL,
            full_name     VARCHAR(120),
            active        BOOLEAN     NOT NULL DEFAULT TRUE
        )
    """)

    for username, password, role, full_name in DEMO_USERS:
        pw_hash, salt = hash_password(password)
        cur.execute("""
            INSERT INTO users (username, password_hash, salt, role, full_name, active)
            VALUES (%s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (username) DO UPDATE
              SET password_hash = EXCLUDED.password_hash,
                  salt          = EXCLUDED.salt,
                  role          = EXCLUDED.role,
                  full_name     = EXCLUDED.full_name,
                  active        = TRUE
        """, (username, pw_hash, salt, role, full_name))
        print(f"  {username:<22} → {role}")

    conn.commit()
    cur.close()
    conn.close()
    print(f"\n✅ {len(DEMO_USERS)} usuarios demo listos en PostgreSQL ({os.getenv('HR_DB_NAME')})")


if __name__ == "__main__":
    main()
