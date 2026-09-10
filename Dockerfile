# Dockerfile ottimizzato per Render.com (free hosting)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off

# Librerie di sistema (GEOS per GeoJSON/PostGIS, build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgeos-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia e installa dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia tutto il codice sorgente
COPY . .

# Crea cartella uploads per avatar/foto profilo
RUN mkdir -p app/static/uploads/avatars

EXPOSE 8000

# Avvio con uvicorn — porta letta da $PORT (Render la imposta automaticamente)
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
