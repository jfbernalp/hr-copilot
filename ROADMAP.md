# Ruta de Trabajo — HR Copilot Práxedes v4
## Dashboard con 4 utilidades: IA Text-to-SQL · KPIs estáticos · Métricas de uso · Login

> Estado de partida (jun 2026): `app/dashboard_praxedes_v3.py` ya contiene las 4 utilidades
> en versión embrionaria. Esta ruta las lleva a versión completa, en 6 fases ordenadas
> por dependencia. Cada fase termina en un estado deployable.

---

## Fase 0 — Saneamiento del repo (½ día) ✅ COMPLETA
*Prerequisito de todo lo demás: una sola versión canónica del dashboard.*

- [x] Consolidar `dashboard_praxedes_v3.py` como versión única → renombrar a `app/dashboard.py`; archivar v1/v2 en `legacy/`.
- [x] Actualizar `Procfile` (hoy apunta a **v2**, el deploy en Render no corre v3).
- [x] Eliminar scripts one-off del root: `rewrite_*.py`, `fix_syntax.py`, `apply_kpis.py`, `refactor_analytics.py`, `generate_pdf.py`, carpetas UUID, `chroma.sqlite3` del root, `app/hr_database.db` (vacío).
- [x] Reparar codificación de `kpi.csv` (era Mac-Roman) → regenerado como `data/kpi_catalog.csv` en UTF-8, relevancia como float, ordenado descendente.
- [x] Revisar `.gitignore`: `chroma_db/`, `*.db-journal`, `.DS_Store`, `__pycache__/`.

## Fase 1 — Utilidad 2: Dashboard estático de KPIs desde kpi.csv (2–3 días)
*La de mayor valor visible. El CSV trae 44 KPIs en 8 categorías con fórmula, gráfico
recomendado y puntaje de relevancia — es la espec del dashboard.*

**1a. Catálogo de KPIs (módulo `app/kpi_catalog.py`) ✅ COMPLETA**
- [x] Parser del CSV → catálogo con categoría, nombre, fórmula, gráfico recomendado, relevancia.
- [x] Registro de 41 funciones de cálculo (decorador `@kpi(indice)`); 3 KPIs marcados sin datos (turnos ×2, skill gap); 12 KPIs salariales bloqueables por RLS.

**1b. Extender la BD con datos sintéticos ✅ COMPLETA**
La BD IBM solo soporta ~12 de los 44 KPIs. `setup/build_synthetic_data.py` (seed 42,
reproducible, con validación automática de 8 KPIs de control) genera 14 tablas coherentes
con los 1.470 empleados, ventana 2024-06 → 2026-05:
- [x] `employment_dates` (hire/exit por empleado — tabla base de coherencia).
- [x] `attendance_monthly` + `medical_leaves` → Ausentismo, Incapacidades EPS/ARL, Overtime Rate, Puntualidad.
- [x] `vacancies` → Time to Fill, Cost of Vacancy, Offer Acceptance, Open Position Rate, Promoción Interna, Quality of Hire.
- [x] `payroll_monthly` + `payroll_runs` + `salary_bands` → Labor Cost per FTE, Compa-Ratio, Incremento Salarial, Payroll Error Rate.
- [x] `headcount_history` → Headcount trend, Turnover Rate, Hiring Rate.
- [x] `survey_cycles` + `survey_responses` → Engagement, eNPS (~0), Participación.
- [x] `training_programs` + `training_participants` → Training Effectiveness.
- [x] `company_financials` + `vacation_balances` → Labor Cost Ratio (~26%), Vacation Liability.
El esquema completo quedó documentado en CLAUDE.md (sección "Tablas sintéticas").

**1c. UI del dashboard estático ✅ COMPLETA**
- [x] Nueva página `/kpis` ("KPIs" en navbar), una sección por categoría (8), KPIs ordenados por relevancia, caché por rol.
- [x] Cada KPI usa el gráfico que recomienda el CSV: combinados barra+línea (headcount, ausentismo, índice OT), heatmaps área×mes (incidentes, incapacidades), scatter con bandas 0.85–1.15 (compa-ratio), Likert apiladas (engagement), dona (promoción interna), barras con benchmark (time to fill 44d, oferta 84%).
- [x] Tarjetas con valor, semáforo (Normal/Alerta/Crítico — sin verde, paleta Práxedes) según umbrales del catálogo.
- [x] Ficha técnica expandible por KPI (descripción, fórmula, visualización recomendada) sin callbacks.
- [x] RLS: filtro de departamento aplicado al contexto de datos; 12 KPIs salariales renderizan bloqueados 🔒 para `employee_viewer`; participación de encuestas recalcula invitados bajo el filtro.

## Fase 2 — Utilidad 1: IA Vanna + Gemini ✅ COMPLETA
*Entrenamiento robusto sobre las 18 tablas + variedad de gráficos (anti-barras).*

- [x] RAG dual-mode: `USE_CHROMA=1` usa ChromaDB local (top-K fragmentos); default estático con todo el corpus en el prompt (apto Render Free). `CHROMA_DIR` → `chroma_db/`.
- [x] Corpus sintético: `DDL_SYNTH` + `SYNTH_DOCUMENTATION` + 15 `SYNTH_EXAMPLES` (ausentismo, vacantes, nómina, eNPS, capacitación); reminder de Gemini actualizado de 4 → 18 tablas.
- [x] `PLOTLY_PROMPT` reescrito como árbol de decisión (T1 series temporales primero → línea/heatmap/eje dual/apiladas; S1 indicador; D1 distribución; P1 dona solo nominales; C1 scatter; barras como último recurso). `smart_chart` fallback reordenado igual.
- [x] RLS extendido a tablas sintéticas: filtro de depto según grano (department_id directo / subquery employee_id / global sin filtro) + bloqueo salarial de `payroll_monthly`/`salary_bands`.
- [x] `tests/ai_regression.py`: 14 preguntas canónicas → 14/14 SQL ejecutable, 14/14 familia de gráfico correcta, 0 violaciones de paleta.

## Fase 3 — Utilidad 3: Métricas de uso y costo ✅ COMPLETA

- [x] `usage_metrics` ampliada: rol, latencia (ms), cache hit/miss, éxito/error. Se registra TODA consulta (incl. cache hits a costo 0 y bloqueos RLS). Tokens del gráfico contabilizados aparte (acumulador `_last_chart_usage` — sin doble conteo).
- [x] Gráficos: costo por día (área), tokens in/out por día (apiladas), consultas por rol (dona), latencia mediana por día (línea).
- [x] Tarjetas: prompts, tokens, costo, proyección mensual (promedio diario × 30), tasa de caché, latencia p50.
- [x] Filtro por rango (7/30/todo) con callback reactivo.
- [x] Página restringida a `hr_admin` (validado contra la sesión, no contra el Store del navegador).

## Fase 4 — Utilidad 4: Login con usuarios reales ✅ COMPLETA

- [x] Tabla `users` (username, password_hash pbkdf2-sha256 stdlib, salt, role, full_name, active).
- [x] `setup/seed_users.py` con 4 usuarios demo (credenciales en README).
- [x] Formulario usuario+contraseña en `layout_login` (mismo diseño de dos paneles; Enter envía).
- [x] Sesión server-side `flask.session` + `SECRET_KEY` en `.env`. El rol se lee SIEMPRE de la sesión: un `dcc.Store` falsificado sin sesión redirige a login (verificado).
- [x] "Salir →" destruye la sesión (ruta `/`). Callbacks de chat/KPIs/métricas validan sesión.
- [x] `rls_audit_log` registra `username` del autenticado.
- [x] Rate-limit: 5 intentos fallidos → bloqueo 5 min (en memoria, `app/auth.py`).

## Fase 5 — Deploy y cierre (½ día)
- [ ] `requirements.txt` actualizado (añadir `passlib[bcrypt]` o `bcrypt`).
- [ ] Procfile → `gunicorn app.dashboard:server`, verificar memoria en Render Free (sin Chroma).
- [ ] Smoke test de las 4 utilidades en producción con los 4 usuarios demo.
- [ ] Actualizar `CLAUDE.md` y `README.md` con la arquitectura final.

---

## Orden y dependencias

```
Fase 0 ──► Fase 1 (KPIs + datos sintéticos)
              │
              ├──► Fase 2 (IA: entrena sobre tablas nuevas)
              │
              └──► Fase 3 (métricas) ──► Fase 4 (login) ──► Fase 5 (deploy)
```

Estimado total: **6–9 días** de trabajo efectivo.

## Decisión clave tomada (revisable)
**Datos sintéticos sí** (Fase 1b): sin ellos solo ~12/44 KPIs del catálogo son calculables.
Al ser un laboratorio educativo para validar la arquitectura antes de Midasoft, generar
datos coherentes con seed reproducible es el camino correcto. Alternativa descartada:
limitar el dashboard al subconjunto IBM (quedaría pobre frente al catálogo de 44 KPIs).
