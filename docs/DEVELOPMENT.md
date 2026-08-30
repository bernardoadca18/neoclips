# NeoClips Development Guide

## Prerequisites

- Python 3.12+
- PostgreSQL 16
- Redis 7
- Docker and Docker Compose (optional)

## Quick Start

```bash
# Clone the repository
cd neoclips

# Copy environment file
cp .env.example .env

# Start infrastructure
docker compose up -d db redis

# Install dependencies
cd backend
pip install -e ".[dev]"

# Run migrations
alembic upgrade head

# Start API
uvicorn app.main:app --reload --port 8020

# In another terminal, start worker
celery -A app.core.celery_app.celery_app worker -Q neoclips --concurrency=1 -l info
```

## Project Structure

```
neoclips/
├── backend/
│   ├── alembic/
│   │   └── versions/
│   ├── app/
│   │   ├── api/
│   │   │   └── routers/
│   │   ├── core/
│   │   ├── models/
│   │   ├── repositories/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── tasks/
│   │   ├── clients/
│   │   └── main.py
│   ├── scripts/
│   ├── tests/
│   │   ├── unit/
│   │   └── integration/
│   ├── alembic.ini
│   ├── pyproject.toml
│   └── Dockerfile
├── docs/
├── scripts/
├── .env.example
├── .gitignore
├── .dockerignore
├── docker-compose.yml
├── README.md
└── AGENTS.md
```

## Configuration

Configuration is centralized in `app/core/config.py` using `pydantic-settings`.

All settings are loaded from environment variables or `.env` file.

Key settings:
- `APP_ENV` — Environment (development, production)
- `LOG_LEVEL` — Logging level
- `DATABASE_URL` — PostgreSQL connection URL
- `REDIS_URL` — Redis connection URL
- `CELERY_QUEUE_NAME` — Celery queue name
- `API_HOST` — API host
- `API_PORT` — API port

Never hardcode secrets. Use `.env` for local development.

## Database

### Migrations

Use Alembic for all database migrations.

```bash
# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

Never use `Base.metadata.create_all()` for production migrations.

### Schema

- All tables use UUID primary keys
- All timestamps use `TIMESTAMP WITH TIME ZONE`
- Constraints are defined at the database level
- Indexes are added for common query patterns

## Testing

### Unit Tests

```bash
pytest tests/unit -v
```

### Integration Tests

```bash
pytest tests/integration -v -m postgres
```

Integration tests require PostgreSQL and are opt-in.

### All Tests

```bash
pytest
```

## Code Quality

### Linting

```bash
ruff check .
```

### Type Checking

```bash
mypy app
```

### All Checks

```bash
./scripts/check.sh
```

## API Development

### Adding a New Endpoint

1. Define schema in `app/schemas/`
2. Create or update repository in `app/repositories/`
3. Create or update service in `app/services/`
4. Add router in `app/api/routers/`
5. Register router in `app/main.py`

### Repository Pattern

Repositories encapsulate database access. Never use SQLAlchemy directly in routers.

### Service Pattern

Services contain business logic. Routers should:
- Validate input
- Call service
- Map domain errors to HTTP
- Return schema

## Celery Tasks

Tasks are defined in `app/tasks/`.

Configuration:
- `worker_prefetch_multiplier = 1`
- `task_acks_late = True`
- `broker_connection_retry_on_startup = True`

Always use the task session context manager for database access:

```python
from app.core.database import task_session

@celery_app.task
def my_task():
    async with task_session() as session:
        # Use session
        pass
```

## Logging

Structured logging is configured in `app/core/logging.py`.

Use the workflow context to include workflow_id in logs:

```python
from app.core.logging import set_workflow_id

set_workflow_id(str(workflow.id))
```

## Docker

```bash
# Build and start all services
docker compose up --build

# Start specific services
docker compose up db redis api

# View logs
docker compose logs -f api

# Stop all services
docker compose down
```

Data persists across `docker compose down` and `docker compose up`.

## Scripts

- `scripts/dev.sh` — Start development environment
- `scripts/test.sh` — Run tests
- `scripts/lint.sh` — Run linter
- `scripts/typecheck.sh` — Run type checker
- `scripts/check.sh` — Run all quality checks
- `scripts/migrate.sh` — Run migrations
- `scripts/smoke.sh` — Run smoke tests
