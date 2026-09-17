"""
seed_postgres.py
----------------
Genera datos sintéticos coherentes para NovaTech Colombia S.A.S.:
  - 150 empleados (50 Medellín, 100 Bogotá)
  - 5 años de historia: 2021-09 → 2026-08
  - Salarios en COP con incremento IPC real por año
  - Nombres colombianos con Faker (es_CO)
  - Nómina con cálculo real de aportes laborales colombianos
  - Reproducible: seed fija 42

Uso:
    pip install faker psycopg2-binary python-dotenv
    python setup/seed_postgres.py

Variables de entorno (.env):
    HR_DB_HOST, HR_DB_PORT, HR_DB_NAME, HR_DB_USER, HR_DB_PASSWORD
"""

import os
import random
import math
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import psycopg2
from psycopg2.extras import execute_values
from faker import Faker
from dotenv import load_dotenv

load_dotenv()
random.seed(42)
fake = Faker("es_CO")
fake.seed_instance(42)

# ── Conexión ────────────────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(
        host=os.getenv("HR_DB_HOST", "localhost"),
        port=os.getenv("HR_DB_PORT", "5432"),
        dbname=os.getenv("HR_DB_NAME", "hrcopilot"),
        user=os.getenv("HR_DB_USER", "hruser"),
        password=os.getenv("HR_DB_PASSWORD", ""),
    )

# ── Constantes ──────────────────────────────────────────────────────────────
FECHA_INICIO = date(2021, 9, 1)
FECHA_FIN    = date(2026, 8, 31)
HOY          = date(2026, 9, 15)

# IPC Colombia por año (incremento diciembre-diciembre)
IPC = {2021: 0.054, 2022: 0.131, 2023: 0.093, 2024: 0.052, 2025: 0.045, 2026: 0.04}

# SMLV Colombia por año
SMLV = {2021: 908_526, 2022: 1_000_000, 2023: 1_160_000,
        2024: 1_300_000, 2025: 1_423_500, 2026: 1_500_000}

# Auxilio de transporte (para salarios ≤ 2 SMLV)
AUX_TRANSPORTE = {2021: 106_454, 2022: 117_172, 2023: 140_606,
                  2024: 162_000, 2025: 200_000, 2026: 214_000}

# Tasa ARL según nivel de riesgo: operativos datacenter → clase III (2.436%)
ARL_TASA = {1: 0.00522, 2: 0.01044, 3: 0.02436, 4: 0.04350, 5: 0.06960}

# ── Rangos salariales 2026 (COP) por nivel ──────────────────────────────────
SALARY_2026 = {
    1: (10_000_000, 20_000_000),   # C-Level
    2: (7_000_000,  15_000_000),   # Director
    3: (5_000_000,   8_000_000),   # Coordinador / Jefe
    4: (3_000_000,   5_000_000),   # Profesional / Analista Senior
    5: (1_800_000,   3_000_000),   # Técnico / Analista Jr
    6: (1_500_000,   2_200_000),   # Operativo / Auxiliar
}

# ── Nombres / catálogos de empresa ──────────────────────────────────────────
SEDES = [
    {"nombre": "Medellín", "ciudad": "Medellín", "es_matriz": True,
     "direccion": "Cra. 43A #1-50, El Poblado, Medellín"},
    {"nombre": "Bogotá",   "ciudad": "Bogotá",   "es_matriz": False,
     "direccion": "Cl. 100 #19-61, Bogotá"},
]

# departamento → (sede_nombre, nivel_ids permitidos)
DEPARTAMENTOS = {
    # ── Medellín ─────────────────────────────────────────────────────
    "Gerencia General":          ("Medellín", [1, 4]),
    "Dirección Financiera":      ("Medellín", [2, 3, 4, 5]),
    "Dirección Comercial":       ("Medellín", [2, 3, 4, 5]),
    "Gestión Humana":            ("Medellín", [2, 3, 4, 5]),
    "Jurídica y Cumplimiento":   ("Medellín", [2, 3, 4]),
    "Tecnología Corporativa":    ("Medellín", [2, 3, 4]),
    "Marketing y Comunicaciones":("Medellín", [3, 4, 5]),
    "Transformación Digital":    ("Medellín", [2, 3, 4]),
    # ── Bogotá ───────────────────────────────────────────────────────
    "Operaciones Datacenter":    ("Bogotá",   [3, 4, 5, 6]),
    "Soporte Técnico":           ("Bogotá",   [3, 4, 5, 6]),
    "Redes e Infraestructura":   ("Bogotá",   [3, 4, 5]),
    "Ciberseguridad":            ("Bogotá",   [2, 3, 4]),
    "Desarrollo y Sistemas":     ("Bogotá",   [3, 4, 5]),
}

# cargo → (departamento, nivel)
CARGOS = {
    # Gerencia General
    "Gerente General":              ("Gerencia General",           1),
    "Asistente de Gerencia":        ("Gerencia General",           4),
    # Dirección Financiera
    "Director Financiero":          ("Dirección Financiera",       2),
    "Controller Financiero":        ("Dirección Financiera",       3),
    "Analista Financiero Senior":   ("Dirección Financiera",       4),
    "Analista Financiero Jr":       ("Dirección Financiera",       5),
    "Auxiliar Contable":            ("Dirección Financiera",       5),
    # Dirección Comercial
    "Director Comercial":           ("Dirección Comercial",        2),
    "Gerente de Cuenta Enterprise": ("Dirección Comercial",        3),
    "Ejecutivo de Ventas":          ("Dirección Comercial",        4),
    "Analista de Preventa":         ("Dirección Comercial",        4),
    # Gestión Humana
    "Directora de Gestión Humana":  ("Gestión Humana",             2),
    "Coordinador RRHH":             ("Gestión Humana",             3),
    "Analista de Selección":        ("Gestión Humana",             4),
    "Analista de Nómina":           ("Gestión Humana",             4),
    "Auxiliar RRHH":                ("Gestión Humana",             5),
    # Jurídica
    "Director Jurídico":            ("Jurídica y Cumplimiento",    2),
    "Abogado Corporativo":          ("Jurídica y Cumplimiento",    4),
    "Analista de Cumplimiento":     ("Jurídica y Cumplimiento",    4),
    # Tecnología Corporativa
    "Director de TI":               ("Tecnología Corporativa",     2),
    "Arquitecto de Soluciones":     ("Tecnología Corporativa",     3),
    "Ingeniero Cloud Senior":       ("Tecnología Corporativa",     4),
    # Marketing
    "Gerente de Marketing":         ("Marketing y Comunicaciones", 3),
    "Diseñador UX/UI":              ("Marketing y Comunicaciones", 4),
    "Community Manager":            ("Marketing y Comunicaciones", 5),
    # Transformación Digital
    "Director de Innovación":       ("Transformación Digital",     2),
    "Líder de Proyectos PMO":       ("Transformación Digital",     3),
    "Analista de Datos":            ("Transformación Digital",     4),
    # Operaciones Datacenter
    "Coordinador de Operaciones":   ("Operaciones Datacenter",     3),
    "Técnico Datacenter Senior":    ("Operaciones Datacenter",     4),
    "Técnico Datacenter Jr":        ("Operaciones Datacenter",     5),
    "Operador de Plataforma":       ("Operaciones Datacenter",     6),
    # Soporte Técnico
    "Coordinador de Soporte":       ("Soporte Técnico",            3),
    "Ingeniero de Soporte N2":      ("Soporte Técnico",            4),
    "Técnico de Soporte N1":        ("Soporte Técnico",            5),
    "Auxiliar Help Desk":           ("Soporte Técnico",            6),
    # Redes
    "Coordinador de Redes":         ("Redes e Infraestructura",    3),
    "Ingeniero de Redes Senior":    ("Redes e Infraestructura",    4),
    "Técnico de Redes":             ("Redes e Infraestructura",    5),
    # Ciberseguridad
    "Director de Ciberseguridad":   ("Ciberseguridad",             2),
    "Analista de Seguridad Senior": ("Ciberseguridad",             4),
    "Analista de Seguridad Jr":     ("Ciberseguridad",             4),
    # Desarrollo
    "Coordinador de Desarrollo":    ("Desarrollo y Sistemas",      3),
    "Desarrollador Senior":         ("Desarrollo y Sistemas",      4),
    "Desarrollador Jr":             ("Desarrollo y Sistemas",      5),
}

# Headcount objetivo por departamento (activos a ago-2026)
HEADCOUNT_TARGET = {
    "Gerencia General":           3,
    "Dirección Financiera":       7,
    "Dirección Comercial":        9,
    "Gestión Humana":             6,
    "Jurídica y Cumplimiento":    4,
    "Tecnología Corporativa":     5,
    "Marketing y Comunicaciones": 5,
    "Transformación Digital":     6,  # Medellín total: ~45 activos + histórico
    "Operaciones Datacenter":    30,
    "Soporte Técnico":           22,
    "Redes e Infraestructura":   18,
    "Ciberseguridad":            12,
    "Desarrollo y Sistemas":     18,  # Bogotá total: ~100 activos
}

DIAS_HABILES = {1:23,2:20,3:23,4:22,5:23,6:22,7:23,8:22,9:22,10:23,11:21,12:21}

MOTIVOS_RETIRO_VOL = [
    "Mejor oferta salarial", "Oportunidad de crecimiento externo",
    "Cambio de ciudad", "Proyecto personal / emprendimiento",
    "Continuación de estudios", "Conflicto con jefe inmediato",
    "Salario no competitivo",
]
MOTIVOS_RETIRO_INV = [
    "Bajo desempeño sostenido", "Incumplimiento de políticas",
    "Reestructuración del área", "Reducción de costos",
    "Conducta inapropiada",
]

PROVEEDORES_CAP = [
    "Platzi for Business", "Coursera for Teams", "LinkedIn Learning",
    "Udemy Business", "Sena Virtual", "Universidad EAFIT",
    "Cámara de Comercio de Medellín", "Consultoría Interna",
]

PROGRAMAS_CAPACITACION = [
    ("Fundamentos de Cloud Computing", "tecnica",         "virtual",    40, 350_000),
    ("Ciberseguridad Corporativa",     "seguridad",       "mixto",      24, 280_000),
    ("Habilidades de Liderazgo",       "liderazgo",       "presencial", 16, 420_000),
    ("Gestión de Proyectos Ágiles",    "tecnica",         "virtual",    20, 180_000),
    ("Comunicación Efectiva",          "habilidades_blandas", "virtual",12, 120_000),
    ("Excel Avanzado y Power BI",      "tecnica",         "virtual",    16, 150_000),
    ("Prevención de Riesgos",          "cumplimiento",    "presencial",  8,  80_000),
    ("Protección de Datos GDPR/LGPD",  "cumplimiento",    "virtual",    12, 160_000),
    ("Negociación y Ventas",           "habilidades_blandas", "mixto",  16, 200_000),
    ("Redes Cisco CCNA",               "tecnica",         "presencial", 80, 900_000),
    ("DevOps y CI/CD",                 "tecnica",         "virtual",    32, 400_000),
    ("Pensamiento Crítico",            "habilidades_blandas", "virtual",10, 100_000),
]

# ── Helpers ─────────────────────────────────────────────────────────────────

def primer_dia(year, month):
    return date(year, month, 1)

def meses_entre(d1, d2):
    """Lista de fechas (primer día de cada mes) entre d1 y d2 inclusive."""
    meses = []
    cur = primer_dia(d1.year, d1.month)
    fin = primer_dia(d2.year, d2.month)
    while cur <= fin:
        meses.append(cur)
        cur += relativedelta(months=1)
    return meses

def salario_en_anno(salario_2026, anno):
    """Retrocede el salario 2026 aplicando IPC inverso hasta el año dado."""
    sal = salario_2026
    for y in range(2026, anno, -1):
        sal = sal / (1 + IPC.get(y, 0.05))
    return round(sal / 1000) * 1000  # redondea a miles

def calcular_nomina(salario_basico, anno, nivel_riesgo_arl=2):
    """Calcula los componentes de nómina colombiana."""
    smlv = SMLV[anno]
    aux  = AUX_TRANSPORTE[anno] if salario_basico <= 2 * smlv else 0
    # Deducciones del empleado
    ded_salud    = round(salario_basico * 0.04)
    ded_pension  = round(salario_basico * 0.04)
    # Aportes empleador
    ap_salud_emp = round(salario_basico * 0.085)
    ap_pen_emp   = round(salario_basico * 0.12)
    ap_arl       = round(salario_basico * ARL_TASA[nivel_riesgo_arl])
    ap_caja      = round(salario_basico * 0.04)
    salario_neto = salario_basico + aux - ded_salud - ded_pension
    costo_total  = salario_basico + aux + ap_salud_emp + ap_pen_emp + ap_arl + ap_caja
    return {
        "aux": aux, "ded_salud": ded_salud, "ded_pension": ded_pension,
        "ap_salud_emp": ap_salud_emp, "ap_pen_emp": ap_pen_emp,
        "ap_arl": ap_arl, "ap_caja": ap_caja,
        "salario_neto": salario_neto, "costo_total": costo_total,
    }

def generar_cedula():
    return str(random.randint(1_000_000_000, 1_299_999_999))

def clasificar_desempeno(puntaje):
    if puntaje >= 4.5: return "sobresaliente"
    if puntaje >= 3.8: return "bueno"
    if puntaje >= 3.0: return "satisfactorio"
    if puntaje >= 2.0: return "mejorable"
    return "deficiente"

# ── Carga principal ─────────────────────────────────────────────────────────

def main():
    conn = get_conn()
    cur  = conn.cursor()

    print("🔧 Limpiando tablas existentes…")
    cur.execute("""
        TRUNCATE TABLE
            financials_empresa, historico_headcount, retiros,
            vacantes, participantes_capacitacion, programas_capacitacion,
            respuestas_encuesta, ciclos_encuesta,
            evaluaciones_desempeno, saldo_vacaciones, vacaciones,
            incapacidades, asistencia_mensual, nomina_mensual,
            salarios, historial_cargos, empleados,
            cargos, niveles_cargo, departamentos, sedes
        RESTART IDENTITY CASCADE
    """)
    conn.commit()

    # ── 1. SEDES ────────────────────────────────────────────────────────────
    print("📍 Insertando sedes…")
    sede_ids = {}
    for s in SEDES:
        cur.execute(
            "INSERT INTO sedes (nombre, ciudad, es_matriz, direccion) VALUES (%s,%s,%s,%s) RETURNING sede_id",
            (s["nombre"], s["ciudad"], s["es_matriz"], s["direccion"])
        )
        sede_ids[s["nombre"]] = cur.fetchone()[0]
    conn.commit()

    # ── 2. NIVELES DE CARGO ─────────────────────────────────────────────────
    print("📊 Insertando niveles de cargo…")
    niveles_data = [
        (1, "C-Level",              1, 10_000_000, 20_000_000),
        (2, "Director",             2,  7_000_000, 15_000_000),
        (3, "Coordinador / Jefe",   3,  5_000_000,  8_000_000),
        (4, "Profesional / Analista", 4, 3_000_000, 5_000_000),
        (5, "Técnico",              5,  1_800_000,  3_000_000),
        (6, "Operativo / Auxiliar", 6,  1_500_000,  2_200_000),
    ]
    nivel_ids = {}
    for nid, nombre, orden, smin, smax in niveles_data:
        cur.execute(
            "INSERT INTO niveles_cargo (nombre, orden, salario_min_ref, salario_max_ref) VALUES (%s,%s,%s,%s) RETURNING nivel_id",
            (nombre, orden, smin, smax)
        )
        nivel_ids[nid] = cur.fetchone()[0]
    conn.commit()

    # ── 3. DEPARTAMENTOS ────────────────────────────────────────────────────
    print("🏢 Insertando departamentos…")
    depto_ids = {}
    for nombre, (sede_nombre, _) in DEPARTAMENTOS.items():
        cur.execute(
            "INSERT INTO departamentos (nombre, sede_id) VALUES (%s,%s) RETURNING departamento_id",
            (nombre, sede_ids[sede_nombre])
        )
        depto_ids[nombre] = cur.fetchone()[0]
    conn.commit()

    # ── 4. CARGOS ───────────────────────────────────────────────────────────
    print("💼 Insertando cargos…")
    cargo_ids = {}
    for nombre_cargo, (depto, nivel) in CARGOS.items():
        cur.execute(
            "INSERT INTO cargos (nombre, departamento_id, nivel_id) VALUES (%s,%s,%s) RETURNING cargo_id",
            (nombre_cargo, depto_ids[depto], nivel_ids[nivel])
        )
        cargo_ids[nombre_cargo] = cur.fetchone()[0]
    conn.commit()

    # ── 5. EMPLEADOS ────────────────────────────────────────────────────────
    print("👥 Generando empleados…")

    # Asignar cargos a cada departamento según headcount objetivo
    # Se incluyen ~20% de empleados históricos (ya retirados) para tener rotación
    asignaciones = []   # (cargo_nombre, sede_nombre) → lista de empleados a generar

    for depto, target in HEADCOUNT_TARGET.items():
        sede_nombre = DEPARTAMENTOS[depto][0]
        cargos_depto = [(c, n) for c, (d, n) in CARGOS.items() if d == depto]
        for i in range(target):
            cargo_nombre, nivel = random.choice(cargos_depto)
            asignaciones.append((cargo_nombre, nivel, sede_nombre, depto, "activo"))

    # Históricos retirados (~30 empleados a lo largo de 5 años)
    for _ in range(30):
        depto = random.choice(list(HEADCOUNT_TARGET.keys()))
        sede_nombre = DEPARTAMENTOS[depto][0]
        cargos_depto = [(c, n) for c, (d, n) in CARGOS.items() if d == depto]
        cargo_nombre, nivel = random.choice(cargos_depto)
        asignaciones.append((cargo_nombre, nivel, sede_nombre, depto, "retirado"))

    empleado_records = []
    cedulas_usadas = set()

    for cargo_nombre, nivel, sede_nombre, depto, estado_inicial in asignaciones:
        genero = random.choice(["M", "F"])
        if genero == "M":
            primer_n = fake.first_name_male()
            segundo_n = fake.first_name_male() if random.random() > 0.4 else None
        else:
            primer_n = fake.first_name_female()
            segundo_n = fake.first_name_female() if random.random() > 0.4 else None

        primer_a  = fake.last_name()
        segundo_a = fake.last_name() if random.random() > 0.3 else None

        # Edad coherente con nivel
        edad_min = {1: 40, 2: 35, 3: 30, 4: 25, 5: 22, 6: 20}
        edad_max = {1: 62, 2: 58, 3: 52, 4: 45, 5: 38, 6: 35}
        edad = random.randint(edad_min[nivel], edad_max[nivel])
        fnac = HOY - timedelta(days=edad * 365 + random.randint(0, 364))

        # Fecha de ingreso
        if estado_inicial == "retirado":
            fi = FECHA_INICIO + timedelta(days=random.randint(0, 365 * 3))
        else:
            max_offset = (HOY - FECHA_INICIO).days - 90
            fi = FECHA_INICIO + timedelta(days=random.randint(0, max_offset))

        tipo_contrato = "indefinido"
        if nivel >= 5 and random.random() < 0.15:
            tipo_contrato = random.choice(["fijo", "obra_labor"])

        cedula = generar_cedula()
        while cedula in cedulas_usadas:
            cedula = generar_cedula()
        cedulas_usadas.add(cedula)

        correo = f"{primer_n.lower().replace(' ','')}.{primer_a.lower()}@novatech.com.co"

        nivel_edu_dist = {
            1: ["maestria", "especializacion", "doctorado"],
            2: ["maestria", "especializacion", "profesional"],
            3: ["especializacion", "profesional"],
            4: ["profesional", "especializacion"],
            5: ["tecnologo", "profesional"],
            6: ["bachiller", "tecnologo"],
        }
        nivel_edu = random.choice(nivel_edu_dist[nivel])

        empleado_records.append({
            "cedula": cedula, "primer_nombre": primer_n, "segundo_nombre": segundo_n,
            "primer_apellido": primer_a, "segundo_apellido": segundo_a,
            "fnac": fnac, "genero": genero,
            "estado_civil": random.choice(["soltero","casado","union_libre","divorciado"]),
            "nivel_educativo": nivel_edu,
            "cargo_nombre": cargo_nombre, "nivel": nivel,
            "sede_nombre": sede_nombre, "depto": depto,
            "estado": estado_inicial, "tipo_contrato": tipo_contrato,
            "fecha_ingreso": fi, "correo": correo,
        })

    emp_ids = {}
    for rec in empleado_records:
        cur.execute("""
            INSERT INTO empleados (
                numero_documento, primer_nombre, segundo_nombre,
                primer_apellido, segundo_apellido,
                fecha_nacimiento, genero, estado_civil, nivel_educativo,
                cargo_actual_id, sede_id, fecha_ingreso,
                estado, tipo_contrato, correo_corporativo
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING empleado_id
        """, (
            rec["cedula"], rec["primer_nombre"], rec["segundo_nombre"],
            rec["primer_apellido"], rec["segundo_apellido"],
            rec["fnac"], rec["genero"], rec["estado_civil"], rec["nivel_educativo"],
            cargo_ids[rec["cargo_nombre"]], sede_ids[rec["sede_nombre"]],
            rec["fecha_ingreso"], rec["estado"], rec["tipo_contrato"], rec["correo"],
        ))
        eid = cur.fetchone()[0]
        emp_ids[eid] = rec
    conn.commit()
    print(f"  {len(emp_ids)} empleados insertados.")

    # ── 6. HISTORIAL DE CARGOS ──────────────────────────────────────────────
    print("📋 Generando historial de cargos…")
    histcargo_rows = []
    for eid, rec in emp_ids.items():
        histcargo_rows.append((
            eid, cargo_ids[rec["cargo_nombre"]], sede_ids[rec["sede_nombre"]],
            rec["fecha_ingreso"], None, "ingreso"
        ))
        # ~15% han tenido un ascenso previo
        if random.random() < 0.15:
            anos_en_empresa = (HOY - rec["fecha_ingreso"]).days / 365
            if anos_en_empresa > 1.5:
                fecha_ascenso = rec["fecha_ingreso"] + timedelta(days=random.randint(365, int(anos_en_empresa * 365 * 0.7)))
                histcargo_rows[-1] = (
                    eid, cargo_ids[rec["cargo_nombre"]], sede_ids[rec["sede_nombre"]],
                    fecha_ascenso, None, "ascenso"
                )
                cargos_nivel_anterior = [
                    (c, n) for c, (d, n) in CARGOS.items()
                    if d == rec["depto"] and n == rec["nivel"] + 1
                ]
                if cargos_nivel_anterior:
                    cargo_ant, _ = random.choice(cargos_nivel_anterior)
                    histcargo_rows.insert(-1, (
                        eid, cargo_ids[cargo_ant], sede_ids[rec["sede_nombre"]],
                        rec["fecha_ingreso"], fecha_ascenso, "ingreso"
                    ))
    execute_values(cur, """
        INSERT INTO historial_cargos (empleado_id, cargo_id, sede_id, fecha_inicio, fecha_fin, motivo_cambio)
        VALUES %s
    """, histcargo_rows)
    conn.commit()

    # ── 7. SALARIOS E HISTORIAL SALARIAL ────────────────────────────────────
    print("💰 Generando historial de salarios…")
    salario_rows = []
    salario_actual = {}  # eid → salario actual

    for eid, rec in emp_ids.items():
        sal_min_26, sal_max_26 = SALARY_2026[rec["nivel"]]
        sal_2026 = round(random.randint(sal_min_26, sal_max_26) / 1000) * 1000

        annos_entrada = rec["fecha_ingreso"].year
        sal_ingreso   = salario_en_anno(sal_2026, annos_entrada)

        # Registro de ingreso
        sal_vigente = sal_ingreso
        fecha_prev  = rec["fecha_ingreso"]
        salario_rows.append((eid, sal_vigente, fecha_prev, None, "ingreso"))

        fecha_fin_rec = rec.get("fecha_retiro") or (HOY if rec["estado"] == "activo" else FECHA_FIN)

        # Incrementos anuales (enero de cada año)
        for y in range(annos_entrada + 1, min(fecha_fin_rec.year + 1, 2027)):
            fecha_inc = date(y, 1, 1)
            if fecha_inc > fecha_fin_rec:
                break
            ipc_y     = IPC.get(y, 0.05)
            sal_nuevo = round(sal_vigente * (1 + ipc_y) / 1000) * 1000
            # Cierra el anterior
            salario_rows[-1] = (salario_rows[-1][0], salario_rows[-1][1], salario_rows[-1][2], fecha_inc - timedelta(days=1), salario_rows[-1][4])
            salario_rows.append((eid, sal_nuevo, fecha_inc, None, "incremento_ipc"))
            sal_vigente = sal_nuevo

        salario_actual[eid] = sal_vigente

    execute_values(cur, """
        INSERT INTO salarios (empleado_id, salario_basico, fecha_vigencia, fecha_fin, motivo)
        VALUES %s
    """, salario_rows)
    conn.commit()

    # ── 8. RETIROS ──────────────────────────────────────────────────────────
    print("🚪 Generando retiros…")
    retiro_rows = []
    for eid, rec in emp_ids.items():
        if rec["estado"] != "retirado":
            continue
        antiguedad_dias = max(30, (HOY - rec["fecha_ingreso"]).days - 90)
        fecha_retiro = rec["fecha_ingreso"] + timedelta(days=random.randint(180, antiguedad_dias))
        if fecha_retiro > HOY:
            fecha_retiro = HOY - timedelta(days=30)

        # Actualiza fecha_retiro en empleados
        cur.execute("UPDATE empleados SET fecha_retiro=%s WHERE empleado_id=%s",
                    (fecha_retiro, eid))
        rec["fecha_retiro"] = fecha_retiro

        tipo = random.choices(
            ["voluntario", "involuntario", "fin_contrato"],
            weights=[0.60, 0.30, 0.10]
        )[0]
        motivo = (random.choice(MOTIVOS_RETIRO_VOL) if tipo == "voluntario"
                  else random.choice(MOTIVOS_RETIRO_INV))
        entrevista = random.random() < 0.70
        calif = random.randint(4, 9) if entrevista else None
        retiro_rows.append((eid, fecha_retiro, tipo, motivo, entrevista, calif, True, random.randint(0, 15)))

    execute_values(cur, """
        INSERT INTO retiros (empleado_id, fecha_retiro, tipo_retiro, motivo_detalle,
                             realizo_entrevista, calificacion_empresa, fue_reemplazado, dias_preaviso)
        VALUES %s
    """, retiro_rows)
    conn.commit()

    # ── 9. NÓMINA Y ASISTENCIA MENSUAL ──────────────────────────────────────
    print("📅 Generando nómina y asistencia mensual (puede tardar ~30 seg)…")
    nomina_rows    = []
    asistencia_rows = []
    saldo_vac_rows  = []
    dias_vac_acum   = {}  # eid → días acumulados

    todos_meses = meses_entre(FECHA_INICIO, date(2026, 8, 1))

    for eid, rec in emp_ids.items():
        fi = rec["fecha_ingreso"]
        fr = rec.get("fecha_retiro") or date(2099, 1, 1)
        dias_vac_acum[eid] = 0.0
        dias_vac_tomados    = 0.0

        for mes in todos_meses:
            if mes < primer_dia(fi.year, fi.month):
                continue
            if mes > primer_dia(min(fr, FECHA_FIN).year, min(fr, FECHA_FIN).month):
                break

            anno = mes.year
            sal_mes = salario_actual.get(eid, SMLV.get(anno, 1_500_000))
            # Ajusta salario al año real de este mes
            sal_mes_hist = salario_en_anno(salario_actual[eid], anno)

            nivel = rec["nivel"]
            arl_riesgo = 3 if nivel >= 5 and DEPARTAMENTOS.get(rec["depto"], ("",))[0] == "Bogotá" else 2
            n = calcular_nomina(sal_mes_hist, anno, arl_riesgo)

            # Horas extra: más frecuentes en Bogotá operativa
            tiene_extra = random.random() < (0.30 if rec["sede_nombre"] == "Bogotá" else 0.15)
            horas_extra = round(random.uniform(2, 20), 1) if tiene_extra else 0
            val_hora    = round(sal_mes_hist / 240 * 1.25)
            val_extra   = round(horas_extra * val_hora) if tiene_extra else 0

            bonif = round(random.uniform(50_000, 300_000)) if random.random() < 0.08 else 0
            comis = 0
            if rec["depto"] == "Dirección Comercial" and random.random() < 0.6:
                comis = round(random.uniform(200_000, 2_000_000))

            salario_neto_final = n["salario_neto"] + val_extra + bonif + comis
            costo_total_final  = n["costo_total"]  + val_extra + bonif + comis

            nomina_rows.append((
                eid, mes, sal_mes_hist, n["aux"],
                horas_extra, val_extra, bonif, comis,
                n["ded_salud"], n["ded_pension"], 0,
                salario_neto_final,
                n["ap_salud_emp"], n["ap_pen_emp"], n["ap_arl"], n["ap_caja"],
                costo_total_final,
            ))

            # Asistencia
            dias_h = DIAS_HABILES.get(mes.month, 22)
            dias_inc  = 1 if random.random() < 0.03 else 0
            dias_ausen = 1 if random.random() < 0.02 else 0
            dias_vac_mes = 0
            if dias_vac_acum[eid] >= 5 and random.random() < 0.04:
                dias_vac_mes = min(5, int(dias_vac_acum[eid]))
                dias_vac_tomados += dias_vac_mes

            dias_trab = dias_h - dias_inc - dias_ausen - dias_vac_mes
            tardanzas = random.randint(0, 2) if random.random() < 0.1 else 0

            asistencia_rows.append((
                eid, mes, dias_h, max(0, dias_trab),
                dias_ausen, dias_inc, dias_vac_mes, 0,
                horas_extra if nivel >= 4 else 0,
                round(horas_extra * 0.3, 1) if nivel >= 4 and tiene_extra else 0,
                tardanzas,
            ))

            # Saldo vacaciones: 1.25 días por mes
            dias_vac_acum[eid] += 1.25
            saldo_pend = round(dias_vac_acum[eid] - dias_vac_tomados, 2)
            saldo_vac_rows.append((eid, mes, round(dias_vac_acum[eid], 2), round(dias_vac_tomados, 2), 0, saldo_pend))

    execute_values(cur, """
        INSERT INTO nomina_mensual (
            empleado_id, periodo, salario_basico, auxilio_transporte,
            horas_extra, valor_horas_extra, bonificaciones, comisiones,
            deduccion_salud, deduccion_pension, otros_descuentos,
            salario_neto, aporte_salud_emp, aporte_pension_emp,
            aporte_arl, aporte_caja_comp, costo_total_empresa
        ) VALUES %s ON CONFLICT DO NOTHING
    """, nomina_rows, page_size=500)

    execute_values(cur, """
        INSERT INTO asistencia_mensual (
            empleado_id, periodo, dias_habiles, dias_trabajados,
            dias_ausencia, dias_incapacidad, dias_vacaciones, dias_licencia,
            horas_extra_diurnas, horas_extra_nocturnas, tardanzas
        ) VALUES %s ON CONFLICT DO NOTHING
    """, asistencia_rows, page_size=500)

    execute_values(cur, """
        INSERT INTO saldo_vacaciones (empleado_id, periodo, dias_causados, dias_tomados, dias_compensados, dias_pendientes)
        VALUES %s ON CONFLICT DO NOTHING
    """, saldo_vac_rows, page_size=500)

    conn.commit()
    print(f"  {len(nomina_rows):,} filas de nómina | {len(asistencia_rows):,} de asistencia.")

    # ── 10. INCAPACIDADES ───────────────────────────────────────────────────
    print("🏥 Generando incapacidades…")
    incap_rows = []
    DIAGNOSTICOS = ["J06.9","M54.5","K29.7","J18.1","A09","Z96.0","S62.0","F32.0","J11","M79.3"]
    for eid, rec in emp_ids.items():
        fi = rec["fecha_ingreso"]
        fr = rec.get("fecha_retiro") or FECHA_FIN
        n_incap = random.choices([0,1,2,3,4], weights=[0.50,0.28,0.12,0.07,0.03])[0]
        rango_dias = (fr - fi).days
        if rango_dias < 10:
            continue
        for _ in range(n_incap):
            fi_inc = fi + timedelta(days=random.randint(30, rango_dias - 5))
            dias   = random.choices([1,2,3,5,7,10,15,30], weights=[0.30,0.20,0.15,0.12,0.10,0.07,0.04,0.02])[0]
            tipo   = random.choices(
                ["EPS","ARL_accidente","ARL_enfermedad","maternidad","paternidad"],
                weights=[0.70, 0.10, 0.08, 0.08, 0.04]
            )[0]
            incap_rows.append((eid, fi_inc, fi_inc + timedelta(days=dias-1), dias,
                               tipo, random.choice(DIAGNOSTICOS), None))
    execute_values(cur, """
        INSERT INTO incapacidades (empleado_id, fecha_inicio, fecha_fin, dias, tipo, diagnostico_cie, descripcion)
        VALUES %s
    """, incap_rows)
    conn.commit()

    # ── 11. EVALUACIONES DE DESEMPEÑO ───────────────────────────────────────
    print("⭐ Generando evaluaciones de desempeño…")
    eval_rows = []
    periodos_eval = []
    y = 2022
    while y <= 2026:
        periodos_eval.append((f"{y}-S1", date(y, 6, 30)))
        if y < 2026:
            periodos_eval.append((f"{y}-S2", date(y, 12, 15)))
        y += 1

    for eid, rec in emp_ids.items():
        fi = rec["fecha_ingreso"]
        fr = rec.get("fecha_retiro") or date(2099, 1, 1)
        nivel = rec["nivel"]
        for periodo_str, fecha_eval in periodos_eval:
            if fecha_eval < fi + timedelta(days=180):
                continue
            if fecha_eval > fr:
                continue
            if random.random() < 0.05:  # 5% no tienen evaluación
                continue
            c1 = round(random.gauss(3.5, 0.7), 1)
            c2 = round(random.gauss(3.5, 0.7), 1)
            c3 = round(random.gauss(3.7, 0.6), 1)
            lid = round(random.gauss(3.4, 0.8), 1) if nivel <= 3 else None
            inn = round(random.gauss(3.3, 0.8), 1)
            for v in [c1, c2, c3, inn]:
                v = max(1.0, min(5.0, v))
            pesos = [c1, c2, c3, inn]
            if lid:
                pesos.append(lid)
            puntaje = round(sum(pesos) / len(pesos), 2)
            puntaje = max(1.0, min(5.0, puntaje))
            eval_rows.append((eid, None, periodo_str, fecha_eval,
                               max(1.0, min(5.0, c1)), max(1.0, min(5.0, c2)),
                               max(1.0, min(5.0, c3)), lid,
                               max(1.0, min(5.0, inn)), puntaje,
                               clasificar_desempeno(puntaje)))
    execute_values(cur, """
        INSERT INTO evaluaciones_desempeno (
            empleado_id, evaluador_id, periodo, fecha_evaluacion,
            cumplimiento_metas, competencias_tecnicas, trabajo_equipo,
            liderazgo, innovacion, puntaje_total, clasificacion
        ) VALUES %s ON CONFLICT DO NOTHING
    """, eval_rows)
    conn.commit()

    # ── 12. ENCUESTAS DE CLIMA ──────────────────────────────────────────────
    print("📊 Generando ciclos de encuesta y respuestas…")
    ciclos_data = []
    q = 1
    y = 2022
    while True:
        ciclo_nombre = f"Encuesta Clima Q{q}-{y}"
        periodo_str  = f"{y}-Q{q}"
        fecha_i = date(y, (q - 1) * 3 + 1, 1)
        fecha_f = fecha_i + timedelta(days=20)
        if fecha_i > FECHA_FIN:
            break
        ciclos_data.append((ciclo_nombre, periodo_str, fecha_i, fecha_f))
        q += 1
        if q > 4:
            q = 1
            y += 1

    ciclo_ids_map = {}
    activos_en_ciclo = {}

    for (nombre, periodo, fi_c, ff_c) in ciclos_data:
        inv = sum(1 for eid, rec in emp_ids.items()
                  if rec["fecha_ingreso"] <= fi_c and
                     (rec.get("fecha_retiro") is None or rec.get("fecha_retiro") > fi_c))
        cur.execute("""
            INSERT INTO ciclos_encuesta (nombre, periodo, fecha_inicio, fecha_cierre, total_invitados)
            VALUES (%s,%s,%s,%s,%s) RETURNING ciclo_id
        """, (nombre, periodo, fi_c, ff_c, inv))
        cid = cur.fetchone()[0]
        ciclo_ids_map[periodo] = (cid, fi_c, ff_c)
        activos_en_ciclo[cid] = [
            eid for eid, rec in emp_ids.items()
            if rec["fecha_ingreso"] <= fi_c and
               (rec.get("fecha_retiro") is None or rec.get("fecha_retiro") > fi_c)
        ]

    resp_rows = []
    for cid, lista_emp in activos_en_ciclo.items():
        fi_c = [v[1] for v in ciclo_ids_map.values() if v[0] == cid][0]
        for eid in lista_emp:
            if random.random() < 0.25:  # 25% no responde
                continue
            rec = emp_ids[eid]
            base = 6.5 if rec["sede_nombre"] == "Bogotá" else 7.2
            def score():
                return max(0, min(10, round(random.gauss(base, 1.5))))
            resp_rows.append((
                cid, eid, fi_c + timedelta(days=random.randint(1, 18)),
                score(), score(), score(), score(), score(), score(), score()
            ))

    execute_values(cur, """
        INSERT INTO respuestas_encuesta (
            ciclo_id, empleado_id, fecha_respuesta,
            orgullo_empresa, recomendaria, satisfaccion_cargo,
            relacion_jefe, equilibrio_vida, oportunidades_desarrollo, intencion_permanencia
        ) VALUES %s ON CONFLICT DO NOTHING
    """, resp_rows)

    # Actualizar total_respondieron
    cur.execute("""
        UPDATE ciclos_encuesta ce
        SET total_respondieron = (
            SELECT COUNT(*) FROM respuestas_encuesta re WHERE re.ciclo_id = ce.ciclo_id
        )
    """)
    conn.commit()

    # ── 13. CAPACITACIONES ──────────────────────────────────────────────────
    print("🎓 Generando programas y participantes de capacitación…")
    prog_ids_map = []
    prog_date = FECHA_INICIO
    for nombre, cat, modalidad, horas, costo in PROGRAMAS_CAPACITACION:
        for _ in range(random.randint(2, 5)):   # cada programa se dicta varias veces
            fi_p = prog_date + timedelta(days=random.randint(0, 60))
            if fi_p > FECHA_FIN:
                break
            duracion = timedelta(days=max(1, horas // 8))
            ff_p = min(fi_p + duracion, FECHA_FIN)
            cur.execute("""
                INSERT INTO programas_capacitacion (nombre, categoria, modalidad, duracion_horas, costo_unitario, proveedor, fecha_inicio, fecha_fin)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING programa_id
            """, (nombre, cat, modalidad, horas, costo, random.choice(PROVEEDORES_CAP), fi_p, ff_p))
            pid = cur.fetchone()[0]
            prog_ids_map.append((pid, fi_p, cat))
            prog_date = fi_p + timedelta(days=random.randint(30, 90))

    partic_rows = []
    for eid, rec in emp_ids.items():
        fi = rec["fecha_ingreso"]
        fr = rec.get("fecha_retiro") or FECHA_FIN
        n_caps = random.choices([0, 1, 2, 3, 4], weights=[0.15, 0.30, 0.30, 0.15, 0.10])[0]
        progs_disp = [(pid, fp, cat) for pid, fp, cat in prog_ids_map if fi <= fp <= fr]
        random.shuffle(progs_disp)
        vistos = set()
        for pid, fp, cat in progs_disp[:n_caps]:
            if pid in vistos:
                continue
            vistos.add(pid)
            estado = random.choices(["completado","retirado","reprobado"], weights=[0.88, 0.08, 0.04])[0]
            calif  = round(random.gauss(78, 15), 1) if estado == "completado" else None
            calif  = max(0, min(100, calif)) if calif else None
            pre  = round(random.uniform(2.5, 4.5), 1)
            post = round(pre + random.gauss(0.3, 0.3), 1) if estado == "completado" else None
            post = max(1.0, min(5.0, post)) if post else None
            partic_rows.append((pid, eid, fp - timedelta(days=5), estado, calif, pre, post))

    execute_values(cur, """
        INSERT INTO participantes_capacitacion (
            programa_id, empleado_id, fecha_inscripcion, estado,
            calificacion, puntaje_desempeno_pre, puntaje_desempeno_post
        ) VALUES %s ON CONFLICT DO NOTHING
    """, partic_rows)
    conn.commit()

    # ── 14. VACANTES ────────────────────────────────────────────────────────
    print("📌 Generando vacantes…")
    vacantes_rows = []
    for eid, rec in emp_ids.items():
        if rec["estado"] != "retirado" or rec.get("fecha_retiro") is None:
            continue
        # Vacante generada por el retiro (reemplazo)
        fr_v = rec["fecha_retiro"]
        dias_abierta = random.randint(15, 90)
        fecha_cierre = fr_v + timedelta(days=dias_abierta)
        if fecha_cierre > FECHA_FIN:
            fecha_cierre = FECHA_FIN
        vacantes_rows.append((
            cargo_ids[rec["cargo_nombre"]], sede_ids[rec["sede_nombre"]],
            fr_v, fecha_cierre, "cubierta", "reemplazo",
            random.randint(5, 40), random.randint(3, 10), random.randint(1, 3),
            None, random.choice(["linkedin","referido","bolsa_empleo","headhunter"]),
            salario_en_anno(SALARY_2026[rec["nivel"]][0], fr_v.year), dias_abierta
        ))

    # Algunas vacantes de expansión
    for _ in range(15):
        cargo_nombre = random.choice(list(CARGOS.keys()))
        depto_v, nivel_v = CARGOS[cargo_nombre]
        sede_v = DEPARTAMENTOS[depto_v][0]
        fa = FECHA_INICIO + timedelta(days=random.randint(30, (FECHA_FIN - FECHA_INICIO).days - 60))
        dias_a = random.randint(20, 75)
        fc = fa + timedelta(days=dias_a)
        estado_v = "cubierta" if fc < date(2026, 6, 1) else "abierta"
        vacantes_rows.append((
            cargo_ids[cargo_nombre], sede_ids[sede_v],
            fa, fc if estado_v == "cubierta" else None,
            estado_v, "expansion",
            random.randint(8, 50), random.randint(4, 12), random.randint(1, 3),
            None, random.choice(["linkedin","referido","bolsa_empleo"]),
            salario_en_anno(SALARY_2026[nivel_v][0], fa.year),
            dias_a if estado_v == "cubierta" else None
        ))

    execute_values(cur, """
        INSERT INTO vacantes (
            cargo_id, sede_id, fecha_apertura, fecha_cierre, estado, motivo_apertura,
            candidatos_recibidos, candidatos_entrevistados, ofertas_extendidas,
            empleado_contratado_id, fuente_contratacion, salario_ofrecido, dias_abierta
        ) VALUES %s
    """, vacantes_rows)
    conn.commit()

    # ── 15. HISTÓRICO HEADCOUNT ─────────────────────────────────────────────
    print("📈 Generando histórico de headcount…")
    hc_rows = []
    for mes in todos_meses:
        for depto_nombre, depto_id in depto_ids.items():
            sede_depto = DEPARTAMENTOS[depto_nombre][0]
            activos = sum(
                1 for eid, rec in emp_ids.items()
                if rec["depto"] == depto_nombre
                and rec["fecha_ingreso"] <= mes
                and (rec.get("fecha_retiro") is None or rec.get("fecha_retiro") > mes)
            )
            retiros_mes = sum(
                1 for eid, rec in emp_ids.items()
                if rec["depto"] == depto_nombre
                and rec.get("fecha_retiro") is not None
                and rec["fecha_retiro"].year == mes.year
                and rec["fecha_retiro"].month == mes.month
            )
            ingresos_mes = sum(
                1 for eid, rec in emp_ids.items()
                if rec["depto"] == depto_nombre
                and rec["fecha_ingreso"].year == mes.year
                and rec["fecha_ingreso"].month == mes.month
            )
            ret_vol = round(retiros_mes * 0.65)
            ret_inv = retiros_mes - ret_vol
            hc_rows.append((
                mes, depto_id, sede_ids[sede_depto],
                max(0, activos - ingresos_mes + retiros_mes),
                ingresos_mes, ret_vol, ret_inv, activos
            ))
    execute_values(cur, """
        INSERT INTO historico_headcount (
            periodo, departamento_id, sede_id, headcount_inicio,
            ingresos, retiros_voluntarios, retiros_involuntarios, headcount_fin
        ) VALUES %s ON CONFLICT DO NOTHING
    """, hc_rows)
    conn.commit()

    # ── 16. FINANCIALS DE LA EMPRESA ────────────────────────────────────────
    print("💹 Generando financials de la empresa…")
    fin_rows = []
    ingresos_base_2021 = 2_500_000_000   # COP 2.5B/mes en 2021
    for mes in todos_meses:
        anno = mes.year
        factor_crecimiento = (1.12 ** (anno - 2021))  # ~12% anual de crecimiento
        ingresos = round(ingresos_base_2021 * factor_crecimiento * random.uniform(0.92, 1.08))
        gasto_nom = sum(
            n_["costo_total"]
            for eid, rec in emp_ids.items()
            if rec["fecha_ingreso"] <= mes and (rec.get("fecha_retiro") is None or rec.get("fecha_retiro") > mes)
            for n_ in [calcular_nomina(salario_en_anno(salario_actual[eid], anno), anno)]
        )
        gasto_cap = sum(
            p[4] for p in partic_rows
            if False  # simplificado: usamos estimado
        )
        gasto_cap_est = round(gasto_nom * random.uniform(0.005, 0.015))
        gasto_bien_est = round(gasto_nom * random.uniform(0.008, 0.020))
        hc = sum(
            1 for eid, rec in emp_ids.items()
            if rec["fecha_ingreso"] <= mes and (rec.get("fecha_retiro") is None or rec.get("fecha_retiro") > mes)
        )
        fin_rows.append((mes, ingresos, round(gasto_nom), gasto_cap_est, gasto_bien_est, hc))

    execute_values(cur, """
        INSERT INTO financials_empresa (
            periodo, ingresos_operacionales, gasto_nomina,
            gasto_capacitacion, gasto_bienestar, headcount_total
        ) VALUES %s ON CONFLICT DO NOTHING
    """, fin_rows)
    conn.commit()

    # ── Resumen ─────────────────────────────────────────────────────────────
    cur.execute("SELECT COUNT(*) FROM empleados")
    print(f"\n✅ Carga completada:")
    print(f"   Empleados:         {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM nomina_mensual")
    print(f"   Registros nómina:  {cur.fetchone()[0]:,}")
    cur.execute("SELECT COUNT(*) FROM asistencia_mensual")
    print(f"   Asistencia:        {cur.fetchone()[0]:,}")
    cur.execute("SELECT COUNT(*) FROM evaluaciones_desempeno")
    print(f"   Evaluaciones:      {cur.fetchone()[0]:,}")
    cur.execute("SELECT COUNT(*) FROM respuestas_encuesta")
    print(f"   Resp. encuestas:   {cur.fetchone()[0]:,}")
    cur.execute("SELECT COUNT(*) FROM retiros")
    print(f"   Retiros:           {cur.fetchone()[0]:,}")

    cur.close()
    conn.close()
    print("\n🎉 Base de datos NovaTech Colombia lista para usar con HR Copilot.")

if __name__ == "__main__":
    main()
