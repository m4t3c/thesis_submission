# Immagine di base: Python già installato su Linux minimale
FROM python:3.12-slim

# Non scrivere file .pyc, output non bufferizzato (log immediati)
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Librerie di sistema necessarie per compilare mysqlclient
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential default-libmysqlclient-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia prima solo requirements: sfrutta la cache di Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia il resto del codice
COPY . .

# gunicorn ascolterà su questa porta dentro il container
EXPOSE 8000
