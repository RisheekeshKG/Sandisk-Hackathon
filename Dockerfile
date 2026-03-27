# ─── Base stage ──────────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

WORKDIR /app

# Install system dependencies: iverilog (syntax checks), ngspice (analog sim), git (PyGithub)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        iverilog \
        ngspice && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies from backend requirements
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy entire project
COPY . .

# ─── FastAPI backend stage ────────────────────────────────────────────────────
FROM base AS api

WORKDIR /app/backend

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

# ─── CI runner stage (for local testing of the agent) ────────────────────────
FROM base AS agent

WORKDIR /app/backend

CMD ["python", "agent_runner.py"]
