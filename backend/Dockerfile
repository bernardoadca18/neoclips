FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first for better caching
COPY pyproject.toml .

# Install Python dependencies
RUN pip install --no-cache-dir "."

# Copy application code
COPY app ./app

# Copy Alembic for migrations
COPY alembic.ini .
COPY alembic ./alembic

# Expose port
EXPOSE 8020

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020"]
