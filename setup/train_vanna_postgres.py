"""
train_vanna_postgres.py
-----------------------
Entrena ChromaDB con el esquema de NovaTech Colombia (PostgreSQL).

Incluye:
  - DDL de las 9 vistas semánticas
  - Documentación de cada dominio HR
  - 1 ejemplo SQL por cada KPI del catálogo (41 de 44; 3 no tienen datos en el esquema)
  - ~25 ejemplos adicionales de patrones de consulta frecuentes
  - Total: ~66 ejemplos

Uso:
    source .venv/bin/activate
    python setup/train_vanna_postgres.py

Requiere USE_CHROMA=1 en .env para activar ChromaDB en el dashboard.
"""

import os, sys
import pandas as pd
from dotenv import load_dotenv
from vanna.legacy.chromadb.chromadb_vector import ChromaDB_VectorStore
from vanna.legacy.base.base import VannaBase

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_provider import GeminiProvider, get_model_name

load_dotenv()

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR    = os.path.dirname(_SCRIPT_DIR)
CHROMA_DIR  = os.path.join(BASE_DIR, "chroma_db")

# ── Clase HRCopilot con ChromaDB ────────────────────────────────────────────
class HRCopilot(ChromaDB_VectorStore, VannaBase):
    def __init__(self, config=None):
        ChromaDB_VectorStore.__init__(self, config=config)
        VannaBase.__init__(self, config=config)
        self._provider  = GeminiProvider(api_key=config.get("api_key"), model_name=config.get("model"))
        self.model_name = self._provider.model_name
        self.last_input_tokens = self.last_output_tokens = self.last_total_tokens = 0

    def system_message(self, message):    return message
    def user_message(self, message):      return message
    def assistant_message(self, message): return message

    def extract_sql(self, text: str) -> str:
        """Override: devuelve el bloque completo del primer ```sql```
        para no truncar queries con UNION ALL o CTEs."""
        import re
        # Bloque ```sql ... ``` o ``` ... ```
        m = re.search(r"```(?:sql)?\s*\n?(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if m:
            return re.sub(r";\s*$", "", m.group(1).strip())
        # Sin fences: desde el primer WITH o SELECT hasta el final
        m2 = re.search(r"((?:WITH|SELECT)\b.+)", text, re.DOTALL | re.IGNORECASE)
        if m2:
            return re.sub(r";\s*$", "", m2.group(1).strip())
        return text

    def submit_prompt(self, prompt, **kwargs):
        text = (
            "\n".join([p if isinstance(p, str) else str(p) for p in prompt])
            if isinstance(prompt, list) else str(prompt)
        )
        text += (
            "\n\nIMPORTANT — Base de datos: NovaTech Colombia S.A.S. (PostgreSQL). "
            "Usa ÚNICAMENTE estas 9 vistas semánticas (nunca las tablas base directamente): "
            "v_perfil_empleado, v_nomina_mensual, v_asistencia_mensual, v_rotacion_retiros, "
            "v_headcount_historico, v_evaluaciones_desempeno, v_vacantes_reclutamiento, "
            "v_engagement_encuestas, v_capacitaciones. "
            "Para Compa-Ratio puedes hacer JOIN con: niveles_cargo (nivel_id, nombre, salario_min_ref, salario_max_ref). "
            "Para incapacidades ARL usa la tabla: incapacidades (empleado_id, fecha_inicio, dias, tipo). "
            "Para historial salarial usa: salarios (empleado_id, salario_basico, fecha_vigencia, motivo). "
            "Para financials usa: financials_empresa (periodo, ingresos_operacionales, gasto_nomina). "
            "Periodos en DATE se almacenan como primer día del mes: '2026-08-01'. "
            "Usa sintaxis PostgreSQL. No uses comillas dobles para strings. "
            "Nunca inventes nombres de columnas o tablas."
        )
        resp_text, tokens_in, tokens_out = self._provider.generate(text)
        self.last_input_tokens  = tokens_in
        self.last_output_tokens = tokens_out
        self.last_total_tokens  = tokens_in + tokens_out
        return resp_text


# ══════════════════════════════════════════════════════════════════════════════
# DDL — Definición de las 9 vistas semánticas
# ══════════════════════════════════════════════════════════════════════════════
DDL_VISTAS = """
-- v_perfil_empleado
-- Columnas: empleado_id, nombre_completo, genero (M/F), edad, nivel_educativo,
--   estado_civil, estado_empleo (activo/retirado), tipo_contrato, fecha_ingreso,
--   fecha_retiro, anos_empresa, cargo, nivel_cargo, nivel_orden (1=más alto),
--   departamento, sede, ciudad, es_matriz (bool), salario_actual (COP)

-- v_nomina_mensual
-- Columnas: periodo (DATE, primer día del mes), empleado_id, nombre_completo,
--   departamento, sede, nivel_cargo, salario_basico, auxilio_transporte,
--   valor_horas_extra, bonificaciones, comisiones, deduccion_salud,
--   deduccion_pension, salario_neto, costo_total_empresa (COP)

-- v_asistencia_mensual
-- Columnas: periodo (DATE), empleado_id, nombre_completo, departamento, sede,
--   dias_habiles, dias_trabajados, dias_ausencia, dias_incapacidad,
--   dias_vacaciones, total_horas_extra (numeric), tardanzas (int),
--   tasa_asistencia (% calculado)

-- v_rotacion_retiros
-- Columnas: empleado_id, nombre_completo, genero, fecha_ingreso, fecha_retiro,
--   meses_en_empresa, tipo_retiro (voluntario/involuntario/fin_contrato/jubilacion),
--   motivo_detalle, calificacion_empresa (1-10), cargo, nivel_cargo,
--   departamento, sede

-- v_headcount_historico
-- Columnas: periodo (DATE), mes (TEXT 'YYYY-MM'), departamento, sede,
--   headcount_inicio, ingresos, retiros_voluntarios, retiros_involuntarios,
--   total_retiros, headcount_fin, tasa_rotacion_mensual (%)

-- v_evaluaciones_desempeno
-- Columnas: periodo (TEXT 'YYYY-S1' o 'YYYY-S2'), empleado_id, nombre_completo,
--   departamento, sede, nivel_cargo, cumplimiento_metas (1-5),
--   competencias_tecnicas (1-5), trabajo_equipo (1-5), liderazgo (1-5 / NULL),
--   innovacion (1-5), puntaje_total (1-5), clasificacion
--   (sobresaliente/bueno/satisfactorio/mejorable/deficiente)

-- v_vacantes_reclutamiento
-- Columnas: vacante_id, fecha_apertura, fecha_cierre, estado (abierta/cubierta/cancelada),
--   motivo_apertura, cargo, nivel_cargo, departamento, sede,
--   candidatos_recibidos, candidatos_entrevistados, ofertas_extendidas,
--   dias_abierta, fuente_contratacion (interno/linkedin/referido/bolsa_empleo/headhunter),
--   salario_ofrecido (COP), tasa_aceptacion_pct

-- v_engagement_encuestas
-- Columnas: periodo (TEXT 'YYYY-QN'), nombre_ciclo, departamento, sede,
--   respuestas, total_invitados, tasa_participacion (%), promedio_orgullo (0-10),
--   promedio_enps_raw (0-10), promedio_satisfaccion (0-10), promedio_equilibrio (0-10),
--   promedio_desarrollo (0-10), promedio_retencion (0-10), enps (calculado)

-- v_capacitaciones
-- Columnas: programa_id, programa, categoria (tecnica/habilidades_blandas/seguridad/
--   cumplimiento/liderazgo), modalidad, duracion_horas, costo_unitario (COP),
--   fecha_inicio, fecha_fin, empleado_id, nombre_completo, departamento, sede,
--   estado (inscrito/completado/retirado/reprobado), calificacion (0-100),
--   puntaje_desempeno_pre (1-5), puntaje_desempeno_post (1-5), delta_desempeno

-- Tablas de apoyo (solo para consultas específicas):
-- niveles_cargo: nivel_id, nombre, orden, salario_min_ref, salario_max_ref (COP 2026)
-- salarios: empleado_id, salario_basico, fecha_vigencia, fecha_fin, motivo
-- incapacidades: empleado_id, fecha_inicio, fecha_fin, dias, tipo, diagnostico_cie
-- financials_empresa: periodo, ingresos_operacionales, gasto_nomina, headcount_total
-- saldo_vacaciones: empleado_id, periodo, dias_causados, dias_tomados, dias_pendientes
"""

# ══════════════════════════════════════════════════════════════════════════════
# DOCUMENTACIÓN — Contexto de negocio y reglas importantes
# ══════════════════════════════════════════════════════════════════════════════
DOCUMENTACION = """
NovaTech Colombia S.A.S. — Empresa de tecnología: Data Center y Cloud Storage.
Sede Medellín (casa matriz, 50 empleados): Gerencia, Finanzas, Comercial, RRHH,
  Jurídica, Tecnología Corporativa, Marketing, Transformación Digital.
Sede Bogotá (operaciones, 100 empleados): Datacenter, Soporte, Redes, Ciberseguridad,
  Desarrollo y Sistemas.

Jerarquía (nivel_orden, 1=más alto):
  1=C-Level (gerentes, salario $10M-$20M COP)
  2=Director ($7M-$15M)
  3=Coordinador/Jefe ($5M-$8M)
  4=Profesional/Analista ($3M-$5M)
  5=Técnico ($1.8M-$3M)
  6=Operativo/Auxiliar (SMLV a $2.2M)

Datos temporales: períodos desde 2021-09 hasta 2026-08 (60 meses).
Periodos en las vistas son DATE (primer día del mes): '2026-08-01'.
En v_headcount_historico también existe columna 'mes' TEXT 'YYYY-MM'.
Periodos de evaluación: 'YYYY-S1' (ene-jun) o 'YYYY-S2' (jul-dic).
Periodos de encuesta: 'YYYY-Q1', 'YYYY-Q2', 'YYYY-Q3', 'YYYY-Q4'.

Nómina colombiana: todos los valores en COP.
  costo_total_empresa = salario + prestaciones sociales + aportes parafiscales.
  salario_neto = salario - aportes empleado (salud 4% + pensión 4%).
  El auxilio de transporte aplica solo para salarios ≤ 2 SMLV.

KPIs no disponibles en este esquema (no tienen datos de soporte):
  - Brecha de Competencias [9]: requiere matriz de competencias por cargo.
  - Porcentaje de Cobertura de Turnos [44]: requiere programación de turnos.
  - Índice de Flexibilidad Horaria [48]: requiere registro de modalidades flexibles.
"""

# ══════════════════════════════════════════════════════════════════════════════
# EJEMPLOS — 1 SQL por KPI del catálogo + patrones adicionales
# ══════════════════════════════════════════════════════════════════════════════
EJEMPLOS = [

    # ── ESTRUCTURA Y DEMOGRAFÍA ──────────────────────────────────────────────

    # [KPI-25] Headcount Total
    (
        "¿Cuántos empleados activos tiene NovaTech Colombia hoy?",
        """
SELECT
    sede,
    COUNT(*) AS headcount_activo
FROM v_perfil_empleado
WHERE estado_empleo = 'activo'
GROUP BY sede
UNION ALL
SELECT 'TOTAL', COUNT(*)
FROM v_perfil_empleado
WHERE estado_empleo = 'activo'
ORDER BY sede;
        """,
    ),

    # [KPI-26] Distribución por Rango de Antigüedad
    (
        "¿Cómo se distribuyen los empleados activos por rango de antigüedad?",
        """
SELECT
    CASE
        WHEN anos_empresa < 1  THEN '0 - Menos de 1 año'
        WHEN anos_empresa < 3  THEN '1 - 1 a 3 años'
        WHEN anos_empresa < 5  THEN '2 - 3 a 5 años'
        WHEN anos_empresa < 10 THEN '3 - 5 a 10 años'
        ELSE                        '4 - Más de 10 años'
    END AS rango_antiguedad,
    COUNT(*) AS empleados,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS porcentaje
FROM v_perfil_empleado
WHERE estado_empleo = 'activo'
GROUP BY 1
ORDER BY 1;
        """,
    ),

    # [KPI-27] Índice de Equidad Salarial por Género (Gender Pay Ratio)
    (
        "¿Existe brecha salarial entre hombres y mujeres por nivel de cargo?",
        """
SELECT
    nivel_cargo,
    ROUND(AVG(CASE WHEN genero = 'F' THEN salario_actual END)) AS salario_promedio_mujeres,
    ROUND(AVG(CASE WHEN genero = 'M' THEN salario_actual END)) AS salario_promedio_hombres,
    COUNT(CASE WHEN genero = 'F' THEN 1 END) AS total_mujeres,
    COUNT(CASE WHEN genero = 'M' THEN 1 END) AS total_hombres,
    ROUND(
        AVG(CASE WHEN genero = 'F' THEN salario_actual END) * 100.0 /
        NULLIF(AVG(CASE WHEN genero = 'M' THEN salario_actual END), 0), 1
    ) AS ratio_equidad_pct
FROM v_perfil_empleado
WHERE estado_empleo = 'activo'
GROUP BY nivel_cargo, nivel_orden
ORDER BY nivel_orden;
        """,
    ),

    # [KPI-28] Distribución Demográfica y Diversidad
    (
        "¿Cuál es la distribución demográfica de los empleados por género, sede y nivel educativo?",
        """
SELECT
    sede,
    genero,
    nivel_educativo,
    COUNT(*) AS empleados,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY sede), 1) AS pct_sobre_sede
FROM v_perfil_empleado
WHERE estado_empleo = 'activo'
GROUP BY sede, genero, nivel_educativo
ORDER BY sede, genero, empleados DESC;
        """,
    ),

    # [KPI-33] Proyección de Headcount
    (
        "¿Cuál es la proyección de headcount para los próximos 3 meses basada en la tendencia reciente?",
        """
WITH ultimos_6m AS (
    SELECT
        periodo,
        SUM(headcount_fin) AS headcount,
        ROW_NUMBER() OVER (ORDER BY MIN(periodo)) AS n
    FROM v_headcount_historico
    WHERE periodo >= CURRENT_DATE - INTERVAL '6 months'
    GROUP BY periodo
),
regresion AS (
    SELECT
        REGR_SLOPE(headcount, n)     AS pendiente,
        REGR_INTERCEPT(headcount, n) AS intercepto,
        MAX(n)                       AS ultimo_n,
        MAX(headcount)               AS ultimo_hc
    FROM ultimos_6m
)
SELECT
    TO_CHAR(CURRENT_DATE + (i || ' months')::INTERVAL, 'YYYY-MM') AS mes_proyectado,
    ROUND(intercepto + pendiente * (ultimo_n + i))                 AS headcount_proyectado,
    ultimo_hc                                                      AS headcount_actual
FROM regresion, generate_series(1, 3) AS i
ORDER BY mes_proyectado;
        """,
    ),

    # [KPI-67] Días de Vacaciones Pendientes / Vacation Liability Index
    (
        "¿Cuántos días de vacaciones pendientes tiene cada empleado y cuál es el pasivo total en pesos?",
        """
SELECT
    pe.nombre_completo,
    pe.departamento,
    pe.sede,
    sv.dias_pendientes,
    ROUND(pe.salario_actual / 30.0 * sv.dias_pendientes) AS pasivo_vacaciones_cop
FROM saldo_vacaciones sv
JOIN v_perfil_empleado pe ON pe.empleado_id = sv.empleado_id
WHERE sv.periodo = (SELECT MAX(periodo) FROM saldo_vacaciones)
  AND pe.estado_empleo = 'activo'
  AND sv.dias_pendientes > 0
ORDER BY sv.dias_pendientes DESC;
        """,
    ),

    # ── DESARROLLO Y TALENTO ─────────────────────────────────────────────────

    # [KPI-7] Puntuación Promedio de Desempeño
    (
        "¿Cuál es el puntaje promedio de desempeño por departamento en el último semestre?",
        """
SELECT
    departamento,
    sede,
    COUNT(*)                         AS evaluaciones,
    ROUND(AVG(puntaje_total), 2)     AS puntaje_promedio,
    ROUND(AVG(cumplimiento_metas), 2)    AS metas,
    ROUND(AVG(competencias_tecnicas), 2) AS competencias,
    ROUND(AVG(trabajo_equipo), 2)        AS trabajo_equipo,
    SUM(CASE WHEN clasificacion = 'sobresaliente' THEN 1 ELSE 0 END) AS sobresalientes,
    SUM(CASE WHEN clasificacion IN ('mejorable','deficiente') THEN 1 ELSE 0 END) AS en_riesgo
FROM v_evaluaciones_desempeno
WHERE periodo = (SELECT MAX(periodo) FROM v_evaluaciones_desempeno)
GROUP BY departamento, sede
ORDER BY puntaje_promedio DESC;
        """,
    ),

    # [KPI-11] Tasa de Promoción Interna
    (
        "¿Cuál es la tasa de promoción interna por año? ¿Qué porcentaje de vacantes se cubrió con talento interno?",
        """
SELECT
    DATE_PART('year', fecha_cierre)::int                         AS año,
    COUNT(*)                                                     AS vacantes_cubiertas,
    SUM(CASE WHEN fuente_contratacion = 'interno' THEN 1 ELSE 0 END) AS cubiertas_internamente,
    ROUND(
        SUM(CASE WHEN fuente_contratacion = 'interno' THEN 1.0 ELSE 0 END) /
        NULLIF(COUNT(*), 0) * 100, 1
    )                                                            AS tasa_promocion_interna_pct
FROM v_vacantes_reclutamiento
WHERE estado = 'cubierta'
  AND fecha_cierre IS NOT NULL
GROUP BY 1
ORDER BY 1;
        """,
    ),

    # [KPI-66] Efectividad de Capacitación
    (
        "¿Qué programas de capacitación tuvieron mayor impacto en el desempeño de los empleados?",
        """
SELECT
    programa,
    categoria,
    modalidad,
    COUNT(*)                                         AS participantes_completaron,
    ROUND(AVG(puntaje_desempeno_pre), 2)             AS desempeno_antes,
    ROUND(AVG(puntaje_desempeno_post), 2)            AS desempeno_despues,
    ROUND(AVG(delta_desempeno), 2)                   AS mejora_absoluta,
    ROUND(
        AVG(delta_desempeno) /
        NULLIF(AVG(puntaje_desempeno_pre), 0) * 100, 1
    )                                                AS efectividad_pct
FROM v_capacitaciones
WHERE estado = 'completado'
  AND delta_desempeno IS NOT NULL
GROUP BY programa, categoria, modalidad
ORDER BY efectividad_pct DESC;
        """,
    ),

    # ── GESTIÓN DE ROTACIÓN Y RETENCIÓN ──────────────────────────────────────

    # [KPI-37] Tasa de Ingresos (Hiring Rate)
    (
        "¿Cuál fue la tasa de nuevas contrataciones mes a mes durante el último año?",
        """
SELECT
    mes,
    sede,
    SUM(ingresos)                                               AS nuevas_contrataciones,
    ROUND(AVG((headcount_inicio + headcount_fin) / 2.0))       AS headcount_promedio,
    ROUND(
        SUM(ingresos) * 100.0 /
        NULLIF(AVG((headcount_inicio + headcount_fin) / 2.0), 0), 2
    )                                                           AS tasa_ingresos_pct
FROM v_headcount_historico
WHERE periodo >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY mes, sede, periodo
ORDER BY periodo, sede;
        """,
    ),

    # [KPI-39] Tasa de Rotación General (Turnover Rate)
    (
        "¿Cuál es la tasa de rotación mensual de NovaTech por sede en el último año?",
        """
SELECT
    mes,
    sede,
    SUM(total_retiros)                                          AS bajas_totales,
    SUM(retiros_voluntarios)                                    AS voluntarios,
    SUM(retiros_involuntarios)                                  AS involuntarios,
    ROUND(AVG((headcount_inicio + headcount_fin) / 2.0))       AS headcount_promedio,
    ROUND(
        SUM(total_retiros) * 100.0 /
        NULLIF(AVG((headcount_inicio + headcount_fin) / 2.0), 0), 2
    )                                                           AS tasa_rotacion_mensual_pct
FROM v_headcount_historico
WHERE periodo >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY mes, sede, periodo
ORDER BY periodo, sede;
        """,
    ),

    # [KPI-34] Índice de Riesgo de Fuga (Flight Risk Index)
    (
        "¿Qué empleados tienen mayor riesgo de fuga según ausentismo, horas extra y antigüedad reciente?",
        """
WITH metricas AS (
    SELECT
        pe.empleado_id,
        pe.nombre_completo,
        pe.departamento,
        pe.sede,
        pe.anos_empresa,
        COALESCE(AVG(am.dias_ausencia::numeric / NULLIF(am.dias_habiles, 0)), 0) AS tasa_aus,
        COALESCE(AVG(am.total_horas_extra), 0)                                   AS horas_extra_prom
    FROM v_perfil_empleado pe
    LEFT JOIN v_asistencia_mensual am
           ON am.empleado_id = pe.empleado_id
          AND am.periodo >= CURRENT_DATE - INTERVAL '6 months'
    WHERE pe.estado_empleo = 'activo'
    GROUP BY pe.empleado_id, pe.nombre_completo, pe.departamento, pe.sede, pe.anos_empresa
)
SELECT
    nombre_completo,
    departamento,
    sede,
    ROUND(anos_empresa, 1)                                          AS años_empresa,
    ROUND(tasa_aus * 100, 1)                                        AS ausentismo_pct,
    ROUND(horas_extra_prom, 1)                                      AS horas_extra_prom_mes,
    ROUND(
        (LEAST(tasa_aus / 0.05, 1) * 40) +
        (LEAST(horas_extra_prom / 20.0, 1) * 30) +
        (CASE WHEN anos_empresa < 1 THEN 30 WHEN anos_empresa < 2 THEN 15 ELSE 0 END)
    , 1)                                                             AS indice_riesgo_fuga
FROM metricas
ORDER BY indice_riesgo_fuga DESC
LIMIT 15;
        """,
    ),

    # [KPI-35] Costo Estimado de Rotación
    (
        "¿Cuánto le costó a NovaTech la rotación de personal en el último año? (estimado 6 meses de salario por reemplazo)",
        """
SELECT
    r.tipo_retiro,
    r.departamento,
    COUNT(*)                                                 AS bajas,
    ROUND(AVG(pe.salario_actual))                           AS salario_promedio_cop,
    ROUND(SUM(pe.salario_actual * 6))                       AS costo_rotacion_total_cop,
    ROUND(AVG(pe.salario_actual * 6))                       AS costo_promedio_por_baja_cop
FROM v_rotacion_retiros r
JOIN v_perfil_empleado pe ON pe.empleado_id = r.empleado_id
WHERE r.fecha_retiro >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY r.tipo_retiro, r.departamento
ORDER BY costo_rotacion_total_cop DESC;
        """,
    ),

    # [KPI-43] Índice de Riesgo de Burnout
    (
        "¿Qué departamentos presentan mayor riesgo de burnout considerando horas extra, ausentismo y tardanzas?",
        """
SELECT
    am.departamento,
    am.sede,
    ROUND(AVG(am.total_horas_extra), 1)                                    AS horas_extra_promedio,
    ROUND(AVG(am.dias_ausencia::numeric / NULLIF(am.dias_habiles, 0)) * 100, 1) AS tasa_ausentismo_pct,
    ROUND(AVG(am.tardanzas), 1)                                            AS tardanzas_promedio,
    ROUND(
        LEAST(AVG(am.total_horas_extra) / 25.0, 1) * 40 +
        LEAST(AVG(am.dias_ausencia::numeric / NULLIF(am.dias_habiles, 0)) / 0.08, 1) * 40 +
        LEAST(AVG(am.tardanzas) / 5.0, 1) * 20
    , 1)                                                                   AS indice_burnout_0_100
FROM v_asistencia_mensual am
WHERE am.periodo >= CURRENT_DATE - INTERVAL '3 months'
GROUP BY am.departamento, am.sede
ORDER BY indice_burnout_0_100 DESC;
        """,
    ),

    # ── CLIMA LABORAL Y BIENESTAR ────────────────────────────────────────────

    # [KPI-1] Índice de Compromiso del Empleado
    (
        "¿Cuál es el índice de compromiso (engagement) de los empleados por sede y trimestre?",
        """
SELECT
    periodo,
    sede,
    ROUND(AVG(
        (promedio_orgullo + promedio_satisfaccion + promedio_equilibrio +
         promedio_desarrollo + promedio_retencion) / 5.0
    ), 2)                                     AS indice_engagement_0_10,
    SUM(respuestas)                           AS total_respuestas,
    ROUND(AVG(tasa_participacion), 1)         AS tasa_participacion_pct
FROM v_engagement_encuestas
GROUP BY periodo, sede
ORDER BY periodo, sede;
        """,
    ),

    # [KPI-2] Tasa de Incidentes de Salud Ocupacional
    (
        "¿Cuál es la tasa de incidentes ARL por cada 200,000 horas trabajadas por año?",
        """
WITH horas_año AS (
    SELECT
        DATE_PART('year', periodo)::int     AS año,
        SUM(dias_trabajados * 8)            AS horas_trabajadas
    FROM v_asistencia_mensual
    GROUP BY 1
),
incidentes_año AS (
    SELECT
        DATE_PART('year', fecha_inicio)::int AS año,
        COUNT(*)                             AS num_incidentes
    FROM incapacidades
    WHERE tipo IN ('ARL_accidente', 'ARL_enfermedad')
    GROUP BY 1
)
SELECT
    h.año,
    h.horas_trabajadas,
    COALESCE(i.num_incidentes, 0)                                AS incidentes_arl,
    ROUND(COALESCE(i.num_incidentes, 0) * 200000.0 /
          NULLIF(h.horas_trabajadas, 0), 2)                      AS tasa_incidentes_200k_horas
FROM horas_año h
LEFT JOIN incidentes_año i ON i.año = h.año
ORDER BY h.año;
        """,
    ),

    # [KPI-3] Índice de Bienestar
    (
        "¿Cuál es el índice de bienestar laboral por sede y su evolución trimestral?",
        """
SELECT
    periodo,
    sede,
    ROUND(
        (AVG(promedio_satisfaccion) * 0.25 +
         AVG(promedio_equilibrio)   * 0.30 +
         AVG(promedio_orgullo)      * 0.25 +
         AVG(promedio_retencion)    * 0.20) / 10.0 * 100, 1
    )                                AS indice_bienestar_0_100,
    SUM(respuestas)                  AS empleados_respondieron
FROM v_engagement_encuestas
GROUP BY periodo, sede
ORDER BY periodo, sede;
        """,
    ),

    # [KPI-4] Tasa de Participación en Encuestas de Clima
    (
        "¿Cuál ha sido la tasa de participación en las encuestas de clima por departamento?",
        """
SELECT
    periodo,
    departamento,
    sede,
    SUM(respuestas)                                                   AS respondieron,
    MAX(total_invitados)                                              AS invitados,
    ROUND(SUM(respuestas) * 100.0 / NULLIF(MAX(total_invitados), 0), 1) AS tasa_participacion_pct
FROM v_engagement_encuestas
GROUP BY periodo, departamento, sede
ORDER BY periodo, tasa_participacion_pct DESC;
        """,
    ),

    # [KPI-5] eNPS (Employee Net Promoter Score)
    (
        "¿Cuál es el eNPS de NovaTech por trimestre y cómo ha evolucionado en los últimos 2 años?",
        """
SELECT
    periodo,
    sede,
    SUM(respuestas)       AS total_respuestas,
    ROUND(AVG(enps), 1)   AS enps_promedio
FROM v_engagement_encuestas
WHERE periodo >= '2024-Q1'
GROUP BY periodo, sede
ORDER BY periodo, sede;
        """,
    ),

    # ── EFICIENCIA OPERATIVA RR.HH. ──────────────────────────────────────────

    # [KPI-15] Tasa de Ausentismo
    (
        "¿Cuál es la tasa de ausentismo mensual por departamento en el último año?",
        """
SELECT
    TO_CHAR(periodo, 'YYYY-MM')                                       AS mes,
    departamento,
    sede,
    SUM(dias_ausencia)                                                AS dias_ausentes,
    SUM(dias_habiles)                                                 AS dias_disponibles,
    ROUND(SUM(dias_ausencia) * 100.0 / NULLIF(SUM(dias_habiles), 0), 2) AS tasa_ausentismo_pct
FROM v_asistencia_mensual
WHERE periodo >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY TO_CHAR(periodo, 'YYYY-MM'), departamento, sede, periodo
ORDER BY periodo, tasa_ausentismo_pct DESC;
        """,
    ),

    # [KPI-16] Frecuencia de Horas Extras (Overtime Rate)
    (
        "¿Cuál es la tasa de horas extras sobre horas regulares por departamento?",
        """
SELECT
    TO_CHAR(periodo, 'YYYY-MM')                                             AS mes,
    departamento,
    ROUND(SUM(total_horas_extra), 1)                                        AS horas_extra_totales,
    SUM(dias_trabajados * 8)                                                AS horas_regulares,
    ROUND(SUM(total_horas_extra) * 100.0 /
          NULLIF(SUM(dias_trabajados * 8), 0), 2)                           AS overtime_rate_pct
FROM v_asistencia_mensual
WHERE periodo >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY TO_CHAR(periodo, 'YYYY-MM'), departamento, periodo
ORDER BY periodo, overtime_rate_pct DESC;
        """,
    ),

    # [KPI-17] Costo Total de Ausentismo
    (
        "¿Cuánto le costó el ausentismo a la empresa por departamento en el último año?",
        """
SELECT
    TO_CHAR(am.periodo, 'YYYY-MM')                                 AS mes,
    am.departamento,
    am.sede,
    SUM(am.dias_ausencia)                                          AS dias_ausentes,
    ROUND(AVG(nm.salario_basico / 30.0))                           AS salario_diario_promedio,
    ROUND(SUM(am.dias_ausencia * nm.salario_basico / 30.0))        AS costo_ausentismo_cop
FROM v_asistencia_mensual am
JOIN v_nomina_mensual nm
  ON nm.empleado_id = am.empleado_id
 AND nm.periodo     = am.periodo
WHERE am.periodo >= CURRENT_DATE - INTERVAL '12 months'
  AND am.dias_ausencia > 0
GROUP BY TO_CHAR(am.periodo, 'YYYY-MM'), am.departamento, am.sede, am.periodo
ORDER BY am.periodo, costo_ausentismo_cop DESC;
        """,
    ),

    # [KPI-18] Ratio de Errores en Nómina (simplificado — % meses con incidencias)
    (
        "¿Cuántos ciclos de nómina se procesaron correctamente por año?",
        """
SELECT
    DATE_PART('year', periodo)::int          AS año,
    COUNT(DISTINCT periodo)                  AS ciclos_procesados,
    COUNT(DISTINCT empleado_id)              AS empleados_liquidados,
    SUM(CASE WHEN salario_neto <= 0 THEN 1 ELSE 0 END) AS registros_con_anomalia,
    ROUND(
        (1 - SUM(CASE WHEN salario_neto <= 0 THEN 1.0 ELSE 0 END) /
             NULLIF(COUNT(*), 0)) * 100, 2
    )                                        AS tasa_puntualidad_pct
FROM v_nomina_mensual
GROUP BY 1
ORDER BY 1;
        """,
    ),

    # [KPI-19] Tasa de Ocupación de Plazas (Vacancy Fill Rate)
    (
        "¿Qué porcentaje de las vacantes abiertas han sido cubiertas por año?",
        """
SELECT
    DATE_PART('year', fecha_apertura)::int                                  AS año,
    COUNT(*)                                                                AS total_vacantes,
    SUM(CASE WHEN estado = 'cubierta'  THEN 1 ELSE 0 END)                  AS cubiertas,
    SUM(CASE WHEN estado = 'abierta'   THEN 1 ELSE 0 END)                  AS abiertas,
    SUM(CASE WHEN estado = 'cancelada' THEN 1 ELSE 0 END)                  AS canceladas,
    ROUND(SUM(CASE WHEN estado = 'cubierta' THEN 1.0 ELSE 0 END) /
          NULLIF(COUNT(*), 0) * 100, 1)                                     AS tasa_cobertura_pct
FROM v_vacantes_reclutamiento
GROUP BY 1
ORDER BY 1;
        """,
    ),

    # [KPI-20] Tiempo de Cobertura de Vacante (Time to Fill)
    (
        "¿Cuántos días en promedio tarda NovaTech en cubrir una vacante por nivel de cargo?",
        """
SELECT
    nivel_cargo,
    departamento,
    sede,
    COUNT(*)                      AS vacantes_cubiertas,
    ROUND(AVG(dias_abierta))      AS dias_promedio_cobertura,
    MIN(dias_abierta)             AS minimo_dias,
    MAX(dias_abierta)             AS maximo_dias,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY dias_abierta) AS mediana_dias
FROM v_vacantes_reclutamiento
WHERE estado = 'cubierta'
  AND dias_abierta IS NOT NULL
GROUP BY nivel_cargo, departamento, sede
ORDER BY dias_promedio_cobertura DESC;
        """,
    ),

    # ── NÓMINA Y COMPENSACIÓN ────────────────────────────────────────────────

    # [KPI-51] Compa-Ratio
    (
        "¿Cuál es el compa-ratio de los empleados activos respecto a la banda salarial de su nivel?",
        """
SELECT
    pe.nivel_cargo,
    pe.nombre_completo,
    pe.departamento,
    pe.sede,
    pe.salario_actual,
    nc.salario_min_ref,
    nc.salario_max_ref,
    ROUND((nc.salario_min_ref + nc.salario_max_ref) / 2.0) AS punto_medio_banda,
    ROUND(pe.salario_actual /
          ((nc.salario_min_ref + nc.salario_max_ref) / 2.0), 3)  AS compa_ratio
FROM v_perfil_empleado pe
JOIN niveles_cargo nc ON nc.nombre = pe.nivel_cargo
WHERE pe.estado_empleo = 'activo'
ORDER BY compa_ratio DESC;
        """,
    ),

    # [KPI-53] Costo Promedio por FTE (Average Labor Cost per FTE)
    (
        "¿Cuánto le cuesta en promedio cada empleado a NovaTech por sede y mes?",
        """
SELECT
    TO_CHAR(periodo, 'YYYY-MM')        AS mes,
    sede,
    COUNT(DISTINCT empleado_id)        AS fte,
    ROUND(SUM(costo_total_empresa))    AS costo_total_nomina_cop,
    ROUND(AVG(costo_total_empresa))    AS costo_promedio_por_fte_cop
FROM v_nomina_mensual
WHERE periodo >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY TO_CHAR(periodo, 'YYYY-MM'), sede, periodo
ORDER BY periodo, sede;
        """,
    ),

    # [KPI-54] Salario Medio por Área
    (
        "¿Cuál es el salario promedio por departamento en el mes más reciente?",
        """
SELECT
    departamento,
    sede,
    COUNT(DISTINCT empleado_id)      AS empleados,
    ROUND(AVG(salario_basico))       AS salario_promedio,
    ROUND(MIN(salario_basico))       AS salario_minimo,
    ROUND(MAX(salario_basico))       AS salario_maximo
FROM v_nomina_mensual
WHERE periodo = (SELECT MAX(periodo) FROM v_nomina_mensual)
GROUP BY departamento, sede
ORDER BY salario_promedio DESC;
        """,
    ),

    # [KPI-55] Ratio de Beneficios sobre Salario Base
    (
        "¿Qué porcentaje representan los beneficios (auxilio, bonificaciones, comisiones) sobre el salario base por departamento?",
        """
SELECT
    departamento,
    sede,
    ROUND(SUM(salario_basico))                                               AS masa_salarial_cop,
    ROUND(SUM(auxilio_transporte + bonificaciones + comisiones))             AS total_beneficios_cop,
    ROUND(SUM(auxilio_transporte + bonificaciones + comisiones) * 100.0 /
          NULLIF(SUM(salario_basico), 0), 2)                                 AS ratio_beneficios_pct
FROM v_nomina_mensual
WHERE periodo = (SELECT MAX(periodo) FROM v_nomina_mensual)
GROUP BY departamento, sede
ORDER BY ratio_beneficios_pct DESC;
        """,
    ),

    # [KPI-56] Puntualidad en el Pago de Nómina
    (
        "¿Cuántos ciclos de nómina se han procesado por año y cuál es la cobertura de empleados?",
        """
SELECT
    DATE_PART('year', periodo)::int       AS año,
    COUNT(DISTINCT periodo)               AS ciclos_de_nomina,
    COUNT(DISTINCT empleado_id)           AS empleados_liquidados,
    ROUND(AVG(salario_neto))              AS salario_neto_promedio_cop,
    ROUND(SUM(costo_total_empresa))       AS costo_total_año_cop
FROM v_nomina_mensual
GROUP BY 1
ORDER BY 1;
        """,
    ),

    # [KPI-57] Incremento Salarial Promedio
    (
        "¿Cuál ha sido el incremento salarial promedio por año en NovaTech?",
        """
WITH sal_por_año AS (
    SELECT
        DATE_PART('year', fecha_vigencia)::int AS año,
        ROUND(AVG(salario_basico))             AS salario_promedio
    FROM salarios
    WHERE motivo = 'incremento_ipc'
      AND fecha_vigencia IS NOT NULL
    GROUP BY 1
)
SELECT
    año,
    salario_promedio,
    LAG(salario_promedio) OVER (ORDER BY año)                               AS salario_año_anterior,
    ROUND((salario_promedio - LAG(salario_promedio) OVER (ORDER BY año)) /
          NULLIF(LAG(salario_promedio) OVER (ORDER BY año), 0) * 100, 1)    AS incremento_pct
FROM sal_por_año
ORDER BY año;
        """,
    ),

    # [KPI-58] Costo Total de Nómina sobre Ingresos (Labor Cost Ratio)
    (
        "¿Qué porcentaje de los ingresos de NovaTech se destina al costo laboral mes a mes?",
        """
SELECT
    TO_CHAR(fe.periodo, 'YYYY-MM')                                           AS mes,
    fe.ingresos_operacionales,
    fe.gasto_nomina,
    ROUND(fe.gasto_nomina * 100.0 / NULLIF(fe.ingresos_operacionales, 0), 2) AS labor_cost_ratio_pct
FROM financials_empresa fe
WHERE fe.periodo >= CURRENT_DATE - INTERVAL '24 months'
ORDER BY fe.periodo;
        """,
    ),

    # [KPI-73] Productividad por Costo Laboral (Revenue per Labor Cost)
    (
        "¿Cuántos pesos de ingreso genera NovaTech por cada peso invertido en nómina?",
        """
SELECT
    TO_CHAR(periodo, 'YYYY-MM')                                              AS mes,
    ingresos_operacionales,
    gasto_nomina,
    ROUND(ingresos_operacionales / NULLIF(gasto_nomina, 0), 2)              AS revenue_por_cop_laboral,
    DATE_PART('year', periodo)::int                                          AS año
FROM financials_empresa
WHERE periodo >= CURRENT_DATE - INTERVAL '24 months'
ORDER BY periodo;
        """,
    ),

    # ── PLAZAS Y GESTIÓN DE VACANTES ─────────────────────────────────────────

    # [KPI-60] Costo por Plaza Vacante
    (
        "¿Cuánto le costó a NovaTech cada plaza que estuvo vacante? (estimado 50% de productividad perdida)",
        """
SELECT
    cargo,
    nivel_cargo,
    departamento,
    sede,
    dias_abierta,
    ROUND(salario_ofrecido)                                          AS salario_ofrecido_cop,
    ROUND(salario_ofrecido / 30.0 * dias_abierta * 0.5)            AS costo_plaza_vacante_cop
FROM v_vacantes_reclutamiento
WHERE estado = 'cubierta'
  AND dias_abierta IS NOT NULL
ORDER BY costo_plaza_vacante_cop DESC
LIMIT 10;
        """,
    ),

    # [KPI-61] Tasa de Aceptación de Oferta
    (
        "¿Qué porcentaje de las ofertas laborales extendidas son aceptadas por fuente de reclutamiento?",
        """
SELECT
    fuente_contratacion,
    sede,
    COUNT(*)                                                                  AS vacantes_cubiertas,
    SUM(ofertas_extendidas)                                                   AS ofertas_extendidas,
    ROUND(
        COUNT(*) * 100.0 / NULLIF(SUM(ofertas_extendidas), 0), 1
    )                                                                         AS tasa_aceptacion_pct
FROM v_vacantes_reclutamiento
WHERE estado = 'cubierta'
  AND ofertas_extendidas > 0
GROUP BY fuente_contratacion, sede
ORDER BY tasa_aceptacion_pct DESC;
        """,
    ),

    # [KPI-62] Calidad de Contratación (Quality of Hire)
    (
        "¿Cuál es el desempeño promedio en el primer año de los empleados contratados en 2024?",
        """
WITH nuevos AS (
    SELECT empleado_id, fecha_ingreso
    FROM v_perfil_empleado
    WHERE DATE_PART('year', fecha_ingreso) = 2024
)
SELECT
    pe.nombre_completo,
    pe.cargo,
    pe.departamento,
    pe.sede,
    pe.fecha_ingreso,
    ROUND(AVG(ed.puntaje_total), 2) AS desempeno_primer_año,
    ed.clasificacion
FROM nuevos n
JOIN v_perfil_empleado pe ON pe.empleado_id = n.empleado_id
LEFT JOIN v_evaluaciones_desempeno ed
       ON ed.empleado_id = n.empleado_id
      AND ed.periodo LIKE (DATE_PART('year', n.fecha_ingreso)::text || '%')
GROUP BY pe.nombre_completo, pe.cargo, pe.departamento, pe.sede, pe.fecha_ingreso, ed.clasificacion
ORDER BY desempeno_primer_año DESC NULLS LAST;
        """,
    ),

    # [KPI-64] Tasa de Vacantes Abiertas (Open Position Rate)
    (
        "¿Qué porcentaje de los cargos de NovaTech están actualmente vacantes?",
        """
SELECT
    sede,
    COUNT(*)                                                              AS vacantes_abiertas,
    (SELECT COUNT(*) FROM cargos WHERE activo = TRUE)                     AS cargos_totales,
    ROUND(
        COUNT(*) * 100.0 /
        NULLIF((SELECT COUNT(*) FROM cargos WHERE activo = TRUE), 0), 1
    )                                                                     AS tasa_vacantes_abiertas_pct
FROM v_vacantes_reclutamiento
WHERE estado = 'abierta'
GROUP BY sede;
        """,
    ),

    # ── HORARIOS Y CONTROL DE ASISTENCIA ─────────────────────────────────────

    # [KPI-45] Horas Extra por Empleado (OT Hours per FTE)
    (
        "¿Cuántas horas extra promedio hace cada empleado por departamento mensualmente?",
        """
SELECT
    TO_CHAR(periodo, 'YYYY-MM')              AS mes,
    departamento,
    sede,
    COUNT(DISTINCT empleado_id)              AS empleados_con_horas_extra,
    ROUND(SUM(total_horas_extra), 1)         AS total_horas_extra,
    ROUND(AVG(total_horas_extra), 1)         AS horas_extra_por_empleado
FROM v_asistencia_mensual
WHERE total_horas_extra > 0
  AND periodo >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY TO_CHAR(periodo, 'YYYY-MM'), departamento, sede, periodo
ORDER BY periodo, horas_extra_por_empleado DESC;
        """,
    ),

    # [KPI-47] Tasa de Puntualidad (On-Time Arrival Rate)
    (
        "¿Cuál es la tasa de puntualidad por departamento en el último semestre?",
        """
SELECT
    departamento,
    sede,
    SUM(dias_habiles)                                                        AS dias_habiles_total,
    SUM(tardanzas)                                                           AS total_tardanzas,
    ROUND(
        (SUM(dias_habiles) - SUM(tardanzas)) * 100.0 /
        NULLIF(SUM(dias_habiles), 0), 2
    )                                                                        AS tasa_puntualidad_pct
FROM v_asistencia_mensual
WHERE periodo >= CURRENT_DATE - INTERVAL '6 months'
GROUP BY departamento, sede
ORDER BY tasa_puntualidad_pct ASC;
        """,
    ),

    # [KPI-70] Índice de Horas Extras sobre Nómina
    (
        "¿Qué porcentaje del costo de nómina representan las horas extras por departamento?",
        """
SELECT
    TO_CHAR(periodo, 'YYYY-MM')                                              AS mes,
    departamento,
    ROUND(SUM(valor_horas_extra))                                            AS valor_horas_extra_cop,
    ROUND(SUM(costo_total_empresa))                                          AS costo_nomina_cop,
    ROUND(SUM(valor_horas_extra) * 100.0 /
          NULLIF(SUM(costo_total_empresa), 0), 2)                            AS indice_horas_extra_pct
FROM v_nomina_mensual
WHERE periodo >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY TO_CHAR(periodo, 'YYYY-MM'), departamento, periodo
ORDER BY periodo, indice_horas_extra_pct DESC;
        """,
    ),

    # [KPI-71] Frecuencia de Incapacidades
    (
        "¿Cuántas incapacidades médicas ocurren por empleado al año según tipo (EPS vs ARL)?",
        """
WITH hc_año AS (
    SELECT DATE_PART('year', periodo)::int AS año, ROUND(AVG(headcount_total)) AS hc
    FROM financials_empresa GROUP BY 1
)
SELECT
    DATE_PART('year', i.fecha_inicio)::int  AS año,
    i.tipo,
    COUNT(*)                                AS num_incapacidades,
    SUM(i.dias)                             AS total_dias,
    ROUND(AVG(i.dias), 1)                   AS dias_promedio_por_incapacidad,
    h.hc                                    AS headcount_promedio,
    ROUND(COUNT(*) * 1.0 / NULLIF(h.hc, 0), 3) AS frecuencia_por_empleado
FROM incapacidades i
JOIN hc_año h ON h.año = DATE_PART('year', i.fecha_inicio)
GROUP BY DATE_PART('year', i.fecha_inicio), i.tipo, h.hc
ORDER BY año, tipo;
        """,
    ),


    # ══════════════════════════════════════════════════════════════════════════
    # PATRONES ADICIONALES — Consultas frecuentes de gerencia y RRHH
    # ══════════════════════════════════════════════════════════════════════════

    # Resumen ejecutivo
    (
        "Dame un resumen ejecutivo del estado actual del talento humano en NovaTech",
        """
SELECT
    'Headcount activo'                    AS indicador,
    COUNT(*)::text                        AS valor
FROM v_perfil_empleado WHERE estado_empleo = 'activo'
UNION ALL
SELECT 'Headcount Medellín',
    COUNT(*)::text FROM v_perfil_empleado WHERE estado_empleo='activo' AND sede='Medellín'
UNION ALL
SELECT 'Headcount Bogotá',
    COUNT(*)::text FROM v_perfil_empleado WHERE estado_empleo='activo' AND sede='Bogotá'
UNION ALL
SELECT 'Salario promedio (COP)',
    TO_CHAR(ROUND(AVG(salario_actual)),'FM$999,999,999')
    FROM v_perfil_empleado WHERE estado_empleo='activo'
UNION ALL
SELECT 'Retiros último año',
    COUNT(*)::text FROM v_rotacion_retiros
    WHERE fecha_retiro >= CURRENT_DATE - INTERVAL '12 months'
UNION ALL
SELECT 'Tasa rotación anual',
    ROUND(COUNT(*) * 100.0 /
        (SELECT COUNT(*) FROM v_perfil_empleado WHERE estado_empleo='activo'), 1)::text || '%'
    FROM v_rotacion_retiros WHERE fecha_retiro >= CURRENT_DATE - INTERVAL '12 months';
        """,
    ),

    # Headcount por departamento
    (
        "¿Cuántos empleados tiene cada departamento actualmente?",
        """
SELECT
    departamento,
    sede,
    COUNT(*)                 AS empleados_activos,
    ROUND(AVG(salario_actual)) AS salario_promedio_cop
FROM v_perfil_empleado
WHERE estado_empleo = 'activo'
GROUP BY departamento, sede
ORDER BY sede, empleados_activos DESC;
        """,
    ),

    # Evolución headcount últimos 12 meses
    (
        "¿Cómo ha evolucionado el headcount total mes a mes en el último año?",
        """
SELECT
    mes,
    sede,
    SUM(headcount_fin)    AS headcount,
    SUM(ingresos)         AS entradas,
    SUM(total_retiros)    AS salidas
FROM v_headcount_historico
WHERE periodo >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY mes, sede, periodo
ORDER BY periodo, sede;
        """,
    ),

    # Empleados por nivel de cargo
    (
        "¿Cómo se distribuye la planta por nivel jerárquico en cada sede?",
        """
SELECT
    nivel_cargo,
    nivel_orden,
    sede,
    COUNT(*)                   AS empleados,
    ROUND(AVG(salario_actual)) AS salario_promedio_cop,
    ROUND(AVG(anos_empresa), 1) AS antiguedad_promedio
FROM v_perfil_empleado
WHERE estado_empleo = 'activo'
GROUP BY nivel_cargo, nivel_orden, sede
ORDER BY nivel_orden, sede;
        """,
    ),

    # Empleados con más de 5 años
    (
        "¿Cuáles son los empleados con más de 5 años en la empresa?",
        """
SELECT
    nombre_completo,
    cargo,
    departamento,
    sede,
    ROUND(anos_empresa, 1) AS años_en_empresa,
    fecha_ingreso,
    ROUND(salario_actual)  AS salario_actual_cop
FROM v_perfil_empleado
WHERE estado_empleo = 'activo'
  AND anos_empresa >= 5
ORDER BY anos_empresa DESC;
        """,
    ),

    # Costo total de nómina por mes
    (
        "¿Cuánto fue el costo total de nómina de NovaTech en el último mes?",
        """
SELECT
    TO_CHAR(periodo, 'YYYY-MM')           AS mes,
    sede,
    COUNT(DISTINCT empleado_id)           AS empleados_liquidados,
    ROUND(SUM(salario_basico))            AS masa_salarial_cop,
    ROUND(SUM(costo_total_empresa))       AS costo_total_empresa_cop,
    ROUND(SUM(auxilio_transporte))        AS total_auxilio_transporte,
    ROUND(SUM(valor_horas_extra))         AS total_horas_extra_cop,
    ROUND(SUM(bonificaciones + comisiones)) AS total_variables_cop
FROM v_nomina_mensual
WHERE periodo = (SELECT MAX(periodo) FROM v_nomina_mensual)
GROUP BY TO_CHAR(periodo, 'YYYY-MM'), sede, periodo
ORDER BY sede;
        """,
    ),

    # Comparación Medellín vs Bogotá en ausentismo
    (
        "¿Cuál sede tiene mayor ausentismo? Compara Medellín vs Bogotá en el último año",
        """
SELECT
    sede,
    SUM(dias_ausencia)                                                    AS total_dias_ausencia,
    SUM(dias_habiles)                                                     AS total_dias_habiles,
    ROUND(SUM(dias_ausencia) * 100.0 / NULLIF(SUM(dias_habiles), 0), 2) AS tasa_ausentismo_pct,
    ROUND(AVG(tardanzas), 1)                                              AS tardanzas_promedio_mes
FROM v_asistencia_mensual
WHERE periodo >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY sede
ORDER BY tasa_ausentismo_pct DESC;
        """,
    ),

    # Top departamentos con mayor rotación
    (
        "¿Qué departamentos tienen la mayor rotación de personal en los últimos 2 años?",
        """
SELECT
    departamento,
    sede,
    SUM(total_retiros)                                                         AS total_bajas,
    SUM(retiros_voluntarios)                                                   AS voluntarios,
    SUM(retiros_involuntarios)                                                 AS involuntarios,
    ROUND(AVG(tasa_rotacion_mensual), 2)                                       AS tasa_rotacion_mensual_prom,
    ROUND(SUM(total_retiros) * 100.0 / NULLIF(AVG(headcount_inicio), 0), 1)  AS rotacion_acumulada_pct
FROM v_headcount_historico
WHERE periodo >= CURRENT_DATE - INTERVAL '24 months'
GROUP BY departamento, sede
ORDER BY rotacion_acumulada_pct DESC;
        """,
    ),

    # Contrataciones 2025 por fuente
    (
        "¿Cuántos empleados ingresaron en 2025 y de qué fuente vinieron?",
        """
SELECT
    v.fuente_contratacion,
    v.sede,
    COUNT(*)                        AS contrataciones,
    ROUND(AVG(v.salario_ofrecido))  AS salario_promedio_ofrecido_cop,
    ROUND(AVG(v.dias_abierta))      AS tiempo_promedio_cobertura_dias
FROM v_vacantes_reclutamiento v
WHERE v.estado = 'cubierta'
  AND DATE_PART('year', v.fecha_cierre) = 2025
GROUP BY v.fuente_contratacion, v.sede
ORDER BY contrataciones DESC;
        """,
    ),

    # Motivos de retiro voluntario
    (
        "¿Cuáles son los principales motivos de retiro voluntario en NovaTech?",
        """
SELECT
    motivo_detalle,
    COUNT(*)                                                                 AS retiros,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1)                      AS porcentaje,
    ROUND(AVG(meses_en_empresa), 1)                                          AS permanencia_promedio_meses,
    ROUND(AVG(calificacion_empresa), 1)                                      AS calificacion_empresa_promedio
FROM v_rotacion_retiros
WHERE tipo_retiro = 'voluntario'
GROUP BY motivo_detalle
ORDER BY retiros DESC;
        """,
    ),

    # Tendencia eNPS últimos 4 trimestres
    (
        "¿Cómo ha evolucionado el eNPS de la empresa en el último año por sede?",
        """
SELECT
    periodo,
    sede,
    SUM(respuestas)       AS total_respuestas,
    ROUND(AVG(enps), 1)   AS enps,
    ROUND(AVG(tasa_participacion), 1) AS participacion_pct
FROM v_engagement_encuestas
WHERE periodo >= '2025-Q3'
GROUP BY periodo, sede
ORDER BY periodo, sede;
        """,
    ),

    # Empleados sin evaluación en el último semestre
    (
        "¿Qué empleados activos no tienen evaluación de desempeño en 2026?",
        """
SELECT
    pe.nombre_completo,
    pe.cargo,
    pe.departamento,
    pe.sede,
    pe.fecha_ingreso,
    ROUND(pe.anos_empresa, 1) AS años_empresa
FROM v_perfil_empleado pe
WHERE pe.estado_empleo = 'activo'
  AND pe.empleado_id NOT IN (
      SELECT empleado_id FROM v_evaluaciones_desempeno WHERE periodo LIKE '2026%'
  )
ORDER BY pe.departamento, pe.nombre_completo;
        """,
    ),

    # Inversión en capacitación por área
    (
        "¿Cuánto invirtió NovaTech en capacitación por departamento en el último año?",
        """
SELECT
    departamento,
    sede,
    COUNT(DISTINCT empleado_id)                    AS empleados_capacitados,
    COUNT(DISTINCT programa_id)                    AS programas_distintos,
    SUM(costo_unitario)                            AS inversion_total_cop,
    ROUND(AVG(costo_unitario))                     AS costo_promedio_por_participacion,
    ROUND(SUM(costo_unitario) /
          NULLIF(COUNT(DISTINCT empleado_id), 0))  AS inversion_por_empleado_cop
FROM v_capacitaciones
WHERE estado = 'completado'
  AND fecha_fin >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY departamento, sede
ORDER BY inversion_total_cop DESC;
        """,
    ),

    # Empleados con 3+ capacitaciones completadas
    (
        "¿Qué empleados completaron 3 o más capacitaciones en los últimos 2 años?",
        """
SELECT
    nombre_completo,
    departamento,
    sede,
    COUNT(DISTINCT programa_id)           AS capacitaciones_completadas,
    ROUND(AVG(calificacion), 1)           AS calificacion_promedio,
    ROUND(AVG(delta_desempeno), 2)        AS mejora_desempeno_promedio
FROM v_capacitaciones
WHERE estado = 'completado'
  AND fecha_fin >= CURRENT_DATE - INTERVAL '24 months'
GROUP BY nombre_completo, departamento, sede
HAVING COUNT(DISTINCT programa_id) >= 3
ORDER BY capacitaciones_completadas DESC;
        """,
    ),

    # Distribución de incapacidades por mes
    (
        "¿Cuántos días de incapacidad se han generado por mes en el último año?",
        """
SELECT
    TO_CHAR(fecha_inicio, 'YYYY-MM')   AS mes,
    tipo,
    COUNT(*)                           AS num_incapacidades,
    SUM(dias)                          AS total_dias_incapacidad
FROM incapacidades
WHERE fecha_inicio >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY TO_CHAR(fecha_inicio, 'YYYY-MM'), tipo
ORDER BY mes, tipo;
        """,
    ),

]

# ══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN DE ENTRENAMIENTO
# ══════════════════════════════════════════════════════════════════════════════

def entrenar():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: No se encontró GEMINI_API_KEY ni GOOGLE_API_KEY en .env")
        sys.exit(1)

    print("Inicializando HRCopilot con ChromaDB…")
    print(f"  CHROMA_DIR: {CHROMA_DIR}")
    vn = HRCopilot(config={
        "api_key":                  api_key,
        "model":                    get_model_name(),
        "chroma_persist_directory": CHROMA_DIR,
    })
    print(f"  Modelo: {get_model_name()}")

    # Limpiar entrenamiento previo
    print("Limpiando ChromaDB anterior…")
    try:
        df_prev = vn.get_training_data()
        if len(df_prev) > 0:
            for tid in df_prev["id"].tolist():
                try:
                    vn.remove_training_data(tid)
                except Exception:
                    pass
            print(f"  {len(df_prev)} fragmentos eliminados.")
    except Exception as e:
        print(f"  (Sin entrenamiento previo: {e})")

    # DDL
    print("\n📐 Entrenando DDL de vistas semánticas…")
    vn.train(ddl=DDL_VISTAS)
    print("  DDL cargado.")

    # Documentación
    print("\n📖 Entrenando documentación del negocio…")
    vn.train(documentation=DOCUMENTACION)
    print("  Documentación cargada.")

    # Ejemplos SQL
    print(f"\n💡 Entrenando {len(EJEMPLOS)} ejemplos SQL…")
    ok = 0
    for i, (pregunta, sql) in enumerate(EJEMPLOS, 1):
        try:
            vn.train(question=pregunta.strip(), sql=sql.strip())
            ok += 1
            if i % 10 == 0:
                print(f"  {i}/{len(EJEMPLOS)} ejemplos procesados…")
        except Exception as e:
            print(f"  ⚠️  Error en ejemplo {i}: {e}")

    # Verificar
    print("\n✅ Verificando ChromaDB…")
    df = vn.get_training_data()
    print(f"  Total fragmentos en ChromaDB: {len(df)}")
    print(f"  Ejemplos SQL exitosos: {ok}/{len(EJEMPLOS)}")
    print("\n🎉 Entrenamiento completado. Activa USE_CHROMA=1 en .env para usarlo.")


if __name__ == "__main__":
    entrenar()
