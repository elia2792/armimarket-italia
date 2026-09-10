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

# Cartelle uploads locale e persistente con permessi per utente non privilegiato
RUN mkdir -p app/static/uploads/avatars /data/uploads/avatars && \
    groupadd -g 1001 appgroup && \
    useradd -u 1001 -g appgroup -s /bin/bash -m appuser && \
    chown -R appuser:appgroup /app /data/uploads

USER appuser

EXPOSE 8000

# Avvio con utente non-root e soppressione dell'header Server Uvicorn
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-server-header
