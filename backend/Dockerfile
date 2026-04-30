FROM python:3.11-slim

WORKDIR /app

# Keep Python logs visible in Railway and avoid writing .pyc files
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install Python dependencies first for better Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the FastAPI backend source code
COPY . .

# Ensure the runtime memory/data directories exist
RUN mkdir -p /app/backend/data /app/data \
    && test -f /app/backend/data/memory.json || echo "[]" > /app/backend/data/memory.json

# Railway injects PORT at runtime. 8000 is only the local fallback.
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
