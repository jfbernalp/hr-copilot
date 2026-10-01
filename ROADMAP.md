# Ruta de Trabajo — HR Copilot
## Dashboard con 4 utilidades: IA Text-to-SQL · KPIs estáticos · Métricas de uso · Login

> Historial: las Fases 0-4 se ejecutaron sobre la Gen 1 (SQLite + dataset IBM HR
> Analytics), culminando en `app/dashboard_praxedes_v3.py` → consolidado como
> `app/dashboard.py`. Esa generación quedó **archivada en `legacy/gen1_sqlite/`**
> (ver su README). La Fase 5 migró todo a PostgreSQL con la empresa sintética
> NovaTech Colombia S.A.S. y nunca se documentó aquí — se cierra retroactivamente
> en esta actualización (30 sept 2026).

---

## Fase 0 — Saneamiento del repo ✅ COMPLETA
*Prerequisito: una sola versión canónica del dashboard.*
- [x] Consolidar en `app/dashboard.py`; archivar versiones previas.
- [x] Procfile apuntando a la versión correcta.
- [x] Eliminar scripts one-off del root.
- [x] `data/kpi_catalog.csv` en UTF-8.
- [x] `.gitignore` saneado.

## Fase 1 — Utilidad 2: Dashboard de KPIs ✅ COMPLETA
- [x] `app/kpi_catalog.py`: catálogo de 44 KPIs, 8 categorías, semáforo, ficha técnica.
- [x] Página `/kpis`, caché por rol, RLS (KPIs salariales bloqueados para roles sin permiso).

## Fase 2 — Utilidad 1: IA Vanna + Gemini ✅ COMPLETA
- [x] RAG dual-mode (ChromaDB / estático).
- [x] `PLOTLY_PROMPT` como árbol de decisión anti-barras-por-defecto.
- [x] `tests/ai_regression.py`: 14 preguntas canónicas.

## Fase 3 — Utilidad 3: Métricas de uso y costo ✅ COMPLETA
- [x] `usage_metrics`: rol, latencia, cache hit/miss, éxito/error, costo.
- [x] Página restringida a `hr_admin`.

## Fase 4 — Utilidad 4: Login con usuarios reales ✅ COMPLETA
- [x] Tabla `users` (pbkdf2), sesión server-side, rate-limit de 5 intentos.
- [x] `rls_audit_log` con `username`.

## Fase 5 — Migración a PostgreSQL + NovaTech Colombia S.A.S. ✅ COMPLETA (retroactiva)
*La Gen 1 (SQLite/IBM HR) validó la arquitectura; esta fase la llevó a un esquema
relacional normalizado, con capa semántica de vistas — el patrón que se replicará
sobre la BD real de Midasoft.*

- [x] `setup/schema_postgres.sql`: 25 tablas normalizadas (sedes, departamentos,
      niveles_cargo, cargos, empleados, historial_cargos, salarios versionados por
      fecha, nomina_mensual, asistencia_mensual, incapacidades, vacaciones,
      saldo_vacaciones, evaluaciones_desempeno, ciclos/respuestas_encuesta,
      programas/participantes_capacitacion, vacantes, historico_headcount, retiros,
      financials_empresa) + **9 vistas semánticas** (capa que Vanna entrena, nunca
      las tablas base — el mismo patrón documentado como objetivo para Midasoft).
- [x] `setup/seed_postgres.py`: datos sintéticos con seed fijo (42) y correlaciones
      reales (satisfacción → eNPS, pre/post capacitación, estacionalidad financiera).
- [x] `setup/train_vanna_postgres.py`: ~56 ejemplos pregunta→SQL en español,
      entrenados solo contra las 9 vistas.
- [x] `app/dashboard.py`, `app/kpi_catalog.py`, `app/auth.py`, `app/rls.py`
      reescritos contra PostgreSQL (psycopg2) y el vocabulario de NovaTech (sedes
      Medellín/Bogotá en vez de departamentos "Sales"/"R&D" de la Gen 1).
- [x] `users`, `query_cache`, `rls_audit_log`, `usage_metrics` recreados en Postgres
      (`CREATE TABLE IF NOT EXISTS` en el arranque — ver `app/dashboard.py` / `app/rls.py`).
- [x] Deploy: `docker-compose.yml` (servicios `hr-db` + `hr-app`), Traefik con TLS
      automático en `hr.jfbernalp.dev`, contenedores vivos en Hetzner.
- [x] `requirements-full.txt` para el build de Docker.
- [x] Smoke test: `tests/ai_regression.py` corrido contra el pipeline completo en
      vivo — 14/14 SQL ejecutable, 0 violaciones de paleta (ver resultado más abajo).
- [x] `README.md`/`ROADMAP.md`/`CLAUDE.md` actualizados a la arquitectura real
      (este commit — llevaban desde el deploy sin reflejar la migración).

## Fase 6 — Hallazgos de la auditoría del 30 sept 2026 y correcciones aplicadas
- [x] **Bug corregido**: `_generate_chart_code()` en `app/dashboard.py` llamaba a
      `genai.types.*` sin tener `genai` importado en su scope — cada pregunta caía
      silenciosamente al heurístico `smart_chart` en vez de usar el gráfico que
      recomienda Gemini. Se agregó el import a nivel de módulo.
- [x] Archivada la Gen 1 (SQLite) completa bajo `legacy/gen1_sqlite/`.
- [x] Corregidos docstrings desactualizados en `kpi_catalog.py` y `ai_regression.py`
      (mencionaban la BD SQLite de la Gen 1).
- [x] Spot-check de realismo de datos: 0 traslapes de fechas en `historial_cargos`,
      0 salarios fuera de banda vs `niveles_cargo` (608 registros, 175 vigentes).
- [ ] **Pendiente, no bloqueante**: verificar con Juan si `gemini-3.6-flash` (usado
      en `app/dashboard.py` y `train_vanna_postgres.py`) es el modelo correcto/más
      reciente disponible al momento de leer esto — no se modificó porque es
      consistente en todo el código activo (no es un typo aislado).
- [ ] Pendiente: decidir si vale la pena portar alguno de los ~59 ejemplos
      pregunta→SQL de la Gen 1 que no tengan equivalente entre los ~56 de NovaTech.

---

## Resultado de regresión más reciente (30 sept 2026, post-fix del bug de gráficos)

```
SQL ejecutable: 14/14 | Gráfico correcto: ver corrida post-redeploy | Violaciones de paleta: 0
```

## Decisión clave tomada (Gen 1, sigue vigente como principio)
**Datos sintéticos sí, pero coherentes**: tanto en IBM HR (Gen 1) como en NovaTech
(Gen 2) se prefirió generar datos sintéticos con seed reproducible y correlaciones
reales antes que limitar el dashboard a datos pobres o puramente aleatorios.
