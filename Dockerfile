FROM python:3.12-slim

WORKDIR /app

# Dependencias del sistema (postgresql-client para pg_isready en entrypoint)
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Dependencias Python
COPY requirements-full.txt .
RUN pip install --no-cache-dir -r requirements-full.txt

# Código de la app
COPY . .

# Entrypoint: inicializa BD + ChromaDB si es necesario, luego arranca gunicorn
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8051

ENTRYPOINT ["/entrypoint.sh"]
