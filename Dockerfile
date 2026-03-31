# syntax=docker/dockerfile:1
FROM python:3.12-slim AS backend

WORKDIR /app
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY tools/ tools/
COPY utils.py writer.py ./

# ── Frontend build stage ──────────────────────────────────────────────
FROM node:22-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ .
RUN npm run build

# ── Final stage ───────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Python deps
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

# Backend sources
COPY backend/ backend/
COPY tools/ tools/
COPY utils.py writer.py ./

# Frontend static files
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

# Output directory
RUN mkdir -p output

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
