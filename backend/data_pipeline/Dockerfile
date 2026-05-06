FROM python:3.11-slim

WORKDIR /app

# fasttext needs a C++ compiler to build from source
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*


COPY backend/data_pipeline/requirements.txt .

RUN pip install --no-cache-dir torch==2.7.1 \
    --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -r requirements.txt

COPY backend/data_pipeline app/data_pipeline

CMD ["python", "-m", "data_pipeline.run_pipeline"]