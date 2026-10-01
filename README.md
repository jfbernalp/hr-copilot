# HR Copilot — NovaTech Colombia S.A.S. 🚀
### Práxedes S.A.S. — prototipo de People Analytics con IA Text-to-SQL

**HR Copilot** es una plataforma de IA Generativa que permite a los líderes de RR.HH.
consultar los datos de su equipo en lenguaje natural (ej. *"¿cuál es la rotación de
personal en Bogotá este año?"*) y recibir SQL, datos y gráficos interactivos al instante.

Este repo contiene el **único proyecto activo**: una empresa sintética, **NovaTech
Colombia S.A.S.** (Data Center / Cloud Storage, sedes Medellín y Bogotá, 175 empleados),
corriendo sobre **PostgreSQL**, construida para ensayar la arquitectura real antes de
conectarla a la BD de Midasoft. La primera versión del laboratorio (SQLite, dataset
público IBM HR Analytics) quedó archivada como referencia en
[`legacy/gen1_sqlite/`](legacy/gen1_sqlite/README.md).

## 🌟 Las 4 utilidades del dashboard

1. **💬 Chat IA Text-to-SQL** — Vanna + Gemini, RAG contra **9 vistas semánticas**
   (`v_perfil_empleado`, `v_nomina_mensual`, `v_asistencia_mensual`,
   `v_rotacion_retiros`, `v_headcount_historico`, `v_evaluaciones_desempeno`,
   `v_vacantes_reclutamiento`, `v_engagement_encuestas`, `v_capacitaciones`), nunca
   contra tablas base. ChromaDB local (`USE_CHROMA=1`) con fallback a modo estático
   si no está disponible.
2. **📊 Dashboard de KPIs** (`/kpis`) — catálogo de 44 KPIs de People Analytics en
   8 categorías (estructura, rotación, desarrollo, clima, eficiencia, nómina,
   horarios, vacantes), con semáforo y ficha técnica por indicador.
3. **📈 Métricas de uso** — costo, tokens, latencia y tasa de caché por consulta,
   restringido a `hr_admin`.
4. **🔐 Login** — usuarios reales en PostgreSQL (pbkdf2), sesión server-side, 5
   intentos fallidos bloquean la cuenta.
5. **🛡️ RLS** — filtra por sede (Medellín/Bogotá) y bloquea columnas salariales
   según el rol (`app/rls.py`), con bitácora en `rls_audit_log`.

## 🛠️ Tecnologías

* **Backend:** Python, Flask, Dash, Gunicorn
* **IA:** Google Gemini, Vanna AI (RAG), ChromaDB
* **Base de datos:** PostgreSQL 16
* **Visualización:** Plotly (paleta Manual Web Práxedes)
* **Deploy:** Docker + Docker Compose, Traefik (TLS automático) — servidor Hetzner,
  **hr.jfbernalp.dev**

## 🚀 Instalación y uso local

```bash
git clone https://github.com/jfbernalp/hr-copilot.git
cd hr-copilot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-full.txt
```

Variables en `.env` (ver `.env.example`): `GEMINI_API_KEY`, `HR_DB_*`,
`SECRET_KEY`, `CHROMA_DIR`, `USE_CHROMA`.

```bash
# 1. Esquema + datos sintéticos de NovaTech
psql -h $HR_DB_HOST -U $HR_DB_USER -d $HR_DB_NAME -f setup/schema_postgres.sql
python setup/seed_postgres.py
python setup/seed_users.py

# 2. Entrenar ChromaDB (opcional pero recomendado)
python setup/train_vanna_postgres.py

# 3. Levantar el dashboard
python app/dashboard.py   # → http://127.0.0.1:8051
```

## 🐳 Deploy con Docker (como corre en producción)

```bash
docker compose build
docker compose up -d
```

`entrypoint.sh` espera a Postgres, siembra el esquema/datos/usuarios si la BD
está vacía, entrena ChromaDB si el volumen está vacío, y arranca Gunicorn. Dos
servicios: `hr-db` (Postgres 16) y `hr-app` (Dash), expuesto vía Traefik en
`${HR_DOMAIN}`.

## 👤 Usuarios demo

| Usuario | Contraseña | Rol | Alcance |
|---|---|---|---|
| `admin` | `Praxedes2026!` | hr_admin | Todo: ambas sedes, salarios, métricas de uso |
| `gerente.medellin` | `Medellin2026!` | gerente_medellin | Solo sede Medellín, ve salarios |
| `lider.bogota` | `Bogota2026!` | lider_bogota | Solo sede Bogotá, sin salarios |
| `viewer` | `Viewer2026!` | viewer | Ambas sedes, sin salarios |

5 intentos fallidos bloquean la cuenta por 5 minutos (`app/auth.py`).

## 🧪 Tests

```bash
docker exec hr-copilot-hr-app-1 python tests/ai_regression.py
```

14 preguntas canónicas contra el pipeline completo (SQL + tipo de gráfico +
paleta Práxedes). Gate: SQL 100% ejecutable, ≥75% de aciertos de familia de
gráfico, 0 violaciones de paleta.

## 📁 Generación 1 (archivada)

El laboratorio original sobre SQLite + dataset IBM HR Analytics vive en
[`legacy/gen1_sqlite/`](legacy/gen1_sqlite/README.md) como referencia histórica.
No es parte del proyecto activo ni se despliega.

---
*Desarrollado por Práxedes S.A.S. para validar la arquitectura de People Analytics
con IA antes de implementarla sobre la base de datos real de Midasoft.*
