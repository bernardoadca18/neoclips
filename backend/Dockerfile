FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy application code first for pip install
COPY app ./app
COPY pyproject.toml .

# Install Python dependencies
RUN pip install --no-cache-dir "."

# Copy Alembic for migrations
COPY alembic.ini .
COPY alembic ./alembic

# Expose port
EXPOSE 8020

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020"]
