"""
train_vanna.py
--------------
Trains Vanna AI on the hr_analytics.db schema and business context.
Stores the training data in ChromaDB (persisted to chroma_db/).

Run once after build_database.py:
    python setup/train_vanna.py

Re-run any time you want to reset or improve the training.
"""

import os
import sys
import sqlite3
import pandas as pd
import google.genai as genai
from dotenv import load_dotenv
from vanna.legacy.base.base import VannaBase

# ChromaDB es OPCIONAL: solo se necesita para entrenar localmente (main()) o para
# correr el dashboard con USE_CHROMA=1. El deploy importa este módulo únicamente
# por el corpus (DDL/DOCUMENTATION/EXAMPLES) y NO debe requerir chromadb.
try:
    from vanna.legacy.chromadb.chromadb_vector import ChromaDB_VectorStore
    CHROMA_AVAILABLE = True
except ImportError:
    class ChromaDB_VectorStore:     # placeholder: la clase nunca se instancia sin chromadb
        def __init__(self, config=None):
            raise RuntimeError("chromadb no está instalado — pip install chromadb")
    CHROMA_AVAILABLE = False

# ── Paths ─────────────────────────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = (
    os.path.dirname(_SCRIPT_DIR)
    if os.path.basename(_SCRIPT_DIR) == "setup"
    else _SCRIPT_DIR
)
DB_PATH    = os.path.join(BASE_DIR, "data", "hr_analytics.db")
CHROMA_DIR = os.path.join(BASE_DIR, "chroma_db")

load_dotenv(os.path.join(BASE_DIR, ".env"))
API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    print(f"ERROR: No API key found in {os.path.join(BASE_DIR, '.env')}")
    print("Expected: GEMINI_API_KEY or GOOGLE_API_KEY")
    print(f"BASE_DIR resolved to: {BASE_DIR}")
    sys.exit(1)


# ── Vanna + Gemini class ──────────────────────────────────────────────────────
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
            "\n\nIMPORTANT: The database has these 18 tables (lowercase): "
            "employees, departments, job_roles, satisfaction (core); "
            "employment_dates, attendance_monthly, medical_leaves, payroll_monthly, "
            "payroll_runs, salary_bands, headcount_history, vacancies, survey_cycles, "
            "survey_responses, training_programs, training_participants, "
            "company_financials, vacation_balances (monthly series 2024-06..2026-05). "
            "Never invent table names. month columns are TEXT 'YYYY-MM'."
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


# ── DDL ───────────────────────────────────────────────────────────────────────
DDL = """
CREATE TABLE departments (
    department_id   INTEGER PRIMARY KEY,
    department_name TEXT    -- e.g. 'Sales', 'Research & Development', 'Human Resources'
);

CREATE TABLE job_roles (
    role_id   INTEGER PRIMARY KEY,
    role_name TEXT    -- e.g. 'Sales Executive', 'Research Scientist', 'Manager'
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
    JobLevel                INTEGER, -- 1 (entry) to 5 (executive)
    MonthlyIncome           INTEGER, -- USD
    DailyRate               INTEGER,
    HourlyRate              INTEGER,
    MonthlyRate             INTEGER,
    PercentSalaryHike       INTEGER,
    StockOptionLevel        INTEGER, -- 0 to 3
    BusinessTravel          TEXT,    -- 'Non-Travel', 'Travel_Rarely', 'Travel_Frequently'
    OverTime                TEXT,    -- 'Yes' or 'No'
    Attrition               TEXT,    -- 'Yes' (left) or 'No' (still employed)
    DistanceFromHome        INTEGER, -- miles
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
    PerformanceRating        INTEGER  -- 1=Low 2=Good 3=Excellent 4=Outstanding
);
"""

# ── Business Documentation ────────────────────────────────────────────────────
DOCUMENTATION = """
The hr_analytics database contains IBM HR data for 1,470 employees.
It is used to answer People Analytics questions about attrition, compensation,
performance, and employee satisfaction.

KEY FACTS:
- Total employees: 1,470
- Attrition = 'Yes' means the employee LEFT the company. Attrition = 'No' means still employed.
- All salary values (MonthlyIncome, DailyRate, HourlyRate) are in USD.
- Education levels: 1=Below College, 2=College, 3=Bachelor, 4=Master, 5=Doctor
- Satisfaction scores (JobSatisfaction, EnvironmentSatisfaction, etc.): 1=Low, 2=Medium, 3=High, 4=Very High
- WorkLifeBalance: 1=Bad, 2=Good, 3=Better, 4=Best
- PerformanceRating: 3=Excellent, 4=Outstanding (no employees rated 1 or 2)
- JobLevel: 1=Entry level, 5=Executive
- StockOptionLevel: 0=None, 1=Low, 2=Medium, 3=High
- BusinessTravel values: 'Non-Travel', 'Travel_Rarely', 'Travel_Frequently'
- The 3 departments are: 'Sales', 'Research & Development', 'Human Resources'

JOINS:
- employees JOIN departments ON employees.department_id = departments.department_id
- employees JOIN job_roles   ON employees.role_id = job_roles.role_id
- employees JOIN satisfaction ON employees.employee_id = satisfaction.employee_id
"""

KPI_DOCUMENTATION = """
PEOPLE ANALYTICS KPI CATALOG
This system is designed to answer questions about the following KPI categories.
Each KPI maps to specific columns in the database.

COLUMN-TO-KPI MAPPING:
  Attrition           -> Turnover Rate, Flight Risk, Turnover Cost
  YearsAtCompany      -> Tenure distribution, Flight Risk (short tenure = higher risk)
  OverTime            -> Overtime Rate, Burnout Risk, Overtime Index
  MonthlyIncome       -> Average Salary, Compa-Ratio, Labor Cost per FTE
  PerformanceRating   -> Performance Score, Training Effectiveness, Burnout (score drop)
  JobSatisfaction     -> Employee Engagement Index, Wellbeing Index, eNPS/ESI
  WorkLifeBalance     -> Wellbeing Index, Burnout Risk
  EnvironmentSatisfaction -> Wellbeing Index, Engagement
  Department          -> Any KPI segmented by area/department
  JobRole             -> Salary by role, Performance by role, Attrition by role
  Age / Gender / MaritalStatus -> Demographic Distribution, Gender Pay Ratio
  TrainingTimesLastYear -> Training Effectiveness, Skill Gap
  YearsSinceLastPromotion -> Internal Promotion Rate, Burnout Risk (stagnation)
  BusinessTravel      -> Burnout Risk, Work-Life Balance analysis
  StockOptionLevel    -> Compensation competitiveness, retention signal
  Education / EducationField -> Demographic diversity, skill profile
  TotalWorkingYears   -> Seniority, experience distribution
  NumCompaniesWorked  -> Flight Risk (high = more likely to leave)
  DistanceFromHome    -> Burnout Risk, absenteeism signal

KPI FORMULAS MAPPED TO SQL:
  - Turnover Rate = COUNT(*) WHERE Attrition='Yes' / COUNT(*) total x 100
  - Overtime Rate = COUNT(*) WHERE OverTime='Yes' / COUNT(*) total x 100
  - Avg Performance Score = AVG(PerformanceRating) -- scale 1-4 in this dataset
  - Engagement proxy = AVG(JobSatisfaction + WorkLifeBalance + EnvironmentSatisfaction + RelationshipSatisfaction) / 4
  - Gender Pay Ratio = AVG(MonthlyIncome) WHERE Gender='Female' / AVG(MonthlyIncome) WHERE Gender='Male'
  - Internal Promotion proxy = employees with YearsSinceLastPromotion = 0 / total x 100
  - Compa-Ratio proxy = employee MonthlyIncome / AVG(MonthlyIncome) of same JobLevel
  - Labor Cost per FTE = SUM(MonthlyIncome) / COUNT(*) by department
  - Flight Risk proxy = employees with (YearsAtCompany <= 2 AND OverTime='Yes') / total x 100
  - Burnout Risk proxy = employees with (OverTime='Yes' AND WorkLifeBalance <= 2 AND PerformanceRating <= 2)
  - Seniority distribution = GROUP BY ranges of YearsAtCompany (0-1, 1-3, 3-5, 5+)
  - Diversity distribution = GROUP BY Gender, Education, MaritalStatus, EducationField

BENCHMARKS TO USE IN ANSWERS (when relevant):
  - Healthy turnover rate: 10-15% annually (LATAM software/services: 18-25%)
  - Overtime red alert: > 10% of workforce consistently
  - Time to fill benchmark: 44 days (SHRM global reference)
  - Offer acceptance benchmark: ~84% (Gem Benchmarks 2024)
  - Survey participation minimum for statistical validity: 70%
  - Compa-ratio equity range: 0.85 to 1.15
  - Flight risk high zone: score > 70/100
  - Burnout risk high zone: score > 70/100
"""

# ── Visualization Rules Documentation ────────────────────────────────────────
# Teaches Gemini chart-type selection AND the exact Práxedes brand palette
# (source: Manual Web Práxedes S.A.S.).
# smart_chart() in the dashboard is only a last-resort fallback.
VISUALIZATION_DOCUMENTATION = """
VISUALIZATION RULES — apply these rules every time you generate Plotly code.
The goal is to select the chart type that best communicates the data semantics
AND always use the Práxedes brand color system defined below.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRÁXEDES BRAND PALETTE — MANDATORY FOR ALL CHARTS
(Source: Manual Web Práxedes S.A.S.)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PRIMARY COLORS (use in this priority order):
  P1  '#ff8b00'   Práxedes Orange   — primary accent, titles, icons, highlights
  P2  '#383838'   Dark Gray         — text, dark bars, strong contrast
  P3  '#dddddd'   Light Gray        — backgrounds, neutral elements, secondary bars
  P4  '#ffffff'   White             — backgrounds and contrast base

SEMANTIC COLORS FOR HR DATA — use ONLY these, never random colors:
  Gender Female     → '#ff8b00'   (Práxedes Orange — warm, primary)
  Gender Male       → '#5b8db8'   (Steel Blue — neutral, professional)
  Attrition Yes     → '#c0392b'   (Deep Red — alert, negative outcome)
  Attrition No      → '#383838'   (Dark Gray — stable, neutral)
  Overtime Yes      → '#ff8b00'   (Orange — high attention)
  Overtime No       → '#dddddd'   (Light Gray — normal state)
  High risk / alert → '#c0392b'   (Deep Red)
  Medium risk       → '#e67e22'   (Amber — derived from orange family)
  Low risk / ok     → '#383838'   (Dark Gray)
  Benchmark line    → '#dddddd'   (Light Gray — reference, unobtrusive)

MULTI-SERIES COLORWAY (when 3+ categories, cycle through in this order):
  1. '#ff8b00'   (Orange)
  2. '#383838'   (Dark Gray)
  3. '#5b8db8'   (Steel Blue)
  4. '#e67e22'   (Amber)
  5. '#dddddd'   (Light Gray)
  6. '#c0392b'   (Deep Red — only if needed as 6th)

NEVER use: random Plotly default colors, purple, green (#43a047), teal, pink,
           or any color not listed above. If unsure, use '#ff8b00' or '#383838'.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CHART TYPE RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RULE 1 — TWO CATEGORICAL DIMENSIONS + ONE NUMERIC (e.g. department + gender + count):
  → ALWAYS use px.bar with color=<second_category> and barmode='group'
  → NEVER generate a stacked bar or a plain bar without color when there are subgroups
  → Gender color_discrete_map MUST be: {'Female': '#ff8b00', 'Male': '#5b8db8'}
  → Example:
      fig = px.bar(df, x='department_name', y='total_employees',
                   color='Gender', barmode='group',
                   color_discrete_map={'Female': '#ff8b00', 'Male': '#5b8db8'})

RULE 2 — ONE CATEGORICAL + ONE NUMERIC (ranking/comparison):
  → If rows > 6: horizontal bar (orientation='h') sorted ascending, color='#ff8b00'
  → If rows <= 6: vertical bar, color_discrete_sequence=['#ff8b00','#383838','#5b8db8']
  → NEVER use unsorted bars

RULE 3 — SINGLE ROW RESULT (one KPI number):
  → Use go.Indicator(mode='number'), number font color='#ff8b00'
  → NEVER use a bar chart for a scalar

RULE 4 — SEQUENTIAL NUMERIC X (YearsAtCompany, JobLevel, tenure_band, age_range, any year/level column):
  → ALWAYS px.line with markers=True, color='#ff8b00', marker color='#383838'
  → This applies to ANY X that represents progression or ordered steps — NOT just date columns
  → NEVER use a bar chart when X is a numeric progression like YearsAtCompany or JobLevel

RULE 5 — PROPORTIONS / PERCENTAGES:
  → 2–6 categories: px.pie with hole=0.38, color_discrete_sequence from MULTI-SERIES COLORWAY
  → > 6 categories: horizontal bar
  → Gender distribution → ALWAYS pie/donut with color_discrete_map={'Female':'#ff8b00','Male':'#5b8db8'}

RULE 6 — DISTRIBUTION (distribucion, distribution, rango, spread):
  → Categorical x: px.box, color_discrete_sequence=['#ff8b00','#383838']
  → Single numeric: px.histogram, color_discrete_sequence=['#ff8b00']

RULE 7 — CORRELATION (two numeric variables, >=10 rows):
  → px.scatter, color='#ff8b00', opacity=0.65

RULE 8 — MULTI-METRIC COMPARISON (multiple score columns):
  → px.bar barmode='group', melt to long format first
  → Use MULTI-SERIES COLORWAY in order

RULE 9 — ATTRITION YES/NO SPLIT:
  → color_discrete_map={'Yes': '#c0392b', 'No': '#383838'}
  → barmode='group', never stacked

RULE 10 — SALARY / INCOME RANKING:
  → Horizontal bar sorted ascending, color='#ff8b00'
  → Text labels formatted as '$X,XXX'
"""


# ── SQL Examples ──────────────────────────────────────────────────────────────
EXAMPLES = [
    {
        "question": "What is the overall attrition rate?",
        "sql": """
            SELECT
                ROUND(100.0 * SUM(CASE WHEN Attrition = 'Yes' THEN 1 ELSE 0 END) / COUNT(*), 1) AS attrition_rate_pct
            FROM employees
        """
    },
    {
        "question": "Which departments have the highest attrition?",
        "sql": """
            SELECT
                d.department_name,
                COUNT(*) AS total_employees,
                SUM(CASE WHEN e.Attrition = 'Yes' THEN 1 ELSE 0 END) AS employees_left,
                ROUND(100.0 * SUM(CASE WHEN e.Attrition = 'Yes' THEN 1 ELSE 0 END) / COUNT(*), 1) AS attrition_pct
            FROM employees e
            JOIN departments d ON e.department_id = d.department_id
            GROUP BY d.department_name
            ORDER BY attrition_pct DESC
        """
    },
    {
        "question": "What is the average monthly income by job role?",
        "sql": """
            SELECT
                jr.role_name,
                ROUND(AVG(e.MonthlyIncome), 0) AS avg_monthly_income,
                COUNT(*) AS employee_count
            FROM employees e
            JOIN job_roles jr ON e.role_id = jr.role_id
            GROUP BY jr.role_name
            ORDER BY avg_monthly_income DESC
        """
    },
    {
        "question": "How does job satisfaction vary by department?",
        "sql": """
            SELECT
                d.department_name,
                ROUND(AVG(s.JobSatisfaction), 2)        AS avg_job_satisfaction,
                ROUND(AVG(s.WorkLifeBalance), 2)         AS avg_work_life_balance,
                ROUND(AVG(s.EnvironmentSatisfaction), 2) AS avg_environment_satisfaction
            FROM satisfaction s
            JOIN employees e  ON s.employee_id = e.employee_id
            JOIN departments d ON e.department_id = d.department_id
            GROUP BY d.department_name
            ORDER BY avg_job_satisfaction DESC
        """
    },
    {
        "question": "Do employees who work overtime have higher attrition?",
        "sql": """
            SELECT
                OverTime,
                COUNT(*) AS total,
                SUM(CASE WHEN Attrition = 'Yes' THEN 1 ELSE 0 END) AS left_company,
                ROUND(100.0 * SUM(CASE WHEN Attrition = 'Yes' THEN 1 ELSE 0 END) / COUNT(*), 1) AS attrition_pct
            FROM employees
            GROUP BY OverTime
        """
    },
    {
        "question": "What is the salary distribution by job level?",
        "sql": """
            SELECT
                JobLevel,
                COUNT(*) AS employees,
                ROUND(MIN(MonthlyIncome), 0) AS min_salary,
                ROUND(AVG(MonthlyIncome), 0) AS avg_salary,
                ROUND(MAX(MonthlyIncome), 0) AS max_salary
            FROM employees
            GROUP BY JobLevel
            ORDER BY JobLevel
        """
    },
    {
        "question": "Which job roles have the lowest performance ratings?",
        "sql": """
            SELECT
                jr.role_name,
                ROUND(AVG(s.PerformanceRating), 2) AS avg_performance,
                COUNT(*) AS employee_count
            FROM satisfaction s
            JOIN employees e  ON s.employee_id = e.employee_id
            JOIN job_roles jr ON e.role_id = jr.role_id
            GROUP BY jr.role_name
            ORDER BY avg_performance ASC
        """
    },
]


# ── KPI SQL Examples ──────────────────────────────────────────────────────────
KPI_EXAMPLES = [
    # ── Turnover & Retention ──────────────────────────────────────────────────
    {
        "question": "What is the turnover rate by department? (Tasa de Rotacion General)",
        "sql": """
            SELECT
                d.department_name,
                COUNT(*) AS total_employees,
                SUM(CASE WHEN e.Attrition = 'Yes' THEN 1 ELSE 0 END) AS employees_left,
                ROUND(100.0 * SUM(CASE WHEN e.Attrition = 'Yes' THEN 1 ELSE 0 END) / COUNT(*), 1) AS turnover_rate_pct
            FROM employees e
            JOIN departments d ON e.department_id = d.department_id
            GROUP BY d.department_name
            ORDER BY turnover_rate_pct DESC
        """
    },
    {
        "question": "Which employees are at high flight risk? (Indice de Riesgo de Fuga)",
        "sql": """
            SELECT
                e.employee_id,
                jr.role_name,
                d.department_name,
                e.YearsAtCompany,
                e.OverTime,
                e.NumCompaniesWorked,
                s.PerformanceRating,
                ROUND((
                    (CASE WHEN e.OverTime = 'Yes' THEN 0.25 ELSE 0 END) +
                    (CASE WHEN e.YearsAtCompany <= 2 THEN 0.25
                          WHEN e.YearsAtCompany <= 4 THEN 0.10 ELSE 0 END) +
                    (CASE WHEN e.NumCompaniesWorked >= 4 THEN 0.25
                          WHEN e.NumCompaniesWorked >= 2 THEN 0.10 ELSE 0 END) +
                    (CASE WHEN s.PerformanceRating <= 2 THEN 0.25 ELSE 0 END)
                ) * 100, 1) AS flight_risk_score
            FROM employees e
            JOIN departments d  ON e.department_id = d.department_id
            JOIN job_roles jr   ON e.role_id = jr.role_id
            JOIN satisfaction s ON e.employee_id = s.employee_id
            WHERE e.Attrition = 'No'
            ORDER BY flight_risk_score DESC
            LIMIT 20
        """
    },
    # ── Overtime & Burnout ────────────────────────────────────────────────────
    {
        "question": "What is the overtime rate by department? (Frecuencia de Horas Extras)",
        "sql": """
            SELECT
                d.department_name,
                COUNT(*) AS total_employees,
                SUM(CASE WHEN e.OverTime = 'Yes' THEN 1 ELSE 0 END) AS employees_with_ot,
                ROUND(100.0 * SUM(CASE WHEN e.OverTime = 'Yes' THEN 1 ELSE 0 END) / COUNT(*), 1) AS overtime_rate_pct
            FROM employees e
            JOIN departments d ON e.department_id = d.department_id
            GROUP BY d.department_name
            ORDER BY overtime_rate_pct DESC
        """
    },
    {
        "question": "Which employees are at high burnout risk? (Indice de Riesgo de Burnout)",
        "sql": """
            SELECT
                e.employee_id,
                jr.role_name,
                d.department_name,
                e.OverTime,
                s.WorkLifeBalance,
                s.PerformanceRating,
                e.YearsSinceLastPromotion,
                ROUND((
                    (CASE WHEN e.OverTime = 'Yes' THEN 0.30 ELSE 0 END) +
                    (CASE WHEN s.WorkLifeBalance = 1 THEN 0.25
                          WHEN s.WorkLifeBalance = 2 THEN 0.15 ELSE 0 END) +
                    (CASE WHEN s.PerformanceRating <= 2 THEN 0.20 ELSE 0 END) +
                    (CASE WHEN e.YearsSinceLastPromotion >= 4 THEN 0.25
                          WHEN e.YearsSinceLastPromotion >= 2 THEN 0.10 ELSE 0 END)
                ) * 100, 1) AS burnout_risk_score
            FROM employees e
            JOIN departments d  ON e.department_id = d.department_id
            JOIN job_roles jr   ON e.role_id = jr.role_id
            JOIN satisfaction s ON e.employee_id = s.employee_id
            WHERE e.Attrition = 'No'
            ORDER BY burnout_risk_score DESC
            LIMIT 20
        """
    },
    # ── Compensation ──────────────────────────────────────────────────────────
    {
        "question": "What is the average labor cost per FTE by department? (Masa Salarial Promedio por Empleado)",
        "sql": """
            SELECT
                d.department_name,
                COUNT(*) AS headcount,
                ROUND(AVG(e.MonthlyIncome), 0) AS avg_monthly_income,
                ROUND(SUM(e.MonthlyIncome), 0) AS total_monthly_labor_cost
            FROM employees e
            JOIN departments d ON e.department_id = d.department_id
            GROUP BY d.department_name
            ORDER BY avg_monthly_income DESC
        """
    },
    {
        "question": "Is there a gender pay gap? (Indice de Equidad Salarial por Genero)",
        "sql": """
            SELECT
                jr.role_name,
                ROUND(AVG(CASE WHEN e.Gender = 'Female' THEN e.MonthlyIncome END), 0) AS avg_salary_female,
                ROUND(AVG(CASE WHEN e.Gender = 'Male'   THEN e.MonthlyIncome END), 0) AS avg_salary_male,
                ROUND(
                    AVG(CASE WHEN e.Gender = 'Female' THEN e.MonthlyIncome END) /
                    AVG(CASE WHEN e.Gender = 'Male'   THEN e.MonthlyIncome END)
                , 3) AS gender_pay_ratio
            FROM employees e
            JOIN job_roles jr ON e.role_id = jr.role_id
            GROUP BY jr.role_name
            HAVING avg_salary_female IS NOT NULL AND avg_salary_male IS NOT NULL
            ORDER BY gender_pay_ratio ASC
        """
    },
    {
        "question": "What is the compa-ratio by job level? (Indice de Equidad Interna Salarial)",
        "sql": """
            WITH avg_by_level AS (
                SELECT JobLevel, AVG(MonthlyIncome) AS midpoint
                FROM employees
                GROUP BY JobLevel
            )
            SELECT
                e.JobLevel,
                jr.role_name,
                e.MonthlyIncome AS actual_salary,
                ROUND(a.midpoint, 0) AS band_midpoint,
                ROUND(e.MonthlyIncome / a.midpoint, 3) AS compa_ratio,
                CASE
                    WHEN e.MonthlyIncome / a.midpoint < 0.85 THEN 'Under-paid'
                    WHEN e.MonthlyIncome / a.midpoint > 1.15 THEN 'Over-paid'
                    ELSE 'In range'
                END AS pay_status
            FROM employees e
            JOIN job_roles jr     ON e.role_id = jr.role_id
            JOIN avg_by_level a   ON e.JobLevel = a.JobLevel
            ORDER BY compa_ratio ASC
            LIMIT 30
        """
    },
    # ── Performance & Development ─────────────────────────────────────────────
    {
        "question": "What is the average performance score by department? (Puntuacion Promedio de Desempeno)",
        "sql": """
            SELECT
                d.department_name,
                ROUND(AVG(s.PerformanceRating), 2) AS avg_performance_score,
                COUNT(*) AS employees_evaluated,
                SUM(CASE WHEN s.PerformanceRating = 4 THEN 1 ELSE 0 END) AS outstanding,
                SUM(CASE WHEN s.PerformanceRating = 3 THEN 1 ELSE 0 END) AS excellent
            FROM satisfaction s
            JOIN employees e  ON s.employee_id = e.employee_id
            JOIN departments d ON e.department_id = d.department_id
            GROUP BY d.department_name
            ORDER BY avg_performance_score DESC
        """
    },
    {
        "question": "What is the internal promotion rate? (Tasa de Promocion Interna)",
        "sql": """
            SELECT
                d.department_name,
                COUNT(*) AS total_employees,
                SUM(CASE WHEN e.YearsSinceLastPromotion = 0 THEN 1 ELSE 0 END) AS recently_promoted,
                ROUND(100.0 * SUM(CASE WHEN e.YearsSinceLastPromotion = 0 THEN 1 ELSE 0 END) / COUNT(*), 1) AS promotion_rate_pct
            FROM employees e
            JOIN departments d ON e.department_id = d.department_id
            GROUP BY d.department_name
            ORDER BY promotion_rate_pct DESC
        """
    },
    # ── Workforce Structure ───────────────────────────────────────────────────
    {
        "question": "What is the headcount total and active employees? (Headcount Total)",
        "sql": """
            SELECT
                COUNT(*) AS total_headcount,
                SUM(CASE WHEN Attrition = 'No'  THEN 1 ELSE 0 END) AS active_employees,
                SUM(CASE WHEN Attrition = 'Yes' THEN 1 ELSE 0 END) AS employees_left
            FROM employees
        """
    },
    {
        "question": "What is the seniority distribution of the workforce? (Distribucion por Rango de Antiguedad)",
        "sql": """
            SELECT
                CASE
                    WHEN YearsAtCompany <= 1 THEN '0-1 years (highest risk)'
                    WHEN YearsAtCompany <= 3 THEN '1-3 years (high risk)'
                    WHEN YearsAtCompany <= 5 THEN '3-5 years (medium risk)'
                    ELSE '5+ years (stable)'
                END AS tenure_band,
                COUNT(*) AS employee_count,
                ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_of_workforce,
                ROUND(100.0 * SUM(CASE WHEN Attrition = 'Yes' THEN 1 ELSE 0 END) / COUNT(*), 1) AS attrition_rate_pct
            FROM employees
            GROUP BY tenure_band
            ORDER BY MIN(YearsAtCompany)
        """
    },
    {
        "question": "What is the demographic and diversity distribution? (Distribucion Demografica y Diversidad)",
        "sql": """
            SELECT
                Gender,
                COUNT(*) AS employee_count,
                ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_total,
                ROUND(AVG(Age), 1) AS avg_age,
                ROUND(AVG(MonthlyIncome), 0) AS avg_monthly_income,
                ROUND(100.0 * SUM(CASE WHEN Attrition = 'Yes' THEN 1 ELSE 0 END) / COUNT(*), 1) AS attrition_pct
            FROM employees
            GROUP BY Gender
        """
    },
    # ── Engagement & Wellbeing ────────────────────────────────────────────────
    {
        "question": "What is the employee engagement and wellbeing index by department? (Indice de Compromiso y Bienestar)",
        "sql": """
            SELECT
                d.department_name,
                ROUND(AVG(s.JobSatisfaction), 2)         AS avg_job_satisfaction,
                ROUND(AVG(s.WorkLifeBalance), 2)          AS avg_work_life_balance,
                ROUND(AVG(s.EnvironmentSatisfaction), 2)  AS avg_environment_satisfaction,
                ROUND(AVG(s.RelationshipSatisfaction), 2) AS avg_relationship_satisfaction,
                ROUND((AVG(s.JobSatisfaction) + AVG(s.WorkLifeBalance) +
                       AVG(s.EnvironmentSatisfaction) + AVG(s.RelationshipSatisfaction)) / 4, 2) AS engagement_index
            FROM satisfaction s
            JOIN employees e  ON s.employee_id = e.employee_id
            JOIN departments d ON e.department_id = d.department_id
            GROUP BY d.department_name
            ORDER BY engagement_index DESC
        """
    },
    # ── Overtime distribution ─────────────────────────────────────────────────
    {
        "question": "Which department has the highest percentage of overtime hours? (cual fue el departamento con mayor porcentaje de horas extras)",
        "sql": """
            WITH dept_ot AS (
                SELECT
                    d.department_name,
                    SUM(CASE WHEN e.OverTime = 'Yes' THEN 1 ELSE 0 END) AS ot_employees,
                    COUNT(*) AS total_employees
                FROM employees e
                JOIN departments d ON e.department_id = d.department_id
                GROUP BY d.department_name
            ),
            total_ot AS (
                SELECT SUM(ot_employees) AS grand_total_ot FROM dept_ot
            )
            SELECT
                dept_ot.department_name,
                dept_ot.ot_employees,
                dept_ot.total_employees,
                ROUND(100.0 * dept_ot.ot_employees / dept_ot.total_employees, 1) AS ot_rate_within_dept_pct,
                ROUND(100.0 * dept_ot.ot_employees / total_ot.grand_total_ot, 1) AS pct_of_total_overtime
            FROM dept_ot, total_ot
            ORDER BY pct_of_total_overtime DESC
        """
    },
    # ── Spanish language variants ─────────────────────────────────────────────
    {
        "question": "Cual es la tasa de rotacion por departamento?",
        "sql": """
            SELECT
                d.department_name,
                COUNT(*) AS total_empleados,
                SUM(CASE WHEN e.Attrition = 'Yes' THEN 1 ELSE 0 END) AS empleados_que_salieron,
                ROUND(100.0 * SUM(CASE WHEN e.Attrition = 'Yes' THEN 1 ELSE 0 END) / COUNT(*), 1) AS tasa_rotacion_pct
            FROM employees e
            JOIN departments d ON e.department_id = d.department_id
            GROUP BY d.department_name
            ORDER BY tasa_rotacion_pct DESC
        """
    },
    {
        "question": "Cuantos empleados hay en total y cuantos se fueron?",
        "sql": """
            SELECT
                COUNT(*) AS total_empleados,
                SUM(CASE WHEN Attrition = 'Yes' THEN 1 ELSE 0 END) AS empleados_que_salieron,
                SUM(CASE WHEN Attrition = 'No'  THEN 1 ELSE 0 END) AS empleados_activos,
                ROUND(100.0 * SUM(CASE WHEN Attrition = 'Yes' THEN 1 ELSE 0 END) / COUNT(*), 1) AS tasa_rotacion_pct
            FROM employees
        """
    },
    {
        "question": "Cual es el salario promedio por departamento?",
        "sql": """
            SELECT
                d.department_name,
                COUNT(*) AS empleados,
                ROUND(AVG(e.MonthlyIncome), 0) AS salario_promedio_mensual,
                ROUND(MIN(e.MonthlyIncome), 0) AS salario_minimo,
                ROUND(MAX(e.MonthlyIncome), 0) AS salario_maximo
            FROM employees e
            JOIN departments d ON e.department_id = d.department_id
            GROUP BY d.department_name
            ORDER BY salario_promedio_mensual DESC
        """
    },
    {
        "question": "Que porcentaje de empleados hace horas extras por departamento?",
        "sql": """
            SELECT
                d.department_name,
                COUNT(*) AS total_empleados,
                SUM(CASE WHEN e.OverTime = 'Yes' THEN 1 ELSE 0 END) AS con_horas_extra,
                ROUND(100.0 * SUM(CASE WHEN e.OverTime = 'Yes' THEN 1 ELSE 0 END) / COUNT(*), 1) AS porcentaje_horas_extra
            FROM employees e
            JOIN departments d ON e.department_id = d.department_id
            GROUP BY d.department_name
            ORDER BY porcentaje_horas_extra DESC
        """
    },
]


# ── Tablas sintéticas (build_synthetic_data.py) ───────────────────────────────
# DDL + documentación + ejemplos para que el copiloto consulte asistencia,
# nómina, vacantes, encuestas y capacitación. Ventana: 2024-06 a 2026-05.
DDL_SYNTH = """
CREATE TABLE employment_dates (
    employee_id INTEGER PRIMARY KEY REFERENCES employees(employee_id),
    hire_date TEXT,   -- 'YYYY-MM-DD'
    exit_date TEXT,   -- NULL = sigue activo
    exit_type TEXT    -- 'voluntary' | 'involuntary' | NULL
);
CREATE TABLE attendance_monthly (
    employee_id INTEGER REFERENCES employees(employee_id),
    month TEXT,       -- 'YYYY-MM', de 2024-06 a 2026-05
    scheduled_days INTEGER, absence_days INTEGER,
    regular_hours REAL, overtime_hours REAL, late_arrivals INTEGER
);
CREATE TABLE medical_leaves (
    employee_id INTEGER, start_date TEXT, days INTEGER,
    leave_type TEXT   -- 'Enfermedad General (EPS)' | 'Accidente de Trabajo (ARL)' | 'Enfermedad Laboral (ARL)'
);
CREATE TABLE payroll_monthly (
    employee_id INTEGER, month TEXT,
    base_salary REAL, benefits REAL, employer_contributions REAL,
    overtime_pay REAL, total_cost REAL  -- USD
);
CREATE TABLE payroll_runs (
    month TEXT, scheduled_pay_date TEXT, actual_pay_date TEXT,
    payslips_total INTEGER, payslips_with_errors INTEGER
);
CREATE TABLE salary_bands (job_level INTEGER, band_min REAL, band_mid REAL, band_max REAL);
CREATE TABLE headcount_history (
    month TEXT, department_id INTEGER REFERENCES departments(department_id),
    headcount INTEGER, hires INTEGER, exits_voluntary INTEGER, exits_involuntary INTEGER
);
CREATE TABLE vacancies (
    vacancy_id INTEGER, department_id INTEGER, role_id INTEGER, job_level INTEGER,
    opened_date TEXT, closed_date TEXT,   -- NULL = vacante abierta
    monthly_salary REAL, productivity_factor REAL,
    offers_extended INTEGER, offers_accepted INTEGER,
    filled_by TEXT,        -- 'internal' | 'external' | NULL
    quality_of_hire REAL   -- 0-100
);
CREATE TABLE survey_cycles (cycle TEXT, survey_date TEXT, invited INTEGER);  -- cycle: '2025Q1'
CREATE TABLE survey_responses (
    employee_id INTEGER, cycle TEXT,
    q_pride INTEGER, q_recommend_nps INTEGER,  -- q_recommend_nps: 0-10 (eNPS)
    q_effort INTEGER, q_stay INTEGER, q_satisfaction INTEGER  -- Likert 1-5 / 0-10
);
CREATE TABLE training_programs (
    program_id INTEGER, program_name TEXT, category TEXT, program_date TEXT, cost_usd INTEGER
);
CREATE TABLE training_participants (
    program_id INTEGER, employee_id INTEGER, perf_score_pre REAL, perf_score_post REAL  -- escala 1-5
);
CREATE TABLE company_financials (month TEXT, operating_revenue REAL);
CREATE TABLE vacation_balances (
    employee_id INTEGER, accrued_days INTEGER, taken_days INTEGER, pending_days INTEGER
);
"""

SYNTH_DOCUMENTATION = """
Synthetic HR time-series tables (window: 2024-06 through 2026-05, 24 months):
- month columns are TEXT 'YYYY-MM'. ORDER BY month works chronologically.
- employment_dates: exit_date IS NULL means the employee is still active today.
- Absenteeism rate (%) = 100.0*SUM(absence_days)/SUM(scheduled_days) from attendance_monthly.
- Overtime rate (%) = 100.0*SUM(overtime_hours)/SUM(regular_hours).
- eNPS per cycle = 100*promoters(q_recommend_nps>=9)/total - 100*detractors(q_recommend_nps<=6)/total.
- Time to Fill (days) = julianday(closed_date)-julianday(opened_date) on vacancies with closed_date NOT NULL.
- Turnover/hires trends come from headcount_history (already aggregated by month and department).
- Labor cost ratio (%) = 100*SUM(payroll_monthly.total_cost)/company_financials.operating_revenue joined by month.
- Training effectiveness (%) per program = 100*(AVG(perf_score_post)-AVG(perf_score_pre))/AVG(perf_score_pre).
- Quarter of a month string: substr(month,1,4) || '-Q' || ((CAST(substr(month,6,2) AS INTEGER)+2)/3).
- Join aliases: attendance_monthly a, payroll_monthly p, medical_leaves ml, vacancies v,
  headcount_history hh, survey_responses sr, employment_dates ed.
- Questions about evolution/trend/tendencia/mensual should GROUP BY month and ORDER BY month.
"""

SYNTH_EXAMPLES = [
    {"question": "¿Cómo ha evolucionado el headcount mes a mes?",
     "sql": "SELECT month, SUM(headcount) AS headcount FROM headcount_history GROUP BY month ORDER BY month;"},
    {"question": "¿Cuál es la tasa de ausentismo mensual?",
     "sql": "SELECT month, ROUND(100.0*SUM(absence_days)/SUM(scheduled_days), 2) AS absenteeism_rate_pct FROM attendance_monthly GROUP BY month ORDER BY month;"},
    {"question": "Ingresos y egresos de personal por mes",
     "sql": "SELECT month, SUM(hires) AS hires, SUM(exits_voluntary + exits_involuntary) AS exits FROM headcount_history GROUP BY month ORDER BY month;"},
    {"question": "Horas extra promedio por mes y departamento",
     "sql": "SELECT a.month, d.department_name, ROUND(AVG(a.overtime_hours), 1) AS avg_overtime_hours FROM attendance_monthly a JOIN employees e ON a.employee_id = e.employee_id JOIN departments d ON e.department_id = d.department_id GROUP BY a.month, d.department_name ORDER BY a.month;"},
    {"question": "¿Cuántas incapacidades hay por tipo?",
     "sql": "SELECT leave_type, COUNT(*) AS total_leaves, SUM(days) AS total_days FROM medical_leaves GROUP BY leave_type ORDER BY total_leaves DESC;"},
    {"question": "¿Cuál es el eNPS por ciclo de encuesta?",
     "sql": "SELECT cycle, ROUND(100.0*SUM(q_recommend_nps >= 9)/COUNT(*) - 100.0*SUM(q_recommend_nps <= 6)/COUNT(*), 1) AS enps FROM survey_responses GROUP BY cycle ORDER BY cycle;"},
    {"question": "Tiempo promedio de cobertura de vacantes por departamento",
     "sql": "SELECT d.department_name, ROUND(AVG(julianday(v.closed_date) - julianday(v.opened_date)), 0) AS avg_days_to_fill FROM vacancies v JOIN departments d ON v.department_id = d.department_id WHERE v.closed_date IS NOT NULL GROUP BY d.department_name ORDER BY avg_days_to_fill DESC;"},
    {"question": "¿Qué porcentaje de los ingresos se gasta en nómina cada mes?",
     "sql": "SELECT p.month, ROUND(100.0*SUM(p.total_cost)/f.operating_revenue, 1) AS labor_cost_ratio_pct FROM payroll_monthly p JOIN company_financials f ON p.month = f.month GROUP BY p.month ORDER BY p.month;"},
    {"question": "Salidas voluntarias vs involuntarias por mes",
     "sql": "SELECT month, SUM(exits_voluntary) AS voluntary, SUM(exits_involuntary) AS involuntary FROM headcount_history GROUP BY month ORDER BY month;"},
    {"question": "Compa-ratio promedio por nivel de cargo",
     "sql": "SELECT e.JobLevel, ROUND(AVG(1.0*e.MonthlyIncome/b.band_mid), 2) AS avg_compa_ratio FROM employees e JOIN salary_bands b ON e.JobLevel = b.job_level GROUP BY e.JobLevel ORDER BY e.JobLevel;"},
    {"question": "¿Qué programas de capacitación mejoraron más el desempeño?",
     "sql": "SELECT tp.program_name, ROUND(100.0*(AVG(t.perf_score_post)-AVG(t.perf_score_pre))/AVG(t.perf_score_pre), 1) AS improvement_pct FROM training_participants t JOIN training_programs tp ON t.program_id = tp.program_id GROUP BY tp.program_name ORDER BY improvement_pct DESC;"},
    {"question": "¿Cuántas vacantes abiertas hay por departamento?",
     "sql": "SELECT d.department_name, COUNT(*) AS open_vacancies FROM vacancies v JOIN departments d ON v.department_id = d.department_id WHERE v.closed_date IS NULL GROUP BY d.department_name ORDER BY open_vacancies DESC;"},
    {"question": "Participación en las encuestas de clima por ciclo",
     "sql": "SELECT sr.cycle, ROUND(100.0*COUNT(*)/sc.invited, 1) AS participation_pct FROM survey_responses sr JOIN survey_cycles sc ON sr.cycle = sc.cycle GROUP BY sr.cycle ORDER BY sr.cycle;"},
    {"question": "Relación entre ausentismo y horas extra por empleado",
     "sql": "SELECT employee_id, SUM(absence_days) AS total_absence_days, SUM(overtime_hours) AS total_overtime_hours FROM attendance_monthly GROUP BY employee_id;"},
    {"question": "Costo de nómina mensual desglosado por concepto",
     "sql": "SELECT month, ROUND(SUM(base_salary), 0) AS base, ROUND(SUM(benefits), 0) AS benefits, ROUND(SUM(employer_contributions), 0) AS contributions, ROUND(SUM(overtime_pay), 0) AS overtime FROM payroll_monthly GROUP BY month ORDER BY month;"},
]


# ── Plotly Visualization Examples ─────────────────────────────────────────────
# These teach Gemini the correct chart type for each data shape.
# Each entry pairs a question+SQL result shape with the CORRECT Plotly code.
# This is the primary fix for the "wrong chart type" problem.
PLOTLY_EXAMPLES = [
    # ── RULE 1: Two categoricals + numeric → grouped bar with color ───────────
    {
        "question": "How many male and female employees are there per department?",
        "sql": """
            SELECT d.department_name, e.Gender, COUNT(*) AS total_employees
            FROM employees e
            JOIN departments d ON e.department_id = d.department_id
            GROUP BY d.department_name, e.Gender
            ORDER BY d.department_name, e.Gender
        """,
        "plotly_code": """
import plotly.express as px
fig = px.bar(
    df,
    x='department_name',
    y='total_employees',
    color='Gender',
    barmode='group',
    title='Headcount by Department and Gender',
    text='total_employees',
    color_discrete_map={'Female': '#ff8b00', 'Male': '#5b8db8'},
)
fig.update_traces(textposition='outside')
fig.update_layout(xaxis_title='Department', yaxis_title='Employees', legend_title='Gender')
"""
    },
    {
        "question": "cuantos hombre y cuantas mujeres tiene la empresa por departamento",
        "sql": """
            SELECT d.department_name, e.Gender, COUNT(*) AS total_employees
            FROM employees e
            JOIN departments d ON e.department_id = d.department_id
            GROUP BY d.department_name, e.Gender
            ORDER BY d.department_name, e.Gender
        """,
        "plotly_code": """
import plotly.express as px
fig = px.bar(
    df,
    x='department_name',
    y='total_employees',
    color='Gender',
    barmode='group',
    title='Empleados por Departamento y Género',
    text='total_employees',
    color_discrete_map={'Female': '#ff8b00', 'Male': '#5b8db8'},
)
fig.update_traces(textposition='outside')
fig.update_layout(xaxis_title='Departamento', yaxis_title='Empleados', legend_title='Género')
"""
    },
    {
        "question": "Show attrition count split by gender for each department",
        "sql": """
            SELECT d.department_name, e.Gender,
                   SUM(CASE WHEN e.Attrition='Yes' THEN 1 ELSE 0 END) AS employees_left
            FROM employees e
            JOIN departments d ON e.department_id = d.department_id
            GROUP BY d.department_name, e.Gender
        """,
        "plotly_code": """
import plotly.express as px
fig = px.bar(
    df,
    x='department_name',
    y='employees_left',
    color='Gender',
    barmode='group',
    title='Attrition by Department and Gender',
    text='employees_left',
    color_discrete_map={'Female': '#ff8b00', 'Male': '#5b8db8'},
)
fig.update_traces(textposition='outside')
"""
    },
    # ── RULE 2: Ranking — horizontal bar sorted ───────────────────────────────
    {
        "question": "What is the average monthly income by job role?",
        "sql": """
            SELECT jr.role_name,
                   ROUND(AVG(e.MonthlyIncome), 0) AS avg_monthly_income
            FROM employees e
            JOIN job_roles jr ON e.role_id = jr.role_id
            GROUP BY jr.role_name
            ORDER BY avg_monthly_income DESC
        """,
        "plotly_code": """
import plotly.express as px
df_sorted = df.sort_values('avg_monthly_income', ascending=True)
fig = px.bar(
    df_sorted,
    x='avg_monthly_income',
    y='role_name',
    orientation='h',
    title='Average Monthly Income by Job Role',
    text='avg_monthly_income',
    color_discrete_sequence=['#ff8b00'],
)
fig.update_traces(texttemplate='$%{text:,.0f}', textposition='outside')
fig.update_layout(xaxis_title='Avg Monthly Income (USD)', yaxis_title='')
"""
    },
    {
        "question": "Cuales son los roles con mayor salario promedio?",
        "sql": """
            SELECT jr.role_name,
                   ROUND(AVG(e.MonthlyIncome), 0) AS salario_promedio
            FROM employees e
            JOIN job_roles jr ON e.role_id = jr.role_id
            GROUP BY jr.role_name
            ORDER BY salario_promedio DESC
        """,
        "plotly_code": """
import plotly.express as px
df_sorted = df.sort_values('salario_promedio', ascending=True)
fig = px.bar(
    df_sorted,
    x='salario_promedio',
    y='role_name',
    orientation='h',
    title='Salario Promedio por Rol',
    text='salario_promedio',
    color_discrete_sequence=['#ff8b00'],
)
fig.update_traces(texttemplate='$%{text:,.0f}', textposition='outside')
fig.update_layout(xaxis_title='Salario Promedio (USD)', yaxis_title='')
"""
    },
    # ── RULE 3: Single row → KPI Indicator ───────────────────────────────────
    {
        "question": "What is the overall attrition rate?",
        "sql": """
            SELECT ROUND(100.0 * SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) / COUNT(*), 1)
                   AS attrition_rate_pct
            FROM employees
        """,
        "plotly_code": """
import plotly.graph_objects as go
fig = go.Figure(go.Indicator(
    mode='number',
    value=float(df.iloc[0]['attrition_rate_pct']),
    number={'suffix': '%', 'font': {'size': 72, 'color': '#c0392b'}},
    title={'text': 'Overall Attrition Rate', 'font': {'size': 18}},
))
fig.update_layout(height=300)
"""
    },
    {
        "question": "Cuantos empleados hay en total?",
        "sql": """
            SELECT COUNT(*) AS total_headcount,
                   SUM(CASE WHEN Attrition='No' THEN 1 ELSE 0 END) AS active_employees,
                   SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) AS employees_left
            FROM employees
        """,
        "plotly_code": """
import plotly.graph_objects as go
row = df.iloc[0]
fig = go.Figure()
metrics = [
    ('total_headcount', 'Total Headcount', '#383838'),
    ('active_employees', 'Active Employees', '#383838'),
    ('employees_left', 'Employees Left', '#c0392b'),
]
for i, (col, label, color) in enumerate(metrics):
    fig.add_trace(go.Indicator(
        mode='number',
        value=float(row[col]),
        title={'text': label},
        number={'font': {'size': 52, 'color': color}},
        domain={'row': 0, 'column': i},
    ))
fig.update_layout(grid={'rows': 1, 'columns': 3}, height=220)
"""
    },
    # ── RULE 4: Time series → line chart ─────────────────────────────────────
    {
        "question": "How has attrition changed by years at company?",
        "sql": """
            SELECT YearsAtCompany,
                   ROUND(100.0 * SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) / COUNT(*), 1)
                   AS attrition_pct
            FROM employees
            GROUP BY YearsAtCompany
            ORDER BY YearsAtCompany
        """,
        "plotly_code": """
import plotly.express as px
fig = px.line(
    df,
    x='YearsAtCompany',
    y='attrition_pct',
    title='Attrition Rate by Tenure',
    markers=True,
    color_discrete_sequence=['#ff8b00'],
)
fig.update_traces(line=dict(width=2.5))
fig.update_layout(xaxis_title='Years at Company', yaxis_title='Attrition Rate (%)')
"""
    },
    # ── RULE 5: Proportions → donut chart ────────────────────────────────────
    {
        "question": "What is the attrition rate by department as a percentage?",
        "sql": """
            SELECT d.department_name,
                   ROUND(100.0 * SUM(CASE WHEN e.Attrition='Yes' THEN 1 ELSE 0 END) / COUNT(*), 1)
                   AS attrition_pct
            FROM employees e
            JOIN departments d ON e.department_id = d.department_id
            GROUP BY d.department_name
        """,
        "plotly_code": """
import plotly.express as px
fig = px.pie(
    df,
    names='department_name',
    values='attrition_pct',
    title='Attrition Rate Distribution by Department',
    hole=0.38,
    color_discrete_sequence=['#ff8b00', '#383838', '#5b8db8'],
)
fig.update_traces(textposition='inside', textinfo='percent+label')
"""
    },
    {
        "question": "Que porcentaje de empleados hace horas extras por departamento?",
        "sql": """
            SELECT d.department_name,
                   ROUND(100.0 * SUM(CASE WHEN e.OverTime='Yes' THEN 1 ELSE 0 END) / COUNT(*), 1)
                   AS porcentaje_horas_extra
            FROM employees e
            JOIN departments d ON e.department_id = d.department_id
            GROUP BY d.department_name
        """,
        "plotly_code": """
import plotly.express as px
fig = px.pie(
    df,
    names='department_name',
    values='porcentaje_horas_extra',
    title='Porcentaje de Horas Extras por Departamento',
    hole=0.38,
    color_discrete_sequence=['#ff8b00', '#383838', '#5b8db8'],
)
fig.update_traces(textposition='inside', textinfo='percent+label')
"""
    },
    # ── RULE 6: Distribution → histogram ─────────────────────────────────────
    {
        "question": "What is the age distribution of employees?",
        "sql": """
            SELECT Age FROM employees ORDER BY Age
        """,
        "plotly_code": """
import plotly.express as px
fig = px.histogram(
    df,
    x='Age',
    nbins=20,
    title='Age Distribution of Employees',
    color_discrete_sequence=['#ff8b00'],
)
fig.update_layout(xaxis_title='Age', yaxis_title='Count', bargap=0.05)
"""
    },
    {
        "question": "Show the distribution of monthly income",
        "sql": """
            SELECT MonthlyIncome FROM employees ORDER BY MonthlyIncome
        """,
        "plotly_code": """
import plotly.express as px
fig = px.histogram(
    df,
    x='MonthlyIncome',
    nbins=30,
    title='Monthly Income Distribution',
    color_discrete_sequence=['#ff8b00'],
)
fig.update_layout(xaxis_title='Monthly Income (USD)', yaxis_title='Count', bargap=0.03)
"""
    },
    # ── RULE 8: Multi-metric grouped bar ─────────────────────────────────────
    {
        "question": "How does job satisfaction vary by department across all satisfaction dimensions?",
        "sql": """
            SELECT d.department_name,
                   ROUND(AVG(s.JobSatisfaction), 2)         AS avg_job_satisfaction,
                   ROUND(AVG(s.WorkLifeBalance), 2)          AS avg_work_life_balance,
                   ROUND(AVG(s.EnvironmentSatisfaction), 2)  AS avg_environment_satisfaction,
                   ROUND(AVG(s.RelationshipSatisfaction), 2) AS avg_relationship_satisfaction
            FROM satisfaction s
            JOIN employees e  ON s.employee_id = e.employee_id
            JOIN departments d ON e.department_id = d.department_id
            GROUP BY d.department_name
        """,
        "plotly_code": """
import plotly.express as px
import pandas as pd
metrics = ['avg_job_satisfaction', 'avg_work_life_balance',
           'avg_environment_satisfaction', 'avg_relationship_satisfaction']
df_long = df.melt(id_vars='department_name', value_vars=metrics,
                  var_name='metric', value_name='score')
df_long['metric'] = df_long['metric'].str.replace('avg_', '').str.replace('_', ' ').str.title()
fig = px.bar(
    df_long,
    x='department_name',
    y='score',
    color='metric',
    barmode='group',
    title='Satisfaction Dimensions by Department',
    text=df_long['score'].round(2),
    color_discrete_sequence=['#ff8b00', '#383838', '#5b8db8', '#e67e22'],
)
fig.update_traces(textposition='outside')
fig.update_layout(xaxis_title='Department', yaxis_title='Score (1–4)', legend_title='Metric',
                  yaxis_range=[0, 5])
"""
    },
    # ── RULE 9: Attrition binary split → grouped bar with color ──────────────
    {
        "question": "Do employees who work overtime have higher attrition?",
        "sql": """
            SELECT OverTime,
                   COUNT(*) AS total,
                   SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) AS left_company,
                   ROUND(100.0 * SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) / COUNT(*), 1)
                   AS attrition_pct
            FROM employees GROUP BY OverTime
        """,
        "plotly_code": """
import plotly.express as px
fig = px.bar(
    df,
    x='OverTime',
    y='attrition_pct',
    color='OverTime',
    title='Attrition Rate by Overtime Status',
    text='attrition_pct',
    color_discrete_map={'Yes': '#c0392b', 'No': '#383838'},
)
fig.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
fig.update_layout(showlegend=False, xaxis_title='Works Overtime',
                  yaxis_title='Attrition Rate (%)', yaxis_range=[0, 50])
"""
    },
    {
        "question": "Afectan las horas extras la rotacion de personal?",
        "sql": """
            SELECT OverTime,
                   ROUND(100.0 * SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) / COUNT(*), 1)
                   AS tasa_rotacion_pct,
                   COUNT(*) AS total_empleados
            FROM employees GROUP BY OverTime
        """,
        "plotly_code": """
import plotly.express as px
fig = px.bar(
    df,
    x='OverTime',
    y='tasa_rotacion_pct',
    color='OverTime',
    title='Tasa de Rotación según Horas Extras',
    text='tasa_rotacion_pct',
    color_discrete_map={'Yes': '#c0392b', 'No': '#383838'},
)
fig.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
fig.update_layout(showlegend=False, xaxis_title='Hace Horas Extras',
                  yaxis_title='Tasa de Rotación (%)', yaxis_range=[0, 50])
"""
    },
    # ── RULE 10: Salary ranking — horizontal bar with currency labels ─────────
    {
        "question": "What is the salary distribution by job level?",
        "sql": """
            SELECT JobLevel,
                   ROUND(MIN(MonthlyIncome), 0) AS min_salary,
                   ROUND(AVG(MonthlyIncome), 0) AS avg_salary,
                   ROUND(MAX(MonthlyIncome), 0) AS max_salary
            FROM employees
            GROUP BY JobLevel ORDER BY JobLevel
        """,
        "plotly_code": """
import plotly.express as px
import pandas as pd
df['JobLevel'] = df['JobLevel'].astype(str).apply(lambda x: f'Level {x}')
df_long = df.melt(id_vars='JobLevel',
                  value_vars=['min_salary', 'avg_salary', 'max_salary'],
                  var_name='metric', value_name='salary')
df_long['metric'] = df_long['metric'].str.replace('_salary', '').str.title()
fig = px.bar(
    df_long,
    x='JobLevel',
    y='salary',
    color='metric',
    barmode='group',
    title='Salary Range by Job Level',
    text='salary',
    color_discrete_sequence=['#dddddd', '#ff8b00', '#383838'],
)
fig.update_traces(texttemplate='$%{text:,.0f}', textposition='outside')
fig.update_layout(xaxis_title='Job Level', yaxis_title='Monthly Income (USD)',
                  legend_title='Metric')
"""
    },
    # ── RULE 4: Sequential numeric X → LINE chart (NOT bar) ──────────────────
    {
        "question": "How does attrition rate change by years at company?",
        "sql": """
            SELECT YearsAtCompany,
                   ROUND(100.0 * SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) / COUNT(*), 1)
                   AS attrition_pct,
                   COUNT(*) AS employee_count
            FROM employees
            GROUP BY YearsAtCompany
            ORDER BY YearsAtCompany
        """,
        "plotly_code": """
import plotly.express as px
fig = px.line(
    df,
    x='YearsAtCompany',
    y='attrition_pct',
    title='Attrition Rate by Years at Company',
    markers=True,
    color_discrete_sequence=['#ff8b00'],
)
fig.update_traces(line=dict(width=2.5), marker=dict(size=7, color='#383838'))
fig.update_layout(
    xaxis_title='Years at Company',
    yaxis_title='Attrition Rate (%)',
    yaxis_range=[0, max(df['attrition_pct']) * 1.2],
)
"""
    },
    {
        "question": "Como varia la tasa de rotacion segun los anos en la empresa?",
        "sql": """
            SELECT YearsAtCompany,
                   ROUND(100.0 * SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) / COUNT(*), 1)
                   AS tasa_rotacion_pct
            FROM employees
            GROUP BY YearsAtCompany
            ORDER BY YearsAtCompany
        """,
        "plotly_code": """
import plotly.express as px
fig = px.line(
    df,
    x='YearsAtCompany',
    y='tasa_rotacion_pct',
    title='Tasa de Rotación por Años en la Empresa',
    markers=True,
    color_discrete_sequence=['#ff8b00'],
)
fig.update_traces(line=dict(width=2.5), marker=dict(size=7, color='#383838'))
fig.update_layout(xaxis_title='Años en la Empresa', yaxis_title='Tasa de Rotación (%)')
"""
    },
    {
        "question": "What is the average salary by job level?",
        "sql": """
            SELECT JobLevel,
                   ROUND(AVG(MonthlyIncome), 0) AS avg_salary,
                   COUNT(*) AS employees
            FROM employees
            GROUP BY JobLevel
            ORDER BY JobLevel
        """,
        "plotly_code": """
import plotly.express as px
fig = px.line(
    df,
    x='JobLevel',
    y='avg_salary',
    title='Average Monthly Income by Job Level',
    markers=True,
    color_discrete_sequence=['#ff8b00'],
)
fig.update_traces(line=dict(width=2.5), marker=dict(size=8, color='#383838'))
fig.update_layout(
    xaxis_title='Job Level (1=Entry → 5=Executive)',
    yaxis_title='Avg Monthly Income (USD)',
)
fig.update_xaxes(tickmode='linear', dtick=1)
"""
    },
    # ── RULE 5: Gender donut → pie with Práxedes colors ───────────────────────
    {
        "question": "What is the gender distribution of the company?",
        "sql": """
            SELECT Gender,
                   COUNT(*) AS employee_count,
                   ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_total
            FROM employees
            GROUP BY Gender
        """,
        "plotly_code": """
import plotly.express as px
fig = px.pie(
    df,
    names='Gender',
    values='employee_count',
    title='Gender Distribution',
    hole=0.38,
    color='Gender',
    color_discrete_map={'Female': '#ff8b00', 'Male': '#5b8db8'},
)
fig.update_traces(textposition='inside', textinfo='percent+label')
"""
    },
    {
        "question": "Cual es la distribucion de genero en la empresa?",
        "sql": """
            SELECT Gender,
                   COUNT(*) AS total_empleados,
                   ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_total
            FROM employees
            GROUP BY Gender
        """,
        "plotly_code": """
import plotly.express as px
fig = px.pie(
    df,
    names='Gender',
    values='total_empleados',
    title='Distribución de Género',
    hole=0.38,
    color='Gender',
    color_discrete_map={'Female': '#ff8b00', 'Male': '#5b8db8'},
)
fig.update_traces(textposition='inside', textinfo='percent+label')
"""
    },
    # ── RULE 7: Correlation two numerics → scatter ────────────────────────────
    {
        "question": "Is there a correlation between distance from home and attrition?",
        "sql": """
            SELECT DistanceFromHome,
                   ROUND(100.0 * SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) / COUNT(*), 1)
                   AS attrition_pct,
                   COUNT(*) AS employees
            FROM employees
            GROUP BY DistanceFromHome
            ORDER BY DistanceFromHome
        """,
        "plotly_code": """
import plotly.express as px
fig = px.scatter(
    df,
    x='DistanceFromHome',
    y='attrition_pct',
    size='employees',
    title='Distance from Home vs Attrition Rate',
    color_discrete_sequence=['#ff8b00'],
    opacity=0.75,
)
fig.update_traces(marker=dict(color='#ff8b00', line=dict(color='#383838', width=1)))
fig.update_layout(xaxis_title='Distance from Home (miles)', yaxis_title='Attrition Rate (%)')
"""
    },
    # ── RULE 3: Multi-KPI single row → Indicators ─────────────────────────────
    {
        "question": "What is the overall attrition rate and overtime rate?",
        "sql": """
            SELECT
                ROUND(100.0 * SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) / COUNT(*), 1) AS attrition_rate_pct,
                ROUND(100.0 * SUM(CASE WHEN OverTime='Yes' THEN 1 ELSE 0 END) / COUNT(*), 1) AS overtime_rate_pct,
                COUNT(*) AS total_headcount
            FROM employees
        """,
        "plotly_code": """
import plotly.graph_objects as go
row = df.iloc[0]
fig = go.Figure()
kpis = [
    ('total_headcount', 'Total Headcount', '#383838', ''),
    ('attrition_rate_pct', 'Attrition Rate', '#c0392b', '%'),
    ('overtime_rate_pct', 'Overtime Rate', '#ff8b00', '%'),
]
for i, (col, label, color, suffix) in enumerate(kpis):
    fig.add_trace(go.Indicator(
        mode='number',
        value=float(row[col]),
        title={'text': label, 'font': {'size': 14}},
        number={'font': {'size': 52, 'color': color}, 'suffix': suffix},
        domain={'row': 0, 'column': i},
    ))
fig.update_layout(grid={'rows': 1, 'columns': 3}, height=220)
"""
    },
    # ── RULE 8: Engagement index radar-style → grouped bar ────────────────────
    {
        "question": "What is the employee engagement and wellbeing index by department?",
        "sql": """
            SELECT d.department_name,
                   ROUND(AVG(s.JobSatisfaction), 2)         AS avg_job_satisfaction,
                   ROUND(AVG(s.WorkLifeBalance), 2)          AS avg_work_life_balance,
                   ROUND(AVG(s.EnvironmentSatisfaction), 2)  AS avg_environment_satisfaction,
                   ROUND((AVG(s.JobSatisfaction) + AVG(s.WorkLifeBalance) +
                          AVG(s.EnvironmentSatisfaction) + AVG(s.RelationshipSatisfaction)) / 4, 2)
                   AS engagement_index
            FROM satisfaction s
            JOIN employees e  ON s.employee_id = e.employee_id
            JOIN departments d ON e.department_id = d.department_id
            GROUP BY d.department_name ORDER BY engagement_index DESC
        """,
        "plotly_code": """
import plotly.express as px
import pandas as pd
metrics = ['avg_job_satisfaction', 'avg_work_life_balance', 'avg_environment_satisfaction']
df_long = df.melt(id_vars='department_name', value_vars=metrics,
                  var_name='dimension', value_name='score')
df_long['dimension'] = df_long['dimension'].str.replace('avg_', '').str.replace('_', ' ').str.title()
fig = px.bar(
    df_long,
    x='department_name',
    y='score',
    color='dimension',
    barmode='group',
    title='Engagement Dimensions by Department',
    text=df_long['score'].round(2),
    color_discrete_sequence=['#ff8b00', '#383838', '#5b8db8'],
)
fig.update_traces(textposition='outside')
fig.update_layout(xaxis_title='', yaxis_title='Score (1–4)',
                  yaxis_range=[0, 5], legend_title='Dimension')
"""
    },
]


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n── HR Copilot — Vanna Training ──────────────────────────────")

    if not CHROMA_AVAILABLE:
        print("ERROR: chromadb no está instalado (el entrenamiento es solo local).")
        print("Instálalo con: pip install chromadb")
        sys.exit(1)

    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}")
        print("Run setup/build_database.py first.")
        sys.exit(1)

    print("\n[1/5] Initializing Vanna + Gemini...")
    vn = HRCopilot(config={
        "api_key":                  API_KEY,
        "model":                    "gemini-2.5-flash",
        "chroma_persist_directory": CHROMA_DIR,
    })

    # Direct SQLite connection (avoid connect_to_sqlite path issues on macOS)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    vn.run_sql = lambda sql: pd.read_sql_query(sql, conn)
    vn.run_sql_is_set = True
    print("  Vanna initialized.")

    print("\n[2/5] Training with DDL schema (core + synthetic)...")
    vn.train(ddl=DDL)
    vn.train(ddl=DDL_SYNTH)
    print("  DDL trained.")

    print("\n[3/5] Training with business documentation...")
    vn.train(documentation=DOCUMENTATION)
    vn.train(documentation=KPI_DOCUMENTATION)
    vn.train(documentation=SYNTH_DOCUMENTATION)
    print("  Documentation trained.")

    print("\n[4/5] Training with SQL examples...")
    for ex in EXAMPLES:
        vn.train(question=ex["question"], sql=ex["sql"])
    print(f"  {len(EXAMPLES)} base examples trained.")

    for ex in KPI_EXAMPLES:
        vn.train(question=ex["question"], sql=ex["sql"])
    print(f"  {len(KPI_EXAMPLES)} KPI examples trained.")

    for ex in SYNTH_EXAMPLES:
        vn.train(question=ex["question"], sql=ex["sql"])
    print(f"  {len(SYNTH_EXAMPLES)} synthetic-table examples trained.")

    print("\n[5/5] Training with Plotly visualization rules and examples...")
    # Train the visualization rules as documentation so Gemini internalizes them
    vn.train(documentation=VISUALIZATION_DOCUMENTATION)
    print("  Visualization rules trained.")

    # Train each Plotly example — question+sql as the anchor, plotly_code as the target
    for ex in PLOTLY_EXAMPLES:
        vn.train(
            question=ex["question"],
            sql=ex["sql"],
            # Store the plotly_code as additional documentation tied to this Q+SQL pair.
            # This shapes how generate_plotly_code() responds for similar queries.
        )
        # Also train the plotly code as documentation with explicit Q context
        vn.train(
            documentation=(
                f"For the question '{ex['question']}', "
                f"after running this SQL:\n{ex['sql'].strip()}\n"
                f"the correct Plotly visualization code is:\n{ex['plotly_code'].strip()}"
            )
        )
    print(f"  {len(PLOTLY_EXAMPLES)} Plotly examples trained.")

    total = len(EXAMPLES) + len(KPI_EXAMPLES) + len(SYNTH_EXAMPLES) + len(PLOTLY_EXAMPLES)
    print(f"\n  Total training entries: {total} examples + 3 documentation blocks")
    print(f"  ChromaDB saved to: {CHROMA_DIR}")
    print("\n── Training complete. You can now run: python app/dashboard.py ──\n")
