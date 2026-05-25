# ==========================================
# STAGE 1: Builder (Compiles dependencies)
# ==========================================
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies (needed in case any packages compile from source)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create a virtual environment to hold all installed packages cleanly
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/rag_pipeline/requirements.txt .

# Install PyTorch with CUDA 11.8 support (Enables GPU acceleration)
RUN pip install --no-cache-dir torch==2.7.1+cu118 \
    --index-url https://download.pytorch.org/whl/cu118

# Install remaining requirements
RUN pip install --no-cache-dir -r requirements.txt


# ==========================================
# STAGE 2: Runtime (Lean production image)
# ==========================================
FROM python:3.11-slim

WORKDIR /app

# Copy ONLY the finished, compiled virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv

# Activate the virtual environment
ENV PATH="/opt/venv/bin:$PATH"

# Copy the application code
COPY backend/rag_pipeline /app/rag_pipeline

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "rag_pipeline.main:app", "--host", "0.0.0.0", "--port", "8000"]