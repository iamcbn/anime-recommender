FROM python:3.11-slim

WORKDIR /app

# Copy only the RAG pipeline's requirements
COPY backend/rag_pipeline/requirements.txt .

RUN pip install --no-cache-dir torch==2.7.1 \
    --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -r requirements.txt

COPY backend/rag_pipeline .

EXPOSE 8000

CMD ["uvicorn", "backend.rag_pipeline.main:app", "--host", "0.0.0.0", "--port", "8000"]