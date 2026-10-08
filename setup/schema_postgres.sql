-- ══════════════════════════════════════════════════════════════════════════════
-- HR Copilot — Esquema PostgreSQL
-- Empresa ficticia: NovaTech Colombia S.A.S.
-- Sector: Tecnología — Data Center y Cloud Storage
-- Sedes: Medellín (50 emp, casa matriz) | Bogotá (100 emp, operaciones)
-- Período de datos: 2021-09 → 2026-08 (5 años de historia)
-- Todos los valores monetarios en COP (pesos colombianos)
-- ══════════════════════════════════════════════════════════════════════════════

-- ── Extensiones ────────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS unaccent;

-- ── Enumeraciones ─────────────────────────────────────────────────────────────
CREATE TYPE genero_tipo         AS ENUM ('M', 'F');
CREATE TYPE estado_emp          AS ENUM ('activo', 'retirado');
CREATE TYPE tipo_contrato_tipo  AS ENUM ('indefinido', 'fijo', 'obra_labor', 'aprendizaje');
CREATE TYPE tipo_retiro_tipo    AS ENUM ('voluntario', 'involuntario', 'jubilacion', 'fin_contrato', 'fallecimiento');
CREATE TYPE estado_vacante      AS ENUM ('abierta', 'cubierta', 'cancelada');
CREATE TYPE motivo_apertura     AS ENUM ('nuevo_cargo', 'reemplazo', 'expansion');
CREATE TYPE fuente_contratacion AS ENUM ('interno', 'linkedin', 'referido', 'bolsa_empleo', 'headhunter');
CREATE TYPE tipo_incapacidad    AS ENUM ('EPS', 'ARL_accidente', 'ARL_enfermedad', 'maternidad', 'paternidad');
CREATE TYPE modalidad_cap       AS ENUM ('virtual', 'presencial', 'mixto');
CREATE TYPE categoria_cap       AS ENUM ('tecnica', 'habilidades_blandas', 'seguridad', 'cumplimiento', 'liderazgo');
CREATE TYPE estado_cap          AS ENUM ('inscrito', 'completado', 'retirado', 'reprobado');
CREATE TYPE motivo_salario      AS ENUM ('ingreso', 'incremento_ipc', 'merito', 'ascenso', 'ajuste_mercado');
CREATE TYPE motivo_cambio_cargo AS ENUM ('ingreso', 'ascenso', 'traslado', 'reestructuracion', 'reemplazo');
CREATE TYPE nivel_desempeno     AS ENUM ('sobresaliente', 'bueno', 'satisfactorio', 'mejorable', 'deficiente');

-- ══════════════════════════════════════════════════════════════════════════════
-- SECCIÓN 1 — CATÁLOGOS BASE
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE sedes (
    sede_id     SERIAL PRIMARY KEY,
    nombre      VARCHAR(100)  NOT NULL,   -- 'Medellín', 'Bogotá'
    ciudad      VARCHAR(100)  NOT NULL,
    es_matriz   BOOLEAN       NOT NULL DEFAULT FALSE,
    direccion   VARCHAR(200),
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  sedes           IS 'Sedes físicas de NovaTech Colombia';
COMMENT ON COLUMN sedes.es_matriz IS 'TRUE = casa matriz (Medellín)';

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE departamentos (
    departamento_id  SERIAL PRIMARY KEY,
    nombre           VARCHAR(100)  NOT NULL,
    sede_id          INTEGER       NOT NULL REFERENCES sedes(sede_id),
    descripcion      TEXT,
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE departamentos IS 'Áreas funcionales de la empresa por sede';

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE niveles_cargo (
    nivel_id       SERIAL PRIMARY KEY,
    nombre         VARCHAR(60)    NOT NULL,   -- 'C-Level', 'Director', 'Coordinador'…
    orden          SMALLINT       NOT NULL,   -- 1=más alto, 6=más bajo
    salario_min_ref NUMERIC(14,2) NOT NULL,   -- referencia 2026 en COP
    salario_max_ref NUMERIC(14,2) NOT NULL
);

COMMENT ON TABLE  niveles_cargo           IS 'Banda jerárquica de cargos con rangos salariales de referencia';
COMMENT ON COLUMN niveles_cargo.orden     IS '1=C-Level, 2=Director, 3=Coordinador/Jefe, 4=Profesional, 5=Técnico, 6=Operativo/Auxiliar';

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE cargos (
    cargo_id        SERIAL PRIMARY KEY,
    nombre          VARCHAR(120)  NOT NULL,
    departamento_id INTEGER       NOT NULL REFERENCES departamentos(departamento_id),
    nivel_id        INTEGER       NOT NULL REFERENCES niveles_cargo(nivel_id),
    descripcion     TEXT,
    activo          BOOLEAN       NOT NULL DEFAULT TRUE
);

COMMENT ON TABLE cargos IS 'Posiciones formales dentro de cada departamento';

-- ══════════════════════════════════════════════════════════════════════════════
-- SECCIÓN 2 — EMPLEADOS Y CONTRATOS
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE empleados (
    empleado_id          SERIAL PRIMARY KEY,
    numero_documento     VARCHAR(12)          UNIQUE NOT NULL,  -- cédula colombiana
    tipo_documento       VARCHAR(5)           NOT NULL DEFAULT 'CC',  -- CC, CE, PA
    primer_nombre        VARCHAR(60)          NOT NULL,
    segundo_nombre       VARCHAR(60),
    primer_apellido      VARCHAR(60)          NOT NULL,
    segundo_apellido     VARCHAR(60),
    fecha_nacimiento     DATE                 NOT NULL,
    genero               genero_tipo          NOT NULL,
    estado_civil         VARCHAR(20),         -- soltero, casado, union_libre, divorciado, viudo
    nivel_educativo      VARCHAR(30),         -- bachiller, tecnologo, profesional, especialista, maestria, doctorado
    cargo_actual_id      INTEGER              REFERENCES cargos(cargo_id),
    sede_id              INTEGER              NOT NULL REFERENCES sedes(sede_id),
    fecha_ingreso        DATE                 NOT NULL,
    fecha_retiro         DATE,
    estado               estado_emp           NOT NULL DEFAULT 'activo',
    tipo_contrato        tipo_contrato_tipo   NOT NULL,
    correo_corporativo   VARCHAR(120),
    telefono             VARCHAR(15),
    ciudad_residencia    VARCHAR(80),
    created_at           TIMESTAMPTZ          NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  empleados                   IS 'Registro maestro de todos los empleados (activos e históricos)';
COMMENT ON COLUMN empleados.numero_documento  IS 'Cédula de ciudadanía — dato ficticio generado';
COMMENT ON COLUMN empleados.cargo_actual_id   IS 'Cargo vigente; NULL si está retirado';

CREATE INDEX idx_empleados_sede     ON empleados(sede_id);
CREATE INDEX idx_empleados_cargo    ON empleados(cargo_actual_id);
CREATE INDEX idx_empleados_estado   ON empleados(estado);
CREATE INDEX idx_empleados_ingreso  ON empleados(fecha_ingreso);

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE historial_cargos (
    historial_id   SERIAL PRIMARY KEY,
    empleado_id    INTEGER              NOT NULL REFERENCES empleados(empleado_id),
    cargo_id       INTEGER              NOT NULL REFERENCES cargos(cargo_id),
    sede_id        INTEGER              NOT NULL REFERENCES sedes(sede_id),
    fecha_inicio   DATE                 NOT NULL,
    fecha_fin      DATE,                            -- NULL = cargo actual
    motivo_cambio  motivo_cambio_cargo  NOT NULL
);

COMMENT ON TABLE  historial_cargos          IS 'Movimientos de cargo: ingresos, ascensos, traslados';
COMMENT ON COLUMN historial_cargos.fecha_fin IS 'NULL indica que es el cargo vigente del empleado';

CREATE INDEX idx_histcargo_empleado ON historial_cargos(empleado_id);
CREATE INDEX idx_histcargo_cargo    ON historial_cargos(cargo_id);

-- ══════════════════════════════════════════════════════════════════════════════
-- SECCIÓN 3 — SALARIOS Y NÓMINA
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE salarios (
    salario_id      SERIAL PRIMARY KEY,
    empleado_id     INTEGER          NOT NULL REFERENCES empleados(empleado_id),
    salario_basico  NUMERIC(14,2)    NOT NULL,
    fecha_vigencia  DATE             NOT NULL,       -- desde cuándo aplica
    fecha_fin       DATE,                            -- NULL = salario actual
    motivo          motivo_salario   NOT NULL
);

COMMENT ON TABLE  salarios               IS 'Historial completo de salarios básicos por empleado';
COMMENT ON COLUMN salarios.fecha_fin     IS 'NULL indica salario vigente';
COMMENT ON COLUMN salarios.motivo        IS 'Razón del cambio salarial';

CREATE INDEX idx_salarios_empleado ON salarios(empleado_id);
CREATE INDEX idx_salarios_vigencia ON salarios(fecha_vigencia);

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE nomina_mensual (
    nomina_id              SERIAL PRIMARY KEY,
    empleado_id            INTEGER        NOT NULL REFERENCES empleados(empleado_id),
    periodo                DATE           NOT NULL,  -- primer día del mes: 2024-01-01
    salario_basico         NUMERIC(14,2)  NOT NULL,
    auxilio_transporte     NUMERIC(14,2)  NOT NULL DEFAULT 0,  -- solo si salario ≤ 2 SMLV
    horas_extra            NUMERIC(8,2)             DEFAULT 0,
    valor_horas_extra      NUMERIC(14,2)            DEFAULT 0,
    bonificaciones         NUMERIC(14,2)            DEFAULT 0,
    comisiones             NUMERIC(14,2)            DEFAULT 0,
    -- Deducciones del empleado
    deduccion_salud        NUMERIC(14,2)  NOT NULL,  -- 4% del salario
    deduccion_pension      NUMERIC(14,2)  NOT NULL,  -- 4% del salario
    otros_descuentos       NUMERIC(14,2)            DEFAULT 0,
    salario_neto           NUMERIC(14,2)  NOT NULL,
    -- Aportes del empleador (costo empresa)
    aporte_salud_emp       NUMERIC(14,2)  NOT NULL,  -- 8.5%
    aporte_pension_emp     NUMERIC(14,2)  NOT NULL,  -- 12%
    aporte_arl             NUMERIC(14,2)  NOT NULL,  -- ~2.436% nivel riesgo II/III
    aporte_caja_comp       NUMERIC(14,2)  NOT NULL,  -- 4% (SENA 2% + ICBF 3% no aplica si > 10 emp, Caja 4%)
    costo_total_empresa    NUMERIC(14,2)  NOT NULL,  -- salario + auxilio + horas_extra + bonif + comis + todos aportes
    UNIQUE (empleado_id, periodo)
);

COMMENT ON TABLE  nomina_mensual              IS 'Liquidación mensual por empleado con devengados, deducciones y aportes patronales';
COMMENT ON COLUMN nomina_mensual.periodo      IS 'Primer día del mes de nómina (ej. 2024-03-01)';
COMMENT ON COLUMN nomina_mensual.salario_neto IS 'Lo que recibe el empleado: basico + auxilio + extras + bonif - deducciones';

CREATE INDEX idx_nomina_empleado ON nomina_mensual(empleado_id);
CREATE INDEX idx_nomina_periodo  ON nomina_mensual(periodo);

-- ══════════════════════════════════════════════════════════════════════════════
-- SECCIÓN 4 — ASISTENCIA E INCAPACIDADES
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE asistencia_mensual (
    asistencia_id          SERIAL PRIMARY KEY,
    empleado_id            INTEGER  NOT NULL REFERENCES empleados(empleado_id),
    periodo                DATE     NOT NULL,
    dias_habiles           SMALLINT NOT NULL,
    dias_trabajados        SMALLINT NOT NULL,
    dias_ausencia          SMALLINT NOT NULL DEFAULT 0,   -- ausencias injustificadas
    dias_incapacidad       SMALLINT NOT NULL DEFAULT 0,
    dias_vacaciones        SMALLINT NOT NULL DEFAULT 0,
    dias_licencia          SMALLINT NOT NULL DEFAULT 0,   -- licencias remuneradas
    horas_extra_diurnas    NUMERIC(6,2)      DEFAULT 0,
    horas_extra_nocturnas  NUMERIC(6,2)      DEFAULT 0,
    tardanzas              SMALLINT          DEFAULT 0,   -- número de llegadas tarde en el mes
    UNIQUE (empleado_id, periodo)
);

COMMENT ON TABLE asistencia_mensual IS 'Consolidado mensual de asistencia, ausencias y horas extra por empleado';

CREATE INDEX idx_asistencia_empleado ON asistencia_mensual(empleado_id);
CREATE INDEX idx_asistencia_periodo  ON asistencia_mensual(periodo);

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE incapacidades (
    incapacidad_id   SERIAL PRIMARY KEY,
    empleado_id      INTEGER           NOT NULL REFERENCES empleados(empleado_id),
    fecha_inicio     DATE              NOT NULL,
    fecha_fin        DATE              NOT NULL,
    dias             SMALLINT          NOT NULL,
    tipo             tipo_incapacidad  NOT NULL,
    diagnostico_cie  VARCHAR(8),                  -- código CIE-10 ej. 'J06.9'
    descripcion      VARCHAR(200),
    CONSTRAINT ck_dias_positivos CHECK (dias > 0),
    CONSTRAINT ck_fechas_incap   CHECK (fecha_fin >= fecha_inicio)
);

COMMENT ON TABLE incapacidades IS 'Registro individual de cada incapacidad médica o licencia de maternidad/paternidad';

CREATE INDEX idx_incap_empleado ON incapacidades(empleado_id);
CREATE INDEX idx_incap_tipo     ON incapacidades(tipo);

-- ══════════════════════════════════════════════════════════════════════════════
-- SECCIÓN 5 — VACACIONES
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE vacaciones (
    vacacion_id       SERIAL PRIMARY KEY,
    empleado_id       INTEGER      NOT NULL REFERENCES empleados(empleado_id),
    fecha_inicio      DATE         NOT NULL,
    fecha_fin         DATE         NOT NULL,
    dias_tomados      SMALLINT     NOT NULL,
    dias_compensados  SMALLINT     NOT NULL DEFAULT 0,  -- pagados en dinero
    estado            VARCHAR(20)  NOT NULL DEFAULT 'aprobado',
    CONSTRAINT ck_fechas_vac CHECK (fecha_fin >= fecha_inicio)
);

COMMENT ON TABLE vacaciones IS 'Períodos de vacaciones tomadas o compensadas en dinero';

CREATE TABLE saldo_vacaciones (
    saldo_id         SERIAL PRIMARY KEY,
    empleado_id      INTEGER       NOT NULL REFERENCES empleados(empleado_id),
    periodo          DATE          NOT NULL,         -- mes de corte
    dias_causados    NUMERIC(7,2)  NOT NULL,         -- 1.25 días × mes trabajado
    dias_tomados     NUMERIC(7,2)  NOT NULL DEFAULT 0,
    dias_compensados NUMERIC(7,2)  NOT NULL DEFAULT 0,
    dias_pendientes  NUMERIC(7,2)  NOT NULL,
    UNIQUE (empleado_id, periodo)
);

COMMENT ON TABLE  saldo_vacaciones              IS 'Saldo mensual de días de vacaciones por empleado';
COMMENT ON COLUMN saldo_vacaciones.dias_causados IS '1.25 días acumulados por mes de trabajo efectivo';

-- ══════════════════════════════════════════════════════════════════════════════
-- SECCIÓN 6 — DESEMPEÑO
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE evaluaciones_desempeno (
    evaluacion_id          SERIAL PRIMARY KEY,
    empleado_id            INTEGER          NOT NULL REFERENCES empleados(empleado_id),
    evaluador_id           INTEGER          REFERENCES empleados(empleado_id),
    periodo                VARCHAR(7)       NOT NULL,   -- 'YYYY-S1' o 'YYYY-S2'
    fecha_evaluacion       DATE             NOT NULL,
    -- Dimensiones 1.0–5.0
    cumplimiento_metas     NUMERIC(3,1)     NOT NULL,
    competencias_tecnicas  NUMERIC(3,1)     NOT NULL,
    trabajo_equipo         NUMERIC(3,1)     NOT NULL,
    liderazgo              NUMERIC(3,1),              -- NULL para no-líderes
    innovacion             NUMERIC(3,1)     NOT NULL,
    puntaje_total          NUMERIC(4,2)     NOT NULL,  -- promedio ponderado
    clasificacion          nivel_desempeno  NOT NULL,
    comentarios            TEXT,
    UNIQUE (empleado_id, periodo),
    CONSTRAINT ck_puntaje CHECK (puntaje_total BETWEEN 1.0 AND 5.0)
);

COMMENT ON TABLE  evaluaciones_desempeno           IS 'Evaluaciones semestrales de desempeño por empleado';
COMMENT ON COLUMN evaluaciones_desempeno.periodo   IS 'YYYY-S1 = primer semestre, YYYY-S2 = segundo semestre';
COMMENT ON COLUMN evaluaciones_desempeno.liderazgo IS 'Solo se evalúa para niveles 1, 2 y 3 (C-Level, Director, Coordinador)';

CREATE INDEX idx_eval_empleado ON evaluaciones_desempeno(empleado_id);
CREATE INDEX idx_eval_periodo  ON evaluaciones_desempeno(periodo);

-- ══════════════════════════════════════════════════════════════════════════════
-- SECCIÓN 7 — CLIMA Y ENGAGEMENT
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE ciclos_encuesta (
    ciclo_id            SERIAL PRIMARY KEY,
    nombre              VARCHAR(120)  NOT NULL,   -- 'Encuesta Clima Q2-2024'
    periodo             VARCHAR(7)    NOT NULL,   -- 'YYYY-QN'
    fecha_inicio        DATE          NOT NULL,
    fecha_cierre        DATE          NOT NULL,
    total_invitados     INTEGER,
    total_respondieron  INTEGER
);

COMMENT ON TABLE ciclos_encuesta IS 'Ciclos trimestrales de encuesta de clima y engagement';

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE respuestas_encuesta (
    respuesta_id              SERIAL PRIMARY KEY,
    ciclo_id                  INTEGER  NOT NULL REFERENCES ciclos_encuesta(ciclo_id),
    empleado_id               INTEGER  NOT NULL REFERENCES empleados(empleado_id),
    fecha_respuesta           DATE,
    -- Escala 0–10
    orgullo_empresa           SMALLINT,  -- "Me siento orgulloso de trabajar aquí"
    recomendaria              SMALLINT,  -- eNPS: "Recomendaría esta empresa a un amigo"
    satisfaccion_cargo        SMALLINT,  -- "Estoy satisfecho con mis funciones"
    relacion_jefe             SMALLINT,  -- "Tengo buena relación con mi jefe inmediato"
    equilibrio_vida           SMALLINT,  -- "Tengo buen equilibrio vida-trabajo"
    oportunidades_desarrollo  SMALLINT,  -- "Veo oportunidades de crecimiento"
    intencion_permanencia     SMALLINT,  -- "Planeo seguir en la empresa el próximo año"
    UNIQUE (ciclo_id, empleado_id),
    CONSTRAINT ck_scores CHECK (
        orgullo_empresa BETWEEN 0 AND 10 AND
        recomendaria    BETWEEN 0 AND 10 AND
        satisfaccion_cargo BETWEEN 0 AND 10
    )
);

COMMENT ON TABLE  respuestas_encuesta             IS 'Respuestas individuales a cada ciclo de encuesta de clima';
COMMENT ON COLUMN respuestas_encuesta.recomendaria IS 'Base del eNPS: promotores ≥9, detractores ≤6';

CREATE INDEX idx_respuesta_ciclo    ON respuestas_encuesta(ciclo_id);
CREATE INDEX idx_respuesta_empleado ON respuestas_encuesta(empleado_id);

-- ══════════════════════════════════════════════════════════════════════════════
-- SECCIÓN 8 — CAPACITACIONES
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE programas_capacitacion (
    programa_id      SERIAL PRIMARY KEY,
    nombre           VARCHAR(200)   NOT NULL,
    categoria        categoria_cap  NOT NULL,
    modalidad        modalidad_cap  NOT NULL,
    duracion_horas   SMALLINT       NOT NULL,
    costo_unitario   NUMERIC(14,2)  NOT NULL,   -- costo por participante en COP
    proveedor        VARCHAR(120),
    fecha_inicio     DATE           NOT NULL,
    fecha_fin        DATE           NOT NULL,
    CONSTRAINT ck_fechas_cap CHECK (fecha_fin >= fecha_inicio)
);

COMMENT ON TABLE programas_capacitacion IS 'Catálogo de programas de formación y capacitación';

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE participantes_capacitacion (
    participacion_id      SERIAL PRIMARY KEY,
    programa_id           INTEGER      NOT NULL REFERENCES programas_capacitacion(programa_id),
    empleado_id           INTEGER      NOT NULL REFERENCES empleados(empleado_id),
    fecha_inscripcion     DATE         NOT NULL,
    estado                estado_cap   NOT NULL DEFAULT 'inscrito',
    calificacion          NUMERIC(5,2),              -- 0.0–100.0
    puntaje_desempeno_pre  NUMERIC(3,1),             -- desempeño antes (1–5)
    puntaje_desempeno_post NUMERIC(3,1),             -- desempeño después (1–5)
    UNIQUE (programa_id, empleado_id)
);

COMMENT ON TABLE participantes_capacitacion IS 'Inscripción y resultados de cada empleado en cada programa';

CREATE INDEX idx_partic_programa  ON participantes_capacitacion(programa_id);
CREATE INDEX idx_partic_empleado  ON participantes_capacitacion(empleado_id);

-- ══════════════════════════════════════════════════════════════════════════════
-- SECCIÓN 9 — RECLUTAMIENTO Y VACANTES
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE vacantes (
    vacante_id               SERIAL PRIMARY KEY,
    cargo_id                 INTEGER              NOT NULL REFERENCES cargos(cargo_id),
    sede_id                  INTEGER              NOT NULL REFERENCES sedes(sede_id),
    fecha_apertura           DATE                 NOT NULL,
    fecha_cierre             DATE,
    estado                   estado_vacante       NOT NULL DEFAULT 'abierta',
    motivo_apertura          motivo_apertura      NOT NULL,
    candidatos_recibidos     INTEGER              DEFAULT 0,
    candidatos_entrevistados INTEGER              DEFAULT 0,
    ofertas_extendidas       INTEGER              DEFAULT 0,
    empleado_contratado_id   INTEGER              REFERENCES empleados(empleado_id),
    fuente_contratacion      fuente_contratacion,
    salario_ofrecido         NUMERIC(14,2),
    dias_abierta             SMALLINT             -- calculado al cerrar
);

COMMENT ON TABLE  vacantes                      IS 'Proceso de reclutamiento por cargo y sede';
COMMENT ON COLUMN vacantes.dias_abierta         IS 'Días transcurridos entre apertura y cierre (time-to-fill)';
COMMENT ON COLUMN vacantes.motivo_apertura      IS 'nuevo_cargo = expansión, reemplazo = alguien se fue, expansion = crecimiento';

CREATE INDEX idx_vacantes_cargo ON vacantes(cargo_id);
CREATE INDEX idx_vacantes_sede  ON vacantes(sede_id);

-- ══════════════════════════════════════════════════════════════════════════════
-- SECCIÓN 10 — HEADCOUNT HISTÓRICO Y RETIROS
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE historico_headcount (
    headcount_id          SERIAL PRIMARY KEY,
    periodo               DATE     NOT NULL,   -- primer día del mes
    departamento_id       INTEGER  NOT NULL REFERENCES departamentos(departamento_id),
    sede_id               INTEGER  NOT NULL REFERENCES sedes(sede_id),
    headcount_inicio      SMALLINT NOT NULL,
    ingresos              SMALLINT NOT NULL DEFAULT 0,
    retiros_voluntarios   SMALLINT NOT NULL DEFAULT 0,
    retiros_involuntarios SMALLINT NOT NULL DEFAULT 0,
    headcount_fin         SMALLINT NOT NULL,
    UNIQUE (periodo, departamento_id)
);

COMMENT ON TABLE historico_headcount IS 'Variación mensual de planta por departamento: ingresos y retiros';

CREATE INDEX idx_headcount_periodo ON historico_headcount(periodo);
CREATE INDEX idx_headcount_depto   ON historico_headcount(departamento_id);

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE retiros (
    retiro_id           SERIAL PRIMARY KEY,
    empleado_id         INTEGER           NOT NULL REFERENCES empleados(empleado_id) UNIQUE,
    fecha_retiro        DATE              NOT NULL,
    tipo_retiro         tipo_retiro_tipo  NOT NULL,
    motivo_detalle      VARCHAR(200),     -- texto libre: "Mejor oferta salarial", "Conflicto con jefe"…
    realizo_entrevista  BOOLEAN           NOT NULL DEFAULT FALSE,
    calificacion_empresa SMALLINT,        -- 1–10 según entrevista de salida
    fue_reemplazado     BOOLEAN,
    dias_preaviso       SMALLINT          DEFAULT 0,
    CONSTRAINT ck_calif CHECK (calificacion_empresa IS NULL OR calificacion_empresa BETWEEN 1 AND 10)
);

COMMENT ON TABLE retiros IS 'Registro de desvinculación con causa y datos de la entrevista de salida';

-- ══════════════════════════════════════════════════════════════════════════════
-- SECCIÓN 11 — FINANCIALS DE LA EMPRESA
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE financials_empresa (
    financial_id             SERIAL PRIMARY KEY,
    periodo                  DATE           NOT NULL UNIQUE,
    ingresos_operacionales   NUMERIC(18,2)  NOT NULL,
    gasto_nomina             NUMERIC(18,2)  NOT NULL,   -- suma de costo_total_empresa del mes
    gasto_capacitacion       NUMERIC(14,2)  NOT NULL DEFAULT 0,
    gasto_bienestar          NUMERIC(14,2)  NOT NULL DEFAULT 0,
    headcount_total          SMALLINT       NOT NULL
);

COMMENT ON TABLE  financials_empresa                  IS 'Indicadores financieros mensuales de la empresa para calcular ratios de costo laboral';
COMMENT ON COLUMN financials_empresa.gasto_nomina     IS 'Costo total de nómina incluyendo aportes patronales';

-- ══════════════════════════════════════════════════════════════════════════════
-- VISTAS SEMÁNTICAS — lo que Vanna ve (no las tablas base directamente)
-- ══════════════════════════════════════════════════════════════════════════════

-- v_perfil_empleado: info completa del empleado con nombres descriptivos
CREATE OR REPLACE VIEW v_perfil_empleado AS
SELECT
    e.empleado_id,
    e.primer_nombre || ' ' || e.primer_apellido                AS nombre_completo,
    e.genero,
    EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.fecha_nacimiento))   AS edad,
    e.nivel_educativo,
    e.estado_civil,
    e.estado                                                    AS estado_empleo,
    e.tipo_contrato,
    e.fecha_ingreso,
    e.fecha_retiro,
    EXTRACT(YEAR FROM AGE(COALESCE(e.fecha_retiro, CURRENT_DATE), e.fecha_ingreso)) AS anos_empresa,
    c.nombre                                                    AS cargo,
    n.nombre                                                    AS nivel_cargo,
    n.orden                                                     AS nivel_orden,
    d.nombre                                                    AS departamento,
    s.nombre                                                    AS sede,
    s.ciudad,
    s.es_matriz,
    sal.salario_basico                                          AS salario_actual
FROM empleados e
JOIN cargos c         ON c.cargo_id       = e.cargo_actual_id
JOIN niveles_cargo n  ON n.nivel_id       = c.nivel_id
JOIN departamentos d  ON d.departamento_id = c.departamento_id
JOIN sedes s          ON s.sede_id        = e.sede_id
LEFT JOIN LATERAL (
    SELECT salario_basico FROM salarios
    WHERE empleado_id = e.empleado_id
      AND fecha_vigencia <= CURRENT_DATE
    ORDER BY fecha_vigencia DESC LIMIT 1
) sal ON TRUE;

COMMENT ON VIEW v_perfil_empleado IS 'Vista semántica: perfil completo del empleado con cargo, departamento, sede y salario actual';

-- ─────────────────────────────────────────────────────────────────────────────

-- v_nomina_mensual: nómina con nombres de empleado y departamento
CREATE OR REPLACE VIEW v_nomina_mensual AS
SELECT
    nm.periodo,
    e.empleado_id,
    e.primer_nombre || ' ' || e.primer_apellido  AS nombre_completo,
    d.nombre   AS departamento,
    s.nombre   AS sede,
    n.nombre   AS nivel_cargo,
    nm.salario_basico,
    nm.auxilio_transporte,
    nm.valor_horas_extra,
    nm.bonificaciones,
    nm.comisiones,
    nm.deduccion_salud,
    nm.deduccion_pension,
    nm.salario_neto,
    nm.costo_total_empresa
FROM nomina_mensual nm
JOIN empleados e     ON e.empleado_id    = nm.empleado_id
JOIN cargos c        ON c.cargo_id       = e.cargo_actual_id
JOIN niveles_cargo n ON n.nivel_id       = c.nivel_id
JOIN departamentos d ON d.departamento_id = c.departamento_id
JOIN sedes s         ON s.sede_id        = e.sede_id;

COMMENT ON VIEW v_nomina_mensual IS 'Vista semántica: nómina mensual con datos del empleado y su área';

-- ─────────────────────────────────────────────────────────────────────────────

-- v_asistencia_mensual
CREATE OR REPLACE VIEW v_asistencia_mensual AS
SELECT
    am.periodo,
    e.empleado_id,
    e.primer_nombre || ' ' || e.primer_apellido  AS nombre_completo,
    d.nombre   AS departamento,
    s.nombre   AS sede,
    am.dias_habiles,
    am.dias_trabajados,
    am.dias_ausencia,
    am.dias_incapacidad,
    am.dias_vacaciones,
    am.horas_extra_diurnas + am.horas_extra_nocturnas  AS total_horas_extra,
    am.tardanzas,
    ROUND(am.dias_trabajados::numeric / NULLIF(am.dias_habiles,0) * 100, 1) AS tasa_asistencia
FROM asistencia_mensual am
JOIN empleados e     ON e.empleado_id    = am.empleado_id
JOIN cargos c        ON c.cargo_id       = e.cargo_actual_id
JOIN departamentos d ON d.departamento_id = c.departamento_id
JOIN sedes s         ON s.sede_id        = e.sede_id;

COMMENT ON VIEW v_asistencia_mensual IS 'Vista semántica: asistencia mensual con tasa calculada por empleado y área';

-- ─────────────────────────────────────────────────────────────────────────────

-- v_rotacion_retiros
CREATE OR REPLACE VIEW v_rotacion_retiros AS
SELECT
    e.empleado_id,
    e.primer_nombre || ' ' || e.primer_apellido  AS nombre_completo,
    e.genero,
    e.fecha_ingreso,
    r.fecha_retiro,
    DATE_PART('month', AGE(r.fecha_retiro, e.fecha_ingreso))
      + DATE_PART('year',  AGE(r.fecha_retiro, e.fecha_ingreso)) * 12  AS meses_en_empresa,
    r.tipo_retiro,
    r.motivo_detalle,
    r.calificacion_empresa,
    c.nombre   AS cargo,
    n.nombre   AS nivel_cargo,
    d.nombre   AS departamento,
    s.nombre   AS sede
FROM retiros r
JOIN empleados e     ON e.empleado_id    = r.empleado_id
JOIN cargos c        ON c.cargo_id       = e.cargo_actual_id
JOIN niveles_cargo n ON n.nivel_id       = c.nivel_id
JOIN departamentos d ON d.departamento_id = c.departamento_id
JOIN sedes s         ON s.sede_id        = e.sede_id;

COMMENT ON VIEW v_rotacion_retiros IS 'Vista semántica: desvinculaciones con causa, permanencia y evaluación de salida';

-- ─────────────────────────────────────────────────────────────────────────────

-- v_headcount_historico
CREATE OR REPLACE VIEW v_headcount_historico AS
SELECT
    hh.periodo,
    TO_CHAR(hh.periodo, 'YYYY-MM')      AS mes,
    d.nombre                            AS departamento,
    s.nombre                            AS sede,
    hh.headcount_inicio,
    hh.ingresos,
    hh.retiros_voluntarios,
    hh.retiros_involuntarios,
    hh.retiros_voluntarios + hh.retiros_involuntarios  AS total_retiros,
    hh.headcount_fin,
    ROUND((hh.retiros_voluntarios + hh.retiros_involuntarios)::numeric
          / NULLIF(hh.headcount_inicio,0) * 100, 2)    AS tasa_rotacion_mensual
FROM historico_headcount hh
JOIN departamentos d ON d.departamento_id = hh.departamento_id
JOIN sedes s         ON s.sede_id         = hh.sede_id;

COMMENT ON VIEW v_headcount_historico IS 'Vista semántica: variación mensual de planta con tasa de rotación calculada';

-- ─────────────────────────────────────────────────────────────────────────────

-- v_evaluaciones_desempeno
CREATE OR REPLACE VIEW v_evaluaciones_desempeno AS
SELECT
    ev.periodo,
    e.empleado_id,
    e.primer_nombre || ' ' || e.primer_apellido  AS nombre_completo,
    d.nombre   AS departamento,
    s.nombre   AS sede,
    n.nombre   AS nivel_cargo,
    ev.cumplimiento_metas,
    ev.competencias_tecnicas,
    ev.trabajo_equipo,
    ev.liderazgo,
    ev.innovacion,
    ev.puntaje_total,
    ev.clasificacion
FROM evaluaciones_desempeno ev
JOIN empleados e     ON e.empleado_id    = ev.empleado_id
JOIN cargos c        ON c.cargo_id       = e.cargo_actual_id
JOIN niveles_cargo n ON n.nivel_id       = c.nivel_id
JOIN departamentos d ON d.departamento_id = c.departamento_id
JOIN sedes s         ON s.sede_id        = e.sede_id;

COMMENT ON VIEW v_evaluaciones_desempeno IS 'Vista semántica: resultados semestrales de desempeño con dimensiones y clasificación';

-- ─────────────────────────────────────────────────────────────────────────────

-- v_vacantes_reclutamiento
CREATE OR REPLACE VIEW v_vacantes_reclutamiento AS
SELECT
    v.vacante_id,
    v.fecha_apertura,
    v.fecha_cierre,
    v.estado,
    v.motivo_apertura,
    c.nombre   AS cargo,
    n.nombre   AS nivel_cargo,
    d.nombre   AS departamento,
    s.nombre   AS sede,
    v.candidatos_recibidos,
    v.candidatos_entrevistados,
    v.ofertas_extendidas,
    v.dias_abierta,
    v.fuente_contratacion,
    v.salario_ofrecido,
    CASE WHEN v.ofertas_extendidas > 0
         THEN ROUND(1.0 / v.ofertas_extendidas * 100, 1) END  AS tasa_aceptacion_pct
FROM vacantes v
JOIN cargos c        ON c.cargo_id       = v.cargo_id
JOIN niveles_cargo n ON n.nivel_id       = c.nivel_id
JOIN departamentos d ON d.departamento_id = c.departamento_id
JOIN sedes s         ON s.sede_id        = v.sede_id;

COMMENT ON VIEW v_vacantes_reclutamiento IS 'Vista semántica: vacantes con métricas de reclutamiento (time-to-fill, fuente, tasa aceptación)';

-- ─────────────────────────────────────────────────────────────────────────────

-- v_engagement_encuestas
CREATE OR REPLACE VIEW v_engagement_encuestas AS
SELECT
    ce.periodo,
    ce.nombre                                        AS nombre_ciclo,
    d.nombre                                         AS departamento,
    s.nombre                                         AS sede,
    COUNT(re.respuesta_id)                           AS respuestas,
    ce.total_invitados,
    ROUND(COUNT(re.respuesta_id)::numeric / NULLIF(ce.total_invitados,0) * 100, 1)  AS tasa_participacion,
    ROUND(AVG(re.orgullo_empresa),1)                 AS promedio_orgullo,
    ROUND(AVG(re.recomendaria),1)                    AS promedio_enps_raw,
    ROUND(AVG(re.satisfaccion_cargo),1)              AS promedio_satisfaccion,
    ROUND(AVG(re.equilibrio_vida),1)                 AS promedio_equilibrio,
    ROUND(AVG(re.oportunidades_desarrollo),1)        AS promedio_desarrollo,
    ROUND(AVG(re.intencion_permanencia),1)           AS promedio_retencion,
    -- eNPS = %promotores(≥9) - %detractores(≤6)
    ROUND(
        (SUM(CASE WHEN re.recomendaria >= 9 THEN 1 ELSE 0 END)::numeric
         - SUM(CASE WHEN re.recomendaria <= 6 THEN 1 ELSE 0 END)::numeric)
        / NULLIF(COUNT(re.respuesta_id),0) * 100, 1
    )                                                AS enps,
    ROUND(AVG(re.relacion_jefe),1)                   AS promedio_relacion_jefe
FROM ciclos_encuesta ce
JOIN respuestas_encuesta re ON re.ciclo_id    = ce.ciclo_id
JOIN empleados e            ON e.empleado_id  = re.empleado_id
JOIN cargos c               ON c.cargo_id     = e.cargo_actual_id
JOIN departamentos d        ON d.departamento_id = c.departamento_id
JOIN sedes s                ON s.sede_id      = e.sede_id
GROUP BY ce.ciclo_id, ce.periodo, ce.nombre, ce.total_invitados, d.nombre, s.nombre;

COMMENT ON VIEW v_engagement_encuestas IS 'Vista semántica: resumen de engagement y eNPS por ciclo, departamento y sede';

-- ─────────────────────────────────────────────────────────────────────────────

-- v_capacitaciones
CREATE OR REPLACE VIEW v_capacitaciones AS
SELECT
    pc.programa_id,
    pc.nombre                                                  AS programa,
    pc.categoria,
    pc.modalidad,
    pc.duracion_horas,
    pc.costo_unitario,
    pc.fecha_inicio,
    pc.fecha_fin,
    e.empleado_id,
    e.primer_nombre || ' ' || e.primer_apellido                AS nombre_completo,
    d.nombre   AS departamento,
    s.nombre   AS sede,
    part.estado,
    part.calificacion,
    part.puntaje_desempeno_pre,
    part.puntaje_desempeno_post,
    CASE WHEN part.puntaje_desempeno_post IS NOT NULL AND part.puntaje_desempeno_pre IS NOT NULL
         THEN ROUND(part.puntaje_desempeno_post - part.puntaje_desempeno_pre, 2)
    END AS delta_desempeno
FROM participantes_capacitacion part
JOIN programas_capacitacion pc ON pc.programa_id = part.programa_id
JOIN empleados e               ON e.empleado_id  = part.empleado_id
JOIN cargos c                  ON c.cargo_id     = e.cargo_actual_id
JOIN departamentos d           ON d.departamento_id = c.departamento_id
JOIN sedes s                   ON s.sede_id      = e.sede_id;

COMMENT ON VIEW v_capacitaciones IS 'Vista semántica: participación en capacitaciones con efectividad (delta de desempeño)';
