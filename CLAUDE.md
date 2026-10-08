# HR Copilot — Práxedes S.A.S.
## Contexto completo del proyecto para Claude Code

> Última sincronización con el servidor: 2026-10-08. Este archivo reemplaza la
> versión anterior, que describía la Generación 1 (SQLite + IBM HR) como
> arquitectura activa — esa generación quedó archivada en `legacy/gen1_sqlite/`.

---

## Qué es este proyecto

Dashboard de People Analytics con IA Text-to-SQL para una empresa sintética,
**NovaTech Colombia S.A.S.** (Data Center / Cloud Storage, sedes Medellín y
Bogotá, 175 empleados). El usuario escribe preguntas en lenguaje natural
(español) y el sistema genera SQL, lo ejecuta contra PostgreSQL, y produce
gráficos interactivos con Plotly.

Es un **laboratorio educativo** para Práxedes S.A.S. que valida la arquitectura
Text-to-SQL antes de llevarla a producción en el módulo People Analytics de
Midasoft. El patrón de producción equivalente es: Azure OpenAI + Azure SQL +
Plotly Dash + Interceptor RLS por empresa/rol.

La Generación 1 (SQLite + dataset público IBM HR Analytics) validó la
arquitectura inicial y quedó archivada como referencia histórica en
[`legacy/gen1_sqlite/`](legacy/gen1_sqlite/README.md). No es parte del proyecto
activo ni se despliega.

---

## Stack técnico

| Componente | Tecnología |
|---|---|
| Lenguaje | Python 3.13 |
| Text-to-SQL | Vanna AI 0.7+ |
| LLM | Gemini (modelo configurable, ver `setup/llm_provider.py`) |
| Vector Store | ChromaDB, persistido en disco (`USE_CHROMA=1`), con fallback estático |
| Base de datos | **PostgreSQL 16** (contenedor `hr-db`) |
| Visualización | Plotly + Dash, puerto 8051 |
| Deploy | Docker + Docker Compose, Traefik (TLS automático), servidor Hetzner — `hr.jfbernalp.dev` |
| API Key | `GEMINI_API_KEY` en `.env` |

---

## Dónde vive el código real

El repo GitHub (`jfbernalp/hr-copilot`) va detrás del servidor: el trabajo se
hace primero en el servidor Hetzner (`juan@2.29.41.159:/home/juan/hr-copilot`,
contenedores `hr-copilot-hr-app-1` / `hr-copilot-hr-db-1`) y desde ahí se
sincroniza a GitHub y a los clones locales. **Antes de asumir que este
directorio local tiene la versión más reciente, compara con el servidor:**

```bash
git remote add hetzner juan@2.29.41.159:/home/juan/hr-copilot   # si no existe aún
git fetch hetzner
git log main..hetzner/main --oneline   # si no está vacío, el servidor va adelante
```

Si el servidor va adelante, hacer `git merge --ff-only hetzner/main` (debería
ser siempre fast-forward: el servidor es la fuente de verdad, no se diverge
localmente). Guardar cualquier cambio local sin commitear con
`git stash push -u` antes de mezclar, y revisar el contenido del stash antes de
descartarlo — puede haber trabajo legítimo mezclado con basura.

---

## Arquitectura del sistema

### Pipeline completo

```
Usuario escribe pregunta
        ↓
Dashboard Dash (app/dashboard.py)
        ↓
vn.generate_sql(question)        ←── Vanna orquesta
        ↓
ChromaDB RAG                     ←── recupera fragmentos más similares
        ↓                             (DDL de las 9 vistas + docs + ejemplos SQL/Plotly)
GeminiProvider.generate()        ←── setup/llm_provider.py — único punto de
        ↓                             configuración del LLM (modelo vía LLM_MODEL)
SQL generado
        ↓
rls_intercept(sql, rol)          ←── interceptor RLS (app/rls.py)
        ↓
PostgreSQL ejecuta SQL filtrado
        ↓
DataFrame (pandas)
        ↓
generate_plotly_code()           ←── segunda llamada a Gemini para el gráfico
        ↓
Gráfico renderizado en Dash
```

### Roles en el sistema

- **Vanna**: coordinador. Busca fragmentos relevantes en ChromaDB, arma el
  prompt, llama al proveedor LLM, devuelve el resultado.
- **ChromaDB**: bodega vectorial con DDL de las 9 vistas semánticas,
  documentación, ejemplos SQL y ejemplos Plotly. RAG top-K, no manda todo el
  corpus salvo en modo estático (fallback).
- **`setup/llm_provider.py` (`GeminiProvider`)**: único punto de llamada real a
  Gemini. Antes el modelo estaba hardcodeado en 4 lugares distintos; ahora es
  una variable de entorno (`LLM_MODEL`) y una sola clase. Reintenta con backoff
  exponencial ante 429/`RESOURCE_EXHAUSTED` (hasta 3 reintentos) y deja log
  detallado en stdout (`docker logs`) de qué cuota de Google se agotó.
- **PostgreSQL**: ejecuta el SQL contra las 9 vistas semánticas (nunca contra
  las 21 tablas base directamente — mismo patrón que se usará con Midasoft).
- **Interceptor RLS (`app/rls.py`)**: código propio, no es librería pip. Se
  sienta entre Vanna y PostgreSQL. Filtra por sede, bloquea columnas
  salariales según el rol, y registra auditoría.

---

## Estructura de archivos

```
hr-analytics-ai/
├── app/
│   ├── dashboard.py        ← dashboard principal, puerto 8051
│   ├── kpi_catalog.py      ← catálogo de 44 KPIs (8 categorías)
│   ├── auth.py             ← login pbkdf2 + rate-limit
│   └── rls.py              ← interceptor RLS (roles, filtro por sede, bloqueo salarial)
├── setup/
│   ├── schema_postgres.sql ← 21 tablas normalizadas + 9 vistas semánticas
│   ├── seed_postgres.py    ← datos sintéticos NovaTech (seed 42, reproducible)
│   ├── seed_users.py       ← 4 usuarios demo
│   ├── train_vanna_postgres.py  ← entrena ChromaDB (clase HRCopilot, ~56 ejemplos ES)
│   └── llm_provider.py     ← único punto de configuración del modelo LLM (GeminiProvider)
├── tests/
│   ├── ai_regression.py    ← 14 preguntas canónicas: SQL ejecutable + tipo de gráfico + paleta
│   └── eval_accuracy.py    ← arnés de precisión: alucinación estructural vs. de contenido,
│                              guarda histórico en tabla eval_runs, nunca usa query_cache
├── legacy/
│   └── gen1_sqlite/        ← Gen 1 archivada (SQLite + IBM HR): dashboards/, data/, setup/
├── data/
│   └── kpi_catalog.csv     ← catálogo fuente de los 44 KPIs (UTF-8)
├── docker-compose.yml      ← servicios hr-db (Postgres 16) + hr-app (Dash), red Traefik
├── Dockerfile / entrypoint.sh  ← espera Postgres, siembra si está vacío, entrena ChromaDB, gunicorn
├── requirements-full.txt   ← dependencias del build de Docker
├── README.md                ← instrucciones de instalación y deploy (fuente de verdad, revisar ahí comandos exactos)
├── ROADMAP.md               ← historial de fases, incluida la migración a Postgres/NovaTech
└── CLAUDE.md                ← este archivo
```

### Nota crítica sobre ChromaDB y rutas

`CHROMA_DIR` **siempre debe ser ruta absoluta** (`os.path.join(BASE_DIR,
"chroma_db")`, nunca `../chroma_db`). Con rutas relativas, el dashboard puede
cargar un ChromaDB vacío aunque el entrenamiento haya funcionado. En Docker,
`CHROMA_DIR=/app/chroma_db` (volumen `hr_chroma`).

---

## Base de datos: PostgreSQL — esquema NovaTech Colombia S.A.S.

21 tablas base normalizadas (`sedes`, `departamentos`, `niveles_cargo`,
`cargos`, `empleados`, `historial_cargos`, `salarios` versionados por fecha,
`nomina_mensual`, `asistencia_mensual`, `incapacidades`, `vacaciones`,
`saldo_vacaciones`, `evaluaciones_desempeno`, `ciclos_encuesta`,
`respuestas_encuesta`, `programas_capacitacion`, `participantes_capacitacion`,
`vacantes`, `historico_headcount`, `retiros`, `financials_empresa`) — ver
`setup/schema_postgres.sql` para las columnas exactas.

**Vanna entrena y consulta solo contra 9 vistas semánticas** (nunca contra las
tablas base — mismo patrón que se replicará con la BD real de Midasoft):

| Vista | Qué expone |
|---|---|
| `v_perfil_empleado` | demografía, cargo, sede, antigüedad |
| `v_nomina_mensual` | salario, beneficios, costo total por empleado×mes |
| `v_asistencia_mensual` | ausentismo, horas extra, puntualidad |
| `v_rotacion_retiros` | retiros voluntarios/involuntarios, antigüedad al salir |
| `v_headcount_historico` | headcount, altas, bajas por mes×sede |
| `v_evaluaciones_desempeno` | ratings y ciclos de evaluación |
| `v_vacantes_reclutamiento` | time to fill, ofertas, calidad de contratación |
| `v_engagement_encuestas` | eNPS, participación, satisfacción |
| `v_capacitaciones` | efectividad de programas de capacitación (pre/post) |

Datos sintéticos generados por `setup/seed_postgres.py` con seed fija (42) y
correlaciones reales (satisfacción → eNPS, pre/post capacitación,
estacionalidad financiera) — re-correr el script los regenera idénticos.

---

## Roles y RLS (`app/rls.py`)

```python
ROLES = {
    "hr_admin":         {"sede_filter": None,       "can_see_salary": True,  "blocked_cols": []},
    "gerente_medellin": {"sede_filter": "Medellín", "can_see_salary": True,  "blocked_cols": []},
    "lider_bogota":     {"sede_filter": "Bogotá",   "can_see_salary": False, "blocked_cols": []},
    "viewer":           {"sede_filter": None,        "can_see_salary": False, "blocked_cols": []},
}
```

Qué hace el interceptor: verifica que el rol exista, bloquea la query si toca
columnas salariales y el rol no tiene permiso (`PermissionError`), inyecta
`WHERE sede = X` si el rol tiene `sede_filter`, y registra en `rls_audit_log`
(con `username`, no solo rol).

### Usuarios demo (`setup/seed_users.py` / `app/auth.py`)

| Usuario | Rol | Alcance |
|---|---|---|
| `admin` | hr_admin | Todo: ambas sedes, salarios, métricas de uso |
| `gerente.medellin` | gerente_medellin | Solo Medellín, ve salarios |
| `lider.bogota` | lider_bogota | Solo Bogotá, sin salarios |
| `viewer` | viewer | Ambas sedes, sin salarios |

Contraseñas exactas en `setup/seed_users.py` / `README.md` (no repetir aquí sin
verificar que no cambiaron). Login: pbkdf2 stdlib, sesión server-side Flask
(`SECRET_KEY` en `.env`), 5 intentos fallidos bloquean la cuenta 5 minutos.

---

## Paleta de colores — Manual Web Práxedes

Sin cambios respecto a la Gen 1 — sigue aplicando en todos los gráficos:

```python
PRAXEDES_ORANGE     = '#ff8b00'
PRAXEDES_DARK_GRAY  = '#383838'
PRAXEDES_LIGHT_GRAY = '#dddddd'
PRAXEDES_WHITE      = '#ffffff'

COLOR_ATTRITION_YES = '#c0392b'
COLOR_ATTRITION_NO  = '#383838'
COLOR_OVERTIME_YES  = '#ff8b00'
COLOR_OVERTIME_NO   = '#dddddd'

COLORWAY = ['#ff8b00', '#383838', '#5b8db8', '#e67e22', '#dddddd', '#c0392b']

# NUNCA usar: verde, morado, azul Bootstrap, rojo Material, o cualquier color no listado.
```

`tests/ai_regression.py` verifica 0 violaciones de paleta como parte del gate
de regresión.

---

## Tests

- **`tests/ai_regression.py`** — smoke test rápido: 14 preguntas canónicas →
  SQL ejecutable + familia de gráfico correcta + paleta Práxedes. Puede
  devolver resultados de `query_cache` (bueno para humo, no para medir
  precisión real). Correr dentro del contenedor:
  `docker exec hr-copilot-hr-app-1 python tests/ai_regression.py`.
- **`tests/eval_accuracy.py`** — arnés de precisión y alucinaciones. Separa
  **alucinación estructural** (el SQL no ejecuta — tabla/columna inexistente)
  de **alucinación de contenido** (el SQL ejecuta pero el valor no coincide
  con una consulta de referencia escrita a mano). Nunca usa `query_cache` —
  cada caso llama a `vn.generate_sql()` de cero. Guarda cada corrida en la
  tabla `eval_runs` para graficar la evolución de precisión en el tiempo.
  `python tests/eval_accuracy.py [--save-json informe.json]`.

---

## Errores conocidos y sus soluciones

| Error | Causa | Solución |
|---|---|---|
| Gráficos caen al heurístico `smart_chart` en vez del tipo que recomienda Gemini | **Bug real, corregido** (commit `bc90173`): `_generate_chart_code()` llamaba a `genai.types.*` sin tener `genai` importado a nivel de módulo en `app/dashboard.py` | Ya corregido — import agregado al inicio del archivo |
| ChromaDB nunca persistía en `chroma_db/` — siempre caía al directorio de trabajo actual (archivos sueltos `chroma.sqlite3` + carpetas UUID en la raíz del repo, o en `/app` dentro del contenedor) | **Bug real, corregido** (commit `948cddc`): `ChromaDB_VectorStore.__init__` del `vanna` instalado lee `config["path"]`, no `config["chroma_persist_directory"]` — esa clave no existe en esta versión de la librería y se ignoraba en silencio | Usar siempre `"path": CHROMA_DIR` en el config de `HRCopilot`/`_StaticCopilot` (`app/dashboard.py`, `setup/train_vanna_postgres.py`) — nunca `"chroma_persist_directory"` |
| `PermissionError` en dashboard | RLS bloqueó la query (rol sin acceso a salarios, o fuera de su sede) | Esperado — mostrar al usuario, no es bug |
| 429 / `RESOURCE_EXHAUSTED` de Gemini, `quotaId: ...FreeTier, limit: 20` | El proyecto Google Cloud está en el **tier gratuito** para `gemini-3.6-flash` (20 solicitudes/día), no en un plan con facturación activa como se creía — confirmado en el mensaje de error del 8 oct 2026. `llm_provider.py` reintenta con backoff, pero no sirve de nada si ya se agotó la cuota diaria completa | **Acción pendiente de Juan**: activar facturación para `gemini-3.6-flash` específicamente en el proyecto de Google Cloud/AI Studio que usa `GOOGLE_API_KEY`/`GEMINI_API_KEY` — revisar que no sea un proyecto distinto al que se verificó como "Nivel 1" |
| `vanna[google]` falla en zsh | El shell interpreta los corchetes | Usar comillas: `pip install 'vanna[google]'` |

**Corregido 2026-10-08** (commit `f9254b0`): `_generate_chart_code()` mandaba
`df.head(5).to_string()` a Gemini para decidir el tipo de gráfico — como
`v_perfil_empleado` devuelve `nombre_completo` + `salario_actual` en la misma
fila, preguntas normales filtraban nombres y salarios reales de empleados al
endpoint de Gemini. Se quitó la muestra de filas; el prompt ahora manda solo
`shape`, `dtypes` y cardinalidad categórica (agregados, nunca valores
individuales). Guardia permanente: `tests/test_no_raw_data_leak.py` (sin
costo, no llama a Gemini) — falla si cualquier valor real de celda aparece en
el prompt capturado. Ver la convención correspondiente más abajo.

**Fidelidad de fórmulas de KPI** (8 oct 2026, commit `948cddc` — ver Fase 8 en
`ROADMAP.md` para el detalle completo): auditoría de las 41 KPIs del catálogo
contra el chat y el tablero encontró 14 con discrepancia real (chat y tablero
calculando cosas distintas, o ninguno igualando la fórmula oficial) y 4 bugs de
código (`KeyError` silencioso, atrapado por el `try/except` genérico de
`_build_items` en `app/kpi_catalog.py` — por eso una tarjeta puede "no mostrar
nada útil" sin lanzar un error visible). Si una KPI del catálogo se ve rara en
el chat o en `/kpis`, antes de asumir que es un caso nuevo, revisar si ya está
en la tabla de auditoría de esa fase.

**Pendiente de verificar** (no bloqueante): confirmar con Juan si
`gemini-3.6-flash` (default en `setup/llm_provider.py`, usado también en
`train_vanna_postgres.py`) sigue siendo el modelo correcto/más reciente
disponible al momento de leer esto. No se ha tratado como typo porque es
consistente en todo el código activo — solo cambiar `LLM_MODEL` en `.env` si
hace falta, no el código.

---

## Comandos para correr el proyecto

### Local (sin Docker)

```bash
source .venv/bin/activate
pip install -r requirements-full.txt

# 1. Esquema + datos sintéticos de NovaTech (requiere Postgres corriendo)
psql -h $HR_DB_HOST -U $HR_DB_USER -d $HR_DB_NAME -f setup/schema_postgres.sql
python setup/seed_postgres.py
python setup/seed_users.py

# 2. Entrenar ChromaDB (opcional pero recomendado)
python setup/train_vanna_postgres.py

# 3. Levantar el dashboard
python app/dashboard.py   # → http://127.0.0.1:8051
```

### Docker (como corre en producción, Hetzner)

```bash
docker compose build
docker compose up -d
```

`entrypoint.sh` espera a que Postgres esté listo, siembra esquema/datos/usuarios
si la tabla `empleados` tiene menos de 100 filas, entrena ChromaDB si el volumen
`hr_chroma` está vacío, y arranca `gunicorn app.dashboard:server` en el puerto
8051 detrás de Traefik.

### Verificar sincronía con el servidor

Ver sección "Dónde vive el código real" arriba.

---

## Convenciones de código

- Comentarios de sección: `# ── Nombre ──`.
- `CHROMA_DIR` y rutas de BD siempre con `os.path.join` + `os.path.abspath` —
  nunca strings hardcodeados ni rutas relativas.
- `thinking_budget=0` siempre activo para Gemini (reduce costo ~6x sin pérdida
  de calidad en SQL) — ver `setup/llm_provider.py`.
- Un solo punto de configuración del modelo LLM: variable de entorno
  `LLM_MODEL`, nunca hardcodear el nombre del modelo en código nuevo.
- El dashboard siempre corre en puerto **8051**.
- Vanna/ChromaDB se entrenan y consultan **solo contra las 9 vistas
  semánticas**, nunca contra las tablas base — si se agrega una tabla nueva,
  agregar también su vista correspondiente antes de entrenar.
- **Ningún valor real de celda viaja a un LLM, nunca** — solo metadatos
  agregados (shape, dtypes, cardinalidad, rangos). Varias vistas devuelven
  PII y salario en la misma fila (`v_perfil_empleado`, `v_nomina_mensual`),
  así que cualquier código nuevo que arme un prompt con contenido de un
  DataFrame (ej. una función de resumen o detección de anomalías) debe
  seguir el patrón de `_generate_chart_code()` en `app/dashboard.py` — nunca
  `df.head()`/`.to_string()`/muestras de filas hacia el LLM. Si se necesita
  "forma" de los datos, usar una fila sintética generada desde los dtypes,
  nunca datos reales. `tests/test_no_raw_data_leak.py` es el guardia de esto.

---

## Contexto de negocio

Laboratorio educativo para validar la arquitectura Text-to-SQL antes de
implementarla en el módulo People Analytics de Midasoft (cliente de Práxedes
S.A.S.). El patrón — Vanna = RAG + LLM + BD relacional con capa semántica de
vistas + Interceptor RLS — equivale directamente a la arquitectura de
producción: Azure OpenAI + Azure SQL + Plotly Dash + RLS por empresa/rol.

Empresa: Práxedes S.A.S., tecnología HR colombiana. Manual de identidad
visual: naranja `#ff8b00`, gris oscuro `#383838`, gris claro `#dddddd`, blanco
`#ffffff`. Fuente: Montserrat. Bordes redondeados 25px.
