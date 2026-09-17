# HR Copilot — Práxedes S.A.S.
## Contexto completo del proyecto para Claude Code

---

## Qué es este proyecto

Dashboard de People Analytics con IA Text-to-SQL. El usuario escribe preguntas en lenguaje natural (español o inglés) y el sistema genera SQL automáticamente, lo ejecuta contra una BD SQLite con datos de IBM HR, y produce gráficos interactivos con Plotly.

Esto es un **laboratorio educativo** para Praxedes S.A.S. que valida la arquitectura Text-to-SQL antes de llevarla a producción en el módulo People Analytics de Midasoft. El patrón de producción equivalente es: Azure OpenAI + Azure SQL + Plotly Dash + Interceptor RLS por empresa/rol.

---

## Stack técnico

| Componente | Tecnología | Versión |
|---|---|---|
| Lenguaje | Python | 3.13 |
| Text-to-SQL | Vanna AI | 0.7+ |
| LLM | Gemini 2.5 Flash | gemini-2.5-flash |
| Vector Store | ChromaDB | local, persistido en disco |
| Base de datos | SQLite | hr_analytics.db |
| Visualización | Plotly + Dash | puerto 8051 |
| Editor | VSCode | macOS Apple Silicon |
| API Key | GEMINI_API_KEY | en .env |

---

## Arquitectura del sistema

### Cómo funciona el pipeline completo

```
Usuario escribe pregunta
        ↓
Dashboard Dash (dashboard_praxedes.py)
        ↓
vn.generate_sql(question)  ←── Vanna orquesta
        ↓
ChromaDB RAG               ←── recupera 3-6 fragmentos más similares
        ↓                       (DDL + docs + ejemplos SQL + ejemplos Plotly)
Gemini 2.5 Flash           ←── LLM que ESCRIBE el SQL (Vanna NO escribe SQL)
        ↓
SQL generado por Gemini
        ↓
run_sql_seguro(sql)        ←── Interceptor RLS (rls.py)
        ↓
SQLite ejecuta SQL filtrado
        ↓
DataFrame (pandas)
        ↓
generate_plotly_code()     ←── segunda llamada a Gemini para el gráfico
        ↓
Gráfico renderizado en Dash
```

### Roles en el sistema

- **Vanna**: coordinador. Busca fragmentos relevantes en ChromaDB, arma el prompt, llama a Gemini, devuelve el resultado. No escribe SQL por sí solo.
- **ChromaDB**: bodega vectorial. Guarda DDL, documentación, ejemplos SQL y ejemplos Plotly. El RAG selecciona solo los K más cercanos al prompt — NO manda todo.
- **Gemini 2.5 Flash**: el LLM. Recibe el prompt armado por Vanna y escribe el SQL. También genera el código Plotly en una segunda llamada.
- **SQLite**: ejecuta el SQL y devuelve los datos.
- **Interceptor RLS (rls.py)**: código Python propio (no es librería). Se sienta entre Vanna y SQLite. Modifica el SQL según el rol del usuario (filtros de filas, bloqueo de columnas).

---

## Estructura de archivos

```
hr-analytics-ai/              ← root del proyecto
├── app/
│   ├── dashboard_praxedes.py ← dashboard principal, puerto 8051
│   └── rls.py                ← interceptor RLS (pendiente crear)
├── setup/
│   ├── train_vanna.py        ← entrena ChromaDB con DDL + docs + ejemplos
│   └── build_database.py     ← construye hr_analytics.db desde el CSV
├── data/
│   ├── hr_analytics.db       ← SQLite con datos IBM HR (1,470 empleados)
│   └── WA_Fn-UseC_-HR-Employee-Attrition.csv  ← CSV fuente IBM
├── chroma_db/                ← generado por train_vanna.py (no subir a git)
├── .venv/                    ← entorno virtual Python
├── .env                      ← GEMINI_API_KEY=... (nunca subir a git)
├── requirements.txt
├── dashboard_v0.01.py        ← versión histórica (tema oscuro, archivo)
└── CLAUDE.md                 ← este archivo
```

### Rutas absolutas en macOS

```
Proyecto:   /Users/jfbernalp/Documents/hr-analytics-ai/
BD:         /Users/jfbernalp/Documents/hr-analytics-ai/data/hr_analytics.db
ChromaDB:   /Users/jfbernalp/Documents/hr-analytics-ai/chroma_db/
Dashboard:  /Users/jfbernalp/Documents/hr-analytics-ai/app/dashboard_praxedes.py
Train:      /Users/jfbernalp/Documents/hr-analytics-ai/setup/train_vanna.py
RLS:        /Users/jfbernalp/Documents/hr-analytics-ai/app/rls.py
```

### Nota crítica sobre ChromaDB y rutas

El `chroma_persist_directory` **siempre debe ser ruta absoluta**. Con rutas relativas
(`../chroma_db`, `./chroma_db`) ChromaDB resuelve diferente según desde dónde se ejecuta
el script, y el dashboard carga un ChromaDB vacío aunque el entrenamiento haya funcionado.

Patrón correcto en cualquier archivo Python del proyecto:

```python
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
CHROMA_DIR = os.path.join(BASE_DIR, "chroma_db")
DB_PATH    = os.path.join(BASE_DIR, "data", "hr_analytics.db")
```

---

## Base de datos: hr_analytics.db

Datos IBM HR — 1,470 empleados. **4 tablas núcleo** (abajo) + **14 tablas sintéticas**
generadas por `setup/build_synthetic_data.py` (ver sección "Tablas sintéticas"). No
inventar tablas fuera de esas 18.

```sql
CREATE TABLE departments (
    department_id   INTEGER PRIMARY KEY,
    department_name TEXT    -- 'Sales', 'Research & Development', 'Human Resources'
);

CREATE TABLE job_roles (
    role_id   INTEGER PRIMARY KEY,
    role_name TEXT    -- 'Sales Executive', 'Research Scientist', 'Manager', etc.
);

CREATE TABLE employees (
    employee_id             INTEGER PRIMARY KEY,
    Age                     INTEGER,
    Gender                  TEXT,    -- 'Male' or 'Female'
    MaritalStatus           TEXT,    -- 'Single', 'Married', 'Divorced'
    Education               INTEGER, -- 1=Below College 2=College 3=Bachelor 4=Master 5=Doctor
    EducationField          TEXT,    -- 'Life Sciences', 'Medical', 'Marketing', etc.
    NumCompaniesWorked      INTEGER,
    TotalWorkingYears       INTEGER,
    YearsAtCompany          INTEGER,
    YearsInCurrentRole      INTEGER,
    YearsSinceLastPromotion INTEGER,
    YearsWithCurrManager    INTEGER,
    JobLevel                INTEGER, -- 1=entry to 5=executive
    MonthlyIncome           INTEGER, -- USD
    DailyRate               INTEGER,
    HourlyRate              INTEGER,
    MonthlyRate             INTEGER,
    PercentSalaryHike       INTEGER,
    StockOptionLevel        INTEGER, -- 0 to 3
    BusinessTravel          TEXT,    -- 'Non-Travel', 'Travel_Rarely', 'Travel_Frequently'
    OverTime                TEXT,    -- 'Yes' or 'No'
    Attrition               TEXT,    -- 'Yes'=left company, 'No'=still employed
    DistanceFromHome        INTEGER,
    TrainingTimesLastYear   INTEGER,
    department_id           INTEGER REFERENCES departments(department_id),
    role_id                 INTEGER REFERENCES job_roles(role_id)
);

CREATE TABLE satisfaction (
    employee_id              INTEGER PRIMARY KEY REFERENCES employees(employee_id),
    JobSatisfaction          INTEGER, -- 1=Low 2=Medium 3=High 4=Very High
    EnvironmentSatisfaction  INTEGER, -- 1=Low 2=Medium 3=High 4=Very High
    RelationshipSatisfaction INTEGER, -- 1=Low 2=Medium 3=High 4=Very High
    WorkLifeBalance          INTEGER, -- 1=Bad 2=Good 3=Better 4=Best
    JobInvolvement           INTEGER, -- 1=Low 2=Medium 3=High 4=Very High
    PerformanceRating        INTEGER  -- 3=Excellent, 4=Outstanding (no 1 or 2)
);
```

### Hechos clave sobre los datos

- Attrition = 'Yes' → empleado SE FUE. Attrition = 'No' → sigue activo.
- PerformanceRating: solo valores 3 y 4 en este dataset (no hay 1 ni 2).
- 3 departamentos: 'Sales', 'Research & Development', 'Human Resources'.
- Todos los salarios en USD.
- JOIN siempre con alias: `employees e`, `departments d`, `job_roles jr`, `satisfaction s`.

### Tablas sintéticas (para el dashboard de KPIs del catálogo kpi_catalog.csv)

Generadas con seed fija (42) por `setup/build_synthetic_data.py` — re-correr ese script
las regenera idénticas. Ventana temporal: **2024-06 a 2026-05** (24 meses). Coherencia:
cada empleado tiene `hire_date`/`exit_date` en `employment_dates` (los Attrition='Yes'
salen dentro de la ventana) y asistencia/nómina solo existen en sus meses activos.

| Tabla | Grano | Columnas clave | KPIs que habilita |
|---|---|---|---|
| `employment_dates` | empleado | hire_date, exit_date, exit_type | antigüedad, rotación |
| `attendance_monthly` | empleado×mes | scheduled_days, absence_days, regular_hours, overtime_hours, late_arrivals | ausentismo, overtime rate, puntualidad |
| `medical_leaves` | incapacidad | start_date, days, leave_type (EPS/ARL) | incapacidades, tasa de incidentes |
| `payroll_monthly` | empleado×mes | base_salary, benefits, employer_contributions, overtime_pay, total_cost | costo por FTE, índice horas extra, incremento salarial |
| `payroll_runs` | mes | scheduled/actual_pay_date, payslips_with_errors | puntualidad de pago, error rate |
| `salary_bands` | job_level | band_min/mid/max | compa-ratio |
| `headcount_history` | mes×depto | headcount, hires, exits_voluntary/involuntary | headcount trend, turnover, hiring rate |
| `vacancies` | vacante | opened/closed_date, monthly_salary, offers_extended/accepted, filled_by, quality_of_hire | time to fill, cost of vacancy, offer acceptance, promoción interna |
| `survey_cycles` + `survey_responses` | ciclo trimestral / respuesta | invited; q_pride, q_recommend_nps (0-10), q_effort, q_stay, q_satisfaction | engagement, eNPS, participación |
| `training_programs` + `training_participants` | programa / participante | perf_score_pre/post, cost_usd | efectividad de capacitación |
| `company_financials` | mes | operating_revenue | labor cost ratio, revenue per labor cost |
| `vacation_balances` | empleado activo | accrued/taken/pending_days | vacation liability |

---

## Clase HRCopilot (Vanna + Gemini)

La clase es idéntica en `train_vanna.py` y en `dashboard_praxedes.py`. Si se modifica en uno, sincronizar en el otro:

```python
import google.genai as genai
from vanna.legacy.chromadb.chromadb_vector import ChromaDB_VectorStore
from vanna.legacy.base.base import VannaBase

class HRCopilot(ChromaDB_VectorStore, VannaBase):
    def __init__(self, config=None):
        ChromaDB_VectorStore.__init__(self, config=config)
        VannaBase.__init__(self, config=config)
        self._client    = genai.Client(api_key=config.get("api_key"))
        self.model_name = config.get("model", "gemini-2.5-flash")
        self.last_input_tokens = self.last_output_tokens = self.last_total_tokens = 0

    def system_message(self, message): return message
    def user_message(self, message):   return message
    def assistant_message(self, message): return message

    def submit_prompt(self, prompt, **kwargs):
        text = (
            "\n".join([p if isinstance(p, str) else str(p) for p in prompt])
            if isinstance(prompt, list) else str(prompt)
        )
        text += (
            "\n\nIMPORTANT: The database has exactly 4 tables: "
            "employees, departments, job_roles, satisfaction. "
            "Always use lowercase table names. Never invent table names."
        )
        response = self._client.models.generate_content(
            model=self.model_name,
            contents=text,
            config=genai.types.GenerateContentConfig(
                thinking_config=genai.types.ThinkingConfig(thinking_budget=0)
            )
        )
        try:
            self.last_input_tokens  = response.usage_metadata.prompt_token_count
            self.last_output_tokens = response.usage_metadata.candidates_token_count
            self.last_total_tokens  = response.usage_metadata.total_token_count
        except Exception:
            pass
        return response.text
```

### Inicialización (igual en ambos archivos)

```python
# IMPORTANTE: usar sqlite3.connect() directo, NO vn.connect_to_sqlite()
# connect_to_sqlite falla con rutas absolutas en macOS
vn = HRCopilot(config={
    "api_key":                  os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
    "model":                    "gemini-2.5-flash",
    "chroma_persist_directory": CHROMA_DIR,  # siempre ruta absoluta
})
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
vn.run_sql = lambda sql: pd.read_sql_query(sql, conn)
vn.run_sql_is_set = True
```

---

## Interceptor RLS (rls.py)

**RLS no es una librería pip.** Es código Python propio en `rls.py` (en el root del proyecto). No hay `pip install rls`.

Arquitectura: se reemplaza `vn.run_sql` con una función que llama al interceptor antes de ejecutar en SQLite.

```python
# En dashboard_praxedes.py — así se conecta rls.py:
from rls import rls_intercept, ROLES   # rls.py está en el mismo directorio

def run_sql_seguro(sql: str) -> pd.DataFrame:
    rol = get_current_role()                  # devuelve string como "hr_admin"
    sql_filtrado = rls_intercept(sql, rol)    # modifica el SQL según el rol
    return pd.read_sql_query(sql_filtrado, conn)

vn.run_sql = run_sql_seguro
vn.run_sql_is_set = True
```

### Roles definidos

```python
ROLES = {
    "hr_admin":        {"dept_filter": None, "can_see_salary": True,  "blocked_cols": []},
    "sales_manager":   {"dept_filter": 1,    "can_see_salary": True,  "blocked_cols": []},
    "rd_manager":      {"dept_filter": 2,    "can_see_salary": True,  "blocked_cols": []},
    "employee_viewer": {"dept_filter": None, "can_see_salary": False, "blocked_cols": ["MonthlyIncome","DailyRate","HourlyRate","MonthlyRate"]},
}
```

### Qué hace el interceptor

1. Verifica que el rol exista
2. Bloquea acceso si la query toca columnas de salario y el rol no tiene permiso (lanza `PermissionError`)
3. Inyecta `WHERE e.department_id = X` si el rol tiene `dept_filter`
4. Registra en tabla `rls_audit_log` (se crea automáticamente en la BD)

---

## Paleta de colores — Manual Web Práxedes

**Todos los gráficos DEBEN usar solo estos colores:**

```python
# Paleta oficial Práxedes S.A.S. (Manual Web)
PRAXEDES_ORANGE    = '#ff8b00'   # naranja principal — barras primarias, títulos
PRAXEDES_DARK_GRAY = '#383838'   # gris oscuro — texto, barras secundarias
PRAXEDES_LIGHT_GRAY= '#dddddd'   # gris claro — fondos, referencias neutrales
PRAXEDES_WHITE     = '#ffffff'   # blanco — fondos de contenedores

# Colores semánticos para datos HR (derivados de la paleta base)
COLOR_FEMALE    = '#ff8b00'   # naranja Práxedes — género femenino
COLOR_MALE      = '#5b8db8'   # azul acero — género masculino
COLOR_ATTRITION_YES = '#c0392b'  # rojo profundo — empleados que se fueron
COLOR_ATTRITION_NO  = '#383838'  # gris oscuro — empleados activos/estables
COLOR_OVERTIME_YES  = '#ff8b00'  # naranja — estado de alerta
COLOR_OVERTIME_NO   = '#dddddd'  # gris claro — estado normal

# Secuencia para gráficos con múltiples series (en este orden)
COLORWAY = ['#ff8b00', '#383838', '#5b8db8', '#e67e22', '#dddddd', '#c0392b']

# NUNCA usar: verde (#43a047), morado (#9c27b0), azul Bootstrap (#1e88e5),
#             rojo Material (#e53935), o cualquier color no listado arriba.
```

---

## Generación de gráficos

El sistema usa **dos capas** para generar gráficos:

### Capa 1 (principal): generate_plotly_code() → Gemini

Gemini ha sido entrenado en ChromaDB con:
- `VISUALIZATION_DOCUMENTATION`: 10 reglas de qué tipo de gráfico usar según la semántica de la pregunta y la estructura del DataFrame.
- `PLOTLY_EXAMPLES`: 16 ejemplos concretos de (pregunta + SQL) → código Plotly correcto con colores Práxedes.

La llamada pasa contexto rico al LLM:

```python
df_sample      = df.head(5).to_string(index=False)
df_cardinality = {col: int(df[col].nunique()) for col in df.select_dtypes(include=["object","category"]).columns}
rich_metadata  = f"dtypes:\n{df.dtypes}\n\nshape: {df.shape[0]} rows\n\nsample:\n{df_sample}\n\ncardinalidad: {df_cardinality}"

plotly_code = vn.generate_plotly_code(question=question, sql=sql, df_metadata=rich_metadata)
fig = vn.get_plotly_figure(plotly_code=plotly_code, df=df)
```

### Capa 2 (fallback): smart_chart()

Solo se usa si Gemini lanza excepción. Reglas Python locales que replican la lógica de VISUALIZATION_DOCUMENTATION.

### Tema visual aplicado siempre (después de cualquier capa)

```python
fig.update_layout(
    paper_bgcolor='#ffffff',
    plot_bgcolor='#f5f5f5',
    font=dict(color='#383838', family="'Montserrat', sans-serif", size=11),
)
```

---

## Errores conocidos y sus soluciones

| Error | Causa | Solución |
|---|---|---|
| `connect_to_sqlite` falla con ruta absoluta en macOS | Bug de Vanna en macOS ARM | Usar `sqlite3.connect()` directo y asignar `vn.run_sql` manualmente |
| ChromaDB vacío al arrancar el dashboard | El dashboard usa ruta diferente al del entrenamiento | Siempre usar `os.path.abspath(__file__)` para construir `CHROMA_DIR`. Nunca `../chroma_db` |
| SQL genera tabla `comments` en vez de `comentarios` | Gemini confunde nombres de tablas | El `submit_prompt` tiene un REMINDER que fuerza los nombres correctos |
| `vanna[google]` falla en zsh | El shell interpreta los corchetes | Usar comillas: `pip install 'vanna[google]'` |
| `gemini-1.5-flash not found` | Modelo deprecado | Usar `gemini-2.5-flash` |
| Rate limit 429 de Google | Billing no activado | Activar billing en Google Cloud Console con límite $15 USD |
| `nbformat` error en Plotly | Versión desactualizada | `pip install 'nbformat>=4.2.0'` |
| `PermissionError` en dashboard | RLS bloqueó la query | Mensaje esperado — mostrar al usuario, no es bug |

---

## Comandos para correr el proyecto

```bash
# Activar entorno virtual (siempre primero)
source .venv/bin/activate

# Instalar dependencias (solo la primera vez o si cambia requirements.txt)
pip install vanna 'vanna[google]' google-genai chromadb plotly dash pandas python-dotenv

# Entrenar Vanna (correr cuando se modifica train_vanna.py o se resetea chroma_db/)
python setup/train_vanna.py

# Correr el dashboard
python app/dashboard_praxedes.py
# → abre http://127.0.0.1:8051 en el navegador

# Verificar que ChromaDB tiene datos entrenados
python -c "
from vanna.legacy.chromadb.chromadb_vector import ChromaDB_VectorStore
from vanna.legacy.base.base import VannaBase
import os
class V(ChromaDB_VectorStore, VannaBase):
    def __init__(self, config=None):
        ChromaDB_VectorStore.__init__(self, config=config)
        VannaBase.__init__(self, config=config)
    def system_message(self, m): return m
    def user_message(self, m): return m
    def assistant_message(self, m): return m
    def submit_prompt(self, p, **kw): return ''
v = V(config={'chroma_persist_directory': os.path.abspath('chroma_db')})
df = v.get_training_data()
print(f'Fragmentos en ChromaDB: {len(df)}')
"
```

---

## Estado actual del proyecto

- [x] Base de datos SQLite funcionando (`hr_analytics.db`)
- [x] Vanna + Gemini 2.5 Flash integrado
- [x] ChromaDB entrenado con DDL + documentación + ejemplos SQL + ejemplos Plotly
- [x] Dashboard Dash funcional en puerto 8051
- [x] Paleta de colores Práxedes aplicada en entrenamiento y dashboard
- [x] Interceptor RLS (`app/rls.py`): filtro de depto según el grano de cada tabla + bloqueo salarial extendido a nómina sintética; auditoría con username
- [x] Login real: `app/auth.py` (pbkdf2 stdlib + rate-limit 5 intentos/5 min) + tabla `users` (`setup/seed_users.py`) + sesión server-side Flask (`SECRET_KEY` en .env). Usuarios demo: admin / sales.manager / rd.manager / viewer (contraseñas en setup/seed_users.py)
- [x] Página /metrics: tokens, costo, proyección mensual, latencia, tasa de caché, por rol — solo hr_admin
- [x] Dashboard estático /kpis: 44 KPIs del catálogo en 9 hojas (Resumen + 8 categorías) con segmentadores
- [ ] Caché de consultas mejorado (nivel 3 persistente con TTL)
- [ ] Conectar BD más compleja (AdventureWorks o similar multi-tabla)

---

## Próximas tareas priorizadas

1. **Integrar rls.py completamente** en el dashboard con selector de rol en la UI (para el laboratorio, sin auth real)
2. **Mejorar la selección de tipo de gráfico** — revisar casos donde Gemini aún elige barras cuando debería usar línea o dona
3. **Caché de consultas nivel 3** — persistir en SQLite consultas frecuentes con TTL configurable
4. **Tests de regresión de gráficos** — script que corre las 16 preguntas de PLOTLY_EXAMPLES y verifica que los colores y tipos sean correctos
5. **Conectar AdventureWorks LT** — BD multi-tabla para demostrar joins más complejos

---

## Convenciones de código

- Todos los comentarios de sección usan `# ── Nombre ──` con guiones
- Los imports de `rls.py` van al inicio de `dashboard_praxedes.py`, junto a los demás imports
- `CHROMA_DIR` y `DB_PATH` siempre se construyen con `os.path.join` y `os.path.abspath` — nunca strings hardcodeados ni rutas relativas
- `thinking_budget=0` siempre activo para Gemini (reduce costo ~6x sin pérdida de calidad en SQL)
- El dashboard siempre corre en puerto **8051** (no 8050, ese es el default de Dash y puede chocar con otros proyectos)

---

## Contexto de negocio

Este laboratorio es un prototipo educativo para validar la arquitectura Text-to-SQL antes de implementar en el módulo People Analytics de Midasoft (cliente de Praxedes S.A.S.). El patrón que se aprende aquí —Vanna = RAG + LLM + BD— equivale directamente a la arquitectura de producción: Azure OpenAI + Azure SQL + Plotly Dash + Interceptor RLS por empresa/rol.

La empresa: Praxedes S.A.S., empresa colombiana de tecnología HR. Manual de identidad visual: naranja `#ff8b00`, gris oscuro `#383838`, gris claro `#dddddd`, blanco `#ffffff`. Fuente: Montserrat. Bordes redondeados 25px.
