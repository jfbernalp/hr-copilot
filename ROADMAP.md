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

## Fase 7 — Hardening de seguridad: datos sensibles vs. LLM ✅ COMPLETA (8 oct 2026)
*Disparado por una revisión de estándares de la industria para mandar datos
sensibles a un LLM (Claude/Gemini) sin comprometer la seguridad de los datos
ni la integridad de la BD — el principio: el LLM solo ve metadatos, nunca
datos reales.*

- [x] **Encontrado y corregido** (`f9254b0`): `_generate_chart_code()` en
      `app/dashboard.py` mandaba `df.head(5).to_string()` a Gemini para elegir
      el tipo de gráfico. `v_perfil_empleado` devuelve `nombre_completo` +
      `salario_actual` en la misma fila → preguntas normales ("salario vs años
      en la empresa") mandaban nombres y salarios reales al endpoint de
      Gemini. Se quitó la muestra de filas; el prompt conserva solo `shape`,
      `dtypes` y cardinalidad categórica (agregados).
- [x] Guardia permanente agregada: `tests/test_no_raw_data_leak.py` — DataFrame
      con valores centinela únicos, falla si cualquiera aparece en el prompt
      capturado. Sin costo (no llama a Gemini de verdad).
- [x] Verificado sin regresión: `tests/ai_regression.py` en producción post-
      deploy → 14/14 SQL ejecutable, 12/14 (86%) gráfico correcto, 0
      violaciones de paleta (gate: ≥75%).
- [x] Desplegado: rebuild + redeploy de `hr-copilot-hr-app-1` en Hetzner,
      HTTP 200 confirmado, ChromaDB reentrenado (56/56 ejemplos).
- [x] Convención documentada en `CLAUDE.md` ("Convenciones de código"): ningún
      valor real de celda viaja a un LLM, nunca — cualquier código nuevo que
      arme un prompt con contenido de un DataFrame debe seguir este patrón.

## Fase 8 — Fidelidad de fórmulas de KPI: catálogo vs. chat vs. tablero ✅ COMPLETA (8 oct 2026)
*Disparado por un reporte puntual (el Índice de Burnout no mostraba nada útil en
`/kpis` y el chat fallaba la primera vez que se le preguntaba). El diagnóstico llevó
a una auditoría completa de las 41 KPIs con datos de soporte: no era un problema de
cobertura de entrenamiento (las 41 ya tenían ejemplo `[KPI-N]` y función `@kpi(N)`),
sino de fidelidad — 14 KPIs donde chat y tablero calculaban fórmulas distintas entre
sí o ninguno de los dos implementaba la fórmula real del catálogo.*

- [x] **Auditoría completa**: 22 OK, 5 sospechosos, 14 con discrepancia real, 3 sin
      datos de soporte (sin cambios, ya excluidos desde la Gen 1).
- [x] **Bugs de código corregidos** (KeyError silencioso, atrapado por el
      `try/except` genérico de `_build_items` — por eso las tarjetas "no mostraban
      nada" sin error visible): KPI-60 (`productivity_factor` nunca definido),
      KPI-19/KPI-51 (`vacancy_id`/`job_level` con nombre equivocado), KPI-62
      (`quality_of_hire` hardcodeado a NULL).
- [x] **KPI-18 y KPI-56 removidos** (Payroll Error Rate, Payroll On-Time Rate): gap
      de esquema real, no bug — ninguna tabla de NovaTech registra errores de
      nómina ni fecha programada/real de pago por corrida. Documentado en vez de
      seguir con el stub que fingía 100% puntualidad.
- [x] **Rediseños de score compuesto** (datos reales, pesos del catálogo):
      KPI-43 Burnout (score 0-100 por empleado, antes un % que daba 0.0% siempre
      con los datos reales), KPI-34 Flight Risk y KPI-35 Turnover Cost (chat
      reescrito para igualar la fórmula que el tablero ya tenía correcta — de
      paso se encontró y corrigió el factor de costo por nivel de KPI-35 en el
      tablero, que estaba **invertido**), KPI-1 Engagement y KPI-3 Wellbeing
      (quitado un mapeo falso "esfuerzo discrecional" ← balance vida-trabajo;
      agregada `promedio_relacion_jefe` a `v_engagement_encuestas`, cambio
      aditivo de vista sin tocar datos), KPI-67 Vacation Liability (el tablero
      solo mostraba días, nunca el pasivo monetario).
- [x] Correcciones menores de consistencia: KPI-2, KPI-17, KPI-28, KPI-54.
- [x] KPI-11, KPI-19, KPI-73 documentados como aproximaciones por gaps de
      esquema (sin "plazas autorizadas", sin `empleado_contratado_id` poblado en
      las vacantes sintéticas, sin ingresos por unidad de negocio) — no se
      fabricaron datos para forzar la fórmula literal.
- [x] **Bug de infraestructura encontrado al verificar, no relacionado con
      fórmulas**: `ChromaDB_VectorStore.__init__` (vanna instalado) lee
      `config["path"]`, no `config["chroma_persist_directory"]` — esa clave
      nunca existió para esta versión de la librería, así que ChromaDB nunca
      persistía en `chroma_db/` sino en el directorio de trabajo actual (de ahí
      los archivos sueltos de Chroma que seguían apareciendo en la raíz del
      repo). En producción esto significaba que el volumen `hr_chroma` nunca se
      usaba de verdad — se reentrenaba por completo en cada reinicio del
      contenedor. Corregido en `app/dashboard.py` y `setup/train_vanna_postgres.py`;
      confirmado en Hetzner que ahora persiste en `/app/chroma_db`.
- [x] Verificado: las 39 funciones del tablero ejecutan sin excepción contra
      Postgres local (admin y rol con RLS); los 6 ejemplos de entrenamiento
      reescritos ejecutan correctamente; ChromaDB reentrenado (54/54, 56
      fragmentos); `tests/test_no_raw_data_leak.py` sigue pasando.
- [ ] **Hallazgo separado, pendiente de que Juan revise facturación**: el error
      429 de Gemini reveló `quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier,
      limit: 20` — el proyecto está en el tier gratuito para `gemini-3.6-flash`
      (20 solicitudes/día), no en un plan con facturación activa como se creía.
      Esto limitó la verificación en vivo de hoy (`tests/ai_regression.py` llegó
      a 11/14 antes de agotar la cuota — 9/11 gráfico correcto, 82%, sin
      violaciones de paleta, sin regresión) y explica la falla intermitente
      original del chat al preguntar por Burnout.

---

## Resultado de regresión más reciente (8 oct 2026, post-fix de fidelidad de KPIs)

```
SQL ejecutable: 11/14 (3 fallaron por 429 de cuota, no por el fix) | Gráfico correcto: 9/11 (82%) | Violaciones de paleta: 0
```

## Decisión clave tomada (Gen 1, sigue vigente como principio)
**Datos sintéticos sí, pero coherentes**: tanto en IBM HR (Gen 1) como en NovaTech
(Gen 2) se prefirió generar datos sintéticos con seed reproducible y correlaciones
reales antes que limitar el dashboard a datos pobres o puramente aleatorios.
