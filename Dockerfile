# Dockerfile ottimizzato per Fly.io
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off

# Librerie di sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgeos-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Codice sorgente
COPY . .

# Cartella uploads locale (fallback se il volume non è montato)
RUN mkdir -p app/static/uploads/avatars /data/uploads/avatars

EXPOSE 8000

# Avvio — porta letta da $PORT (Fly la imposta automaticamente)
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
