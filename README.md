# NeoClips

**Clip discovery and production engine for the NeoVids ecosystem.**

## Overview

NeoClips transforms long-form audiovisual content into clip candidates and rendered clips for platforms like YouTube, YouTube Shorts, TikTok, and Instagram Reels.

## Quick Start

```bash
# Clone and enter directory
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

## API Documentation

- Swagger UI: http://localhost:8020/docs
- ReDoc: http://localhost:8020/redoc

## Endpoints

### Health
- `GET /health` - Liveness check
- `GET /health/readiness` - Readiness check (includes dependency status)

### Policies (`/v1/policies`)
- `POST /` - Create policy
- `GET /` - List policies
- `GET /{id}` - Get policy
- `PATCH /{id}` - Update policy
- `DELETE /{id}` - Delete policy
- `POST /{id}/verify` - Mark as verified
- `POST /{id}/block` - Block policy

### Sources (`/v1/sources`)
- `POST /` - Create source
- `GET /` - List sources
- `GET /{id}` - Get source
- `PATCH /{id}` - Update source
- `DELETE /{id}` - Delete source

### Workflows (`/v1/workflows`)
- `POST /` - Create workflow
- `GET /` - List workflows
- `GET /{id}` - Get workflow
- `PATCH /{id}` - Update workflow
- `DELETE /{id}` - Delete workflow
- `POST /{id}/cancel` - Cancel workflow
- `POST /{id}/retry` - Retry failed workflow

## Development

```bash
# Run tests
./scripts/test.sh

# Run linter
./scripts/lint.sh

# Run type checker
./scripts/typecheck.sh

# Run all checks
./scripts/check.sh
```

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed architecture documentation.

## Documentation

- [MVP Scope](docs/MVP_SCOPE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Domain Model](docs/DOMAIN_MODEL.md)
- [API Contracts](docs/CONTRACTS.md)
- [Development Guide](docs/DEVELOPMENT.md)

## License

MIT
