#!/bin/bash
set -e

echo "=== HR Copilot — NovaTech Colombia ==="

# ── Esperar a que PostgreSQL esté listo ───────────────────────────────────────
echo "Esperando PostgreSQL..."
until pg_isready -h "$HR_DB_HOST" -U "$HR_DB_USER" -d "$HR_DB_NAME" -q; do
    sleep 2
done
echo "  PostgreSQL listo."

# ── Inicializar BD si está vacía ──────────────────────────────────────────────
EMP_COUNT=$(PGPASSWORD="$HR_DB_PASSWORD" psql \
    -h "$HR_DB_HOST" -U "$HR_DB_USER" -d "$HR_DB_NAME" \
    -t -c "SELECT COUNT(*) FROM empleados" 2>/dev/null | tr -d ' ' || echo "0")

if [ "${EMP_COUNT:-0}" -lt "100" ]; then
    echo "Inicializando esquema y datos..."
    PGPASSWORD="$HR_DB_PASSWORD" psql \
        -h "$HR_DB_HOST" -U "$HR_DB_USER" -d "$HR_DB_NAME" \
        -f setup/schema_postgres.sql
    python setup/seed_postgres.py
    python setup/seed_users.py
    echo "  BD lista con datos de NovaTech Colombia."
else
    echo "  BD ya inicializada ($EMP_COUNT empleados)."
fi

# ── Entrenar ChromaDB si está vacío ──────────────────────────────────────────
CHROMA_DIR="${CHROMA_DIR:-/app/chroma_db}"
CHROMA_EMPTY=true
if [ -d "$CHROMA_DIR" ] && [ "$(ls -A "$CHROMA_DIR" 2>/dev/null)" ]; then
    CHROMA_EMPTY=false
fi

if [ "$CHROMA_EMPTY" = true ]; then
    echo "Entrenando ChromaDB (primera vez ~2 min)..."
    python setup/train_vanna_postgres.py
    echo "  ChromaDB listo."
else
    echo "  ChromaDB ya entrenado."
fi

# ── Arrancar gunicorn ─────────────────────────────────────────────────────────
echo "Iniciando dashboard en puerto 8051..."
exec gunicorn app.dashboard:server \
    --bind 0.0.0.0:8051 \
    --workers 2 \
    --timeout 120 \
    --worker-class sync \
    --access-logfile - \
    --error-logfile -
