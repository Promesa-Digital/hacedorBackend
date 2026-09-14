# syntax=docker/dockerfile:1

FROM python:3.13-slim AS builder

WORKDIR /app

# Headers de sistema necesarios para compilar dependencias de Python
# (Pillow necesita libjpeg/zlib; psycopg2-binary trae sus propios libs
# pero pip a veces igual requiere build-essential para compilar ruedas
# no manylinux según arquitectura).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libjpeg62-turbo-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.13-slim

WORKDIR /app

# Librerías de runtime (sin las de compilación) para que Pillow funcione.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libjpeg62-turbo \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

COPY . .

RUN chmod +x /app/entrypoint.sh

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 80

ENTRYPOINT ["/app/entrypoint.sh"]
