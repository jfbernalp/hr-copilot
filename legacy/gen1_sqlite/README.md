# Gen 1 — Laboratorio SQLite (archivado)

Esta carpeta conserva la primera generación de HR Copilot: el laboratorio
construido sobre el dataset público IBM HR Analytics (1.470 empleados) en
SQLite. Fue el prototipo que validó la arquitectura completa (Vanna + Gemini +
ChromaDB + RLS + login + catálogo de 44 KPIs) antes de migrar a la segunda
generación.

**El proyecto activo es la Generación 2 — NovaTech Colombia S.A.S. sobre
PostgreSQL**, documentada en el `CLAUDE.md` / `README.md` de la raíz del repo
y desplegada en hr.jfbernalp.dev. Esta carpeta es solo referencia histórica —
no la importa ningún archivo activo en `app/` ni en `setup/` fuera de aquí.

## Contenido
- `data/hr_analytics.db`, `data/WA_Fn-UseC_-HR-Employee-Attrition.csv` — BD SQLite y dataset fuente.
- `setup/train_vanna.py`, `build_database.py`, `build_synthetic_data.py` — scripts de construcción y entrenamiento de esta generación (modelo gemini-2.5-flash, DDL de 18 tablas base, sin capa de vistas semánticas).
- `dashboards/dashboard_v0.01.py`, `dashboard_praxedes_v1.py`, `dashboard_praxedes_v2.py` — versiones sucesivas del dashboard Dash sobre SQLite, previas al `app/dashboard.py` único actual.

## Cómo correrlo (si hace falta revivirlo)
```bash
python legacy/gen1_sqlite/setup/build_database.py
python legacy/gen1_sqlite/setup/build_synthetic_data.py
python legacy/gen1_sqlite/setup/train_vanna.py
python legacy/gen1_sqlite/dashboards/dashboard_praxedes_v2.py
```
Requiere ajustar las rutas relativas (BASE_DIR) si se ejecuta fuera de su
ubicación original en la raíz del repo.
