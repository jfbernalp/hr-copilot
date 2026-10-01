"""
build_database.py
-----------------
Downloads the IBM HR Analytics dataset from Kaggle and builds a normalized
SQLite database with 4 relational tables.

Can be run from the project root OR from the setup/ folder:
    python build_database.py
    python setup/build_database.py

Requirements:
    - Kaggle API credentials configured (~/.kaggle/kaggle.json)
      OR manually place the CSV at data/WA_Fn-UseC_-HR-Employee-Attrition.csv
      OR place the CSV in the project root (script will move it automatically)
    - pip install -r requirements.txt
"""

import os
import shutil
import sqlite3
import pandas as pd

# ── Paths — works from any working directory ──────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR    = (
    os.path.dirname(_SCRIPT_DIR)           # ran from setup/
    if os.path.basename(_SCRIPT_DIR) == "setup"
    else _SCRIPT_DIR                       # ran from project root
)
DATA_DIR = os.path.join(BASE_DIR, "data")
CSV_NAME = "WA_Fn-UseC_-HR-Employee-Attrition.csv"
CSV_PATH = os.path.join(DATA_DIR, CSV_NAME)
DB_PATH  = os.path.join(DATA_DIR, "hr_analytics.db")

os.makedirs(DATA_DIR, exist_ok=True)

# If CSV is in the project root, move it to data/ automatically
_root_csv = os.path.join(BASE_DIR, CSV_NAME)
if not os.path.exists(CSV_PATH) and os.path.exists(_root_csv):
    shutil.copy(_root_csv, CSV_PATH)
    print(f"  Copied CSV from project root to data/")


# ── Step 1: Download from Kaggle if CSV not present ──────────────────────────
def download_dataset():
    if os.path.exists(CSV_PATH):
        print(f"  CSV found at {CSV_PATH} — skipping download.")
        return
    try:
        import kaggle
        print("  Downloading IBM HR dataset from Kaggle...")
        kaggle.api.authenticate()
        kaggle.api.dataset_download_files(
            "pavansubhasht/ibm-hr-analytics-attrition-dataset",
            path=DATA_DIR,
            unzip=True
        )
        print("  Download complete.")
    except Exception as e:
        print(f"\n  Could not download automatically: {e}")
        print("  Please download manually from:")
        print("  https://www.kaggle.com/datasets/pavansubhasht/ibm-hr-analytics-attrition-dataset")
        print(f"  and place the CSV at: {CSV_PATH}")
        raise SystemExit(1)


# ── Step 2: Load and validate CSV ────────────────────────────────────────────
def load_csv() -> pd.DataFrame:
    print(f"  Loading CSV from {CSV_PATH}...")
    df = pd.read_csv(CSV_PATH)
    print(f"  Loaded {len(df):,} rows x {len(df.columns)} columns.")
    return df


# ── Step 3: Build normalized tables ──────────────────────────────────────────
def normalize(df: pd.DataFrame) -> dict:
    """
    Splits the flat IBM CSV into 4 relational tables:
      departments  — unique departments (3 rows)
      job_roles    — unique job roles linked to departments (9 rows)
      employees    — one row per employee, demographics + employment facts
      satisfaction — survey scores + performance rating per employee
    """

    # --- departments ---------------------------------------------------------
    departments = (
        df[["Department"]]
        .drop_duplicates()
        .reset_index(drop=True)
        .rename(columns={"Department": "department_name"})
    )
    departments.insert(0, "department_id", range(1, len(departments) + 1))

    # --- job_roles -----------------------------------------------------------
    # Deduplicate by role_name only — some roles (e.g. Manager) appear in
    # multiple departments in the raw data. Keeping the first occurrence
    # avoids a many-to-many merge that inflates the employee row count.
    job_roles = (
        df[["JobRole"]]
        .drop_duplicates()
        .reset_index(drop=True)
        .rename(columns={"JobRole": "role_name"})
    )
    job_roles.insert(0, "role_id", range(1, len(job_roles) + 1))

    # --- employees -----------------------------------------------------------
    # Merge 1: bring department_id onto every employee row
    df2 = df.merge(departments, left_on="Department", right_on="department_name")

    # Merge 2: bring role_id — one-to-one since job_roles is now unique by name
    df2 = df2.merge(
        job_roles[["role_id", "role_name"]],
        left_on="JobRole",
        right_on="role_name"
    )

    employees = df2[[
        "EmployeeNumber", "Age", "Gender", "MaritalStatus", "Education",
        "EducationField", "NumCompaniesWorked", "TotalWorkingYears",
        "YearsAtCompany", "YearsInCurrentRole", "YearsSinceLastPromotion",
        "YearsWithCurrManager", "JobLevel", "MonthlyIncome", "DailyRate",
        "HourlyRate", "MonthlyRate", "PercentSalaryHike", "StockOptionLevel",
        "BusinessTravel", "OverTime", "Attrition",
        "DistanceFromHome", "TrainingTimesLastYear",
        "department_id", "role_id"
    ]].rename(columns={"EmployeeNumber": "employee_id"}).copy()

    # --- satisfaction --------------------------------------------------------
    satisfaction = df2[[
        "EmployeeNumber", "JobSatisfaction", "EnvironmentSatisfaction",
        "RelationshipSatisfaction", "WorkLifeBalance",
        "JobInvolvement", "PerformanceRating"
    ]].rename(columns={"EmployeeNumber": "employee_id"}).copy()

    return {
        "departments":  departments,
        "job_roles":    job_roles,
        "employees":    employees,
        "satisfaction": satisfaction,
    }


# ── Step 4: Write to SQLite ───────────────────────────────────────────────────
def write_sqlite(tables: dict):
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"  Removed existing database.")

    conn = sqlite3.connect(DB_PATH)

    for name in ["departments", "job_roles", "employees", "satisfaction"]:
        df = tables[name]
        df.to_sql(name, conn, index=False, if_exists="replace")
        print(f"  Table '{name}': {len(df):,} rows written.")

    conn.cursor().executescript("""
        CREATE INDEX IF NOT EXISTS idx_emp_dept ON employees(department_id);
        CREATE INDEX IF NOT EXISTS idx_emp_role ON employees(role_id);
        CREATE INDEX IF NOT EXISTS idx_emp_attr ON employees(Attrition);
        CREATE INDEX IF NOT EXISTS idx_sat_emp  ON satisfaction(employee_id);
    """)

    conn.commit()
    conn.close()
    print(f"\n  Database written to: {DB_PATH}")


# ── Step 5: Create query cache table ─────────────────────────────────────────
def create_cache_table():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS query_cache (
            question_hash TEXT PRIMARY KEY,
            question      TEXT NOT NULL,
            sql_generated TEXT NOT NULL,
            result_json   TEXT,
            created_at    TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()
    print("  Query cache table created.")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n-- HR Copilot - Database Setup --")

    print("\n[1/4] Checking dataset...")
    download_dataset()

    print("\n[2/4] Loading CSV...")
    df = load_csv()

    print("\n[3/4] Normalizing into relational tables...")
    tables = normalize(df)
    for name, t in tables.items():
        print(f"  {name}: {len(t)} rows, {len(t.columns)} columns")

    print("\n[4/4] Writing to SQLite...")
    write_sqlite(tables)
    create_cache_table()

    print("\n-- Setup complete. Next step: python setup/train_vanna.py --\n")
