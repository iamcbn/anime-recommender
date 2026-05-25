# ==========================================
# STAGE 1: Builder (Compiles dependencies)
# ==========================================
FROM python:3.11-slim AS builder

WORKDIR /app

# fasttext needs a C++ compiler to build from source
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/data_pipeline/requirements.txt .

# Keep Data Pipeline on CPU (since GitHub Actions runs on CPU servers)
RUN pip install --no-cache-dir torch==2.7.1 \
    --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -r requirements.txt


# ==========================================
# STAGE 2: Runtime (Lean production image)
# ==========================================
FROM python:3.11-slim

WORKDIR /app

# Copy ONLY the finished, compiled virtual environment
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/data_pipeline /app/data_pipeline

CMD ["python", "-m", "data_pipeline.run_pipeline"]