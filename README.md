# FastAPI Async Framework Template

A production-ready FastAPI async framework template with SQLAlchemy 2.0 async engine and PostgreSQL.

## Features

- ✅ Full async support (FastAPI + SQLAlchemy 2.0 + asyncpg)
- ✅ Structured project organization (routers, models, schemas separation)
- ✅ Database connection pool management
- ✅ Alembic database migrations (async + schema support)
- ✅ Celery + Redis background tasks and scheduled tasks (K8s multi-pod safe)
- ✅ Loguru async logging (auto rotation, compression)
- ✅ Auto API documentation (Swagger UI)
- ✅ CORS middleware support
- ✅ Environment variable configuration
- ✅ Type hints support
- ✅ AWS S3 file upload utility
- ✅ PDF and Excel parsing utilities

## Project Structure

```
fastapi-tmpl/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application entry
│   ├── config.py            # Configuration management
│   ├── database.py          # Database connection and session management
│   ├── celery_app.py        # Celery application configuration
│   ├── logger.py            # Logging configuration (loguru)
│   ├── dependencies.py      # Dependency injection
│   ├── enums/               # Enum definitions
│   │   ├── __init__.py
│   │   └── common.py
│   ├── models/              # SQLAlchemy data models
│   │   └── __init__.py
│   ├── schemas/             # Pydantic schema definitions
│   │   ├── __init__.py
│   │   └── response.py
│   ├── routers/             # API routes
│   │   ├── __init__.py
│   │   ├── enums.py
│   │   ├── health.py
│   │   ├── tasks.py
│   │   └── upload.py
│   ├── tasks/               # Celery tasks
│   │   ├── __init__.py
│   │   └── example.py
│   └── utils/               # Utility functions
│       ├── __init__.py
│       ├── response.py
│       ├── s3.py
│       ├── excel.py
│       └── pdf.py
├── alembic/                 # Database migrations
│   ├── versions/            # Migration version files
│   ├── env.py               # Migration environment configuration
│   ├── script.py.mako       # Migration template
│   └── README
├── alembic.ini              # Alembic configuration file
├── scripts/                 # Startup scripts
│   ├── start.sh             # Startup script
│   └── reset_db.py          # Database reset script
├── Dockerfile               # Docker image build file
├── docker-compose.yml       # Docker Compose configuration
├── main.py                  # Application startup entry
├── pyproject.toml           # Project configuration and dependencies
└── README.md
```

## Quick Start

### 1. Install Dependencies

Using `uv` to install dependencies:

```bash
uv sync
```

### 2. Configure Environment Variables

Create `.env` file:

```env
# Database configuration
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/dbname
DATABASE_SCHEMA=public

# Redis configuration
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Application configuration
DEBUG=True
LOG_LEVEL=INFO
HOST=0.0.0.0
PORT=8000

# AWS S3 configuration (optional)
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=us-east-1
AWS_S3_BUCKET=your_bucket
```

### 3. Database Migrations

```bash
# Generate migration file
uv run alembic revision --autogenerate -m "describe your changes"

# Apply migrations
uv run alembic upgrade head

# Reset migration state (if needed)
uv run alembic stamp base
```

### 4. Start Services

**Option 1: Using startup script (recommended)**

```bash
chmod +x scripts/start.sh
./scripts/start.sh all     # Start all services
./scripts/start.sh api     # Start API only
./scripts/start.sh worker  # Start Worker only
./scripts/start.sh beat    # Start Beat only
./scripts/start.sh stop    # Stop all services
```

**Option 2: Using Docker Compose**

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

**Option 3: Manual startup**

```bash
# Start API
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Start Worker (new terminal)
uv run celery -A app.celery_app worker --loglevel=info

# Start Beat (new terminal)
uv run celery -A app.celery_app beat --loglevel=info -S redbeat.RedBeatScheduler
```

### 5. Access API Documentation

After starting:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API Endpoints

### Health Check
- `GET /health` - Health check

### Background Tasks
- `POST /api/v1/tasks/example` - Create example background task
- `GET /api/v1/tasks/status/{task_id}` - Query task status

### Enums
- `GET /api/v1/enums/status` - Get status enums

### File Upload (Presigned URL)
- `POST /api/v1/upload/presign` - Get presigned URL for direct S3 upload
- `POST /api/v1/upload/presign/image` - Get presigned URL for image upload
- `POST /api/v1/upload/presign/document` - Get presigned URL for document upload

## Development Guide

### Adding New Routes

1. Create a new route file in `app/routers/` directory
2. Use `APIRouter` to create a router instance
3. Register the router in `app/main.py`:

```python
from app.routers import your_router

app.include_router(your_router.router, prefix="/api/v1")
```

### Adding New Data Models

1. Create a model file in `app/models/` directory
2. Inherit from `Base` class (import from `app.database`)
3. Export the model in `app/models/__init__.py`
4. Create corresponding Pydantic schema in `app/schemas/`
5. Import the model in `alembic/env.py` for migration detection
6. Generate and apply migrations

Example model:

```python
from sqlalchemy import Column, String, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class User(Base):
    """user model"""

    __tablename__ = "users"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
        server_default=func.gen_random_uuid(),
    )
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

### Adding Celery Tasks

1. Create a task file in `app/tasks/` directory
2. Use `@celery_app.task` or `@shared_task` decorator
3. Export the task in `app/tasks/__init__.py`

```python
from app.celery_app import celery_app

@celery_app.task(bind=True, max_retries=3)
def my_task(self, data: dict):
    # Task logic
    return {"status": "success"}
```

### Adding Scheduled Tasks

Configure `beat_schedule` in `app/celery_app.py`:

```python
from celery.schedules import crontab

celery_app.conf.beat_schedule = {
    "my-periodic-task": {
        "task": "app.tasks.example.my_periodic_task",
        "schedule": 60.0,  # Every 60 seconds
    },
    # Or use crontab
    "daily-task": {
        "task": "app.tasks.example.daily_task",
        "schedule": crontab(hour=0, minute=0),  # Daily at 00:00
    },
}
```

### Database Migration Commands

| Command | Description |
|---------|-------------|
| `uv run alembic revision --autogenerate -m "msg"` | Auto-generate migration file |
| `uv run alembic upgrade head` | Upgrade to latest version |
| `uv run alembic downgrade -1` | Rollback one version |
| `uv run alembic downgrade base` | Rollback all migrations |
| `uv run alembic current` | View current version |
| `uv run alembic history` | View migration history |

### Celery Commands

| Command | Description |
|---------|-------------|
| `uv run celery -A app.celery_app worker --loglevel=info` | Start Worker |
| `uv run celery -A app.celery_app beat --loglevel=info` | Start Beat scheduler |
| `uv run celery -A app.celery_app flower` | Start Flower monitoring |
| `uv run celery -A app.celery_app inspect active` | View active tasks |
| `uv run celery -A app.celery_app purge` | Clear pending tasks |

### Specifying Schema

Configure `DATABASE_SCHEMA` in `.env` to specify database schema:

```env
DATABASE_SCHEMA=your_schema_name
```

All model tables will be created under the specified schema.

### Logging Usage

```python
from app.logger import logger

# Basic logging
logger.debug("Debug message")
logger.info("Info message")
logger.warning("Warning message")
logger.error("Error message")

# Exception logging (auto stack trace)
try:
    ...
except Exception as e:
    logger.exception("Something went wrong")
```

Log files output to `logs/` directory:
- `logs/app.log` - All INFO and above levels (7 days retention)
- `logs/error.log` - ERROR and above levels only (30 days retention)

### AWS S3 Usage

```python
from app.utils.s3 import (
    upload_to_s3,
    download_from_s3,
    delete_from_s3,
    get_presigned_url,
    get_presigned_upload_url,
)

# Upload file (server-side)
url = await upload_to_s3(file_bytes, "image.png", folder="images")

# Download file to memory
file_bytes = await download_from_s3("uploads/documents/report.pdf")
# or from full URL
file_bytes = await download_from_s3(url)

# Delete file
await delete_from_s3(url)

# Generate presigned URL for private file access
presigned_url = await get_presigned_url(url, expiration=3600)

# Generate presigned URL for direct frontend upload
result = await get_presigned_upload_url("photo.jpg", folder="avatars")
print(result.upload_url)   # Frontend uses this URL to PUT file
print(result.key)          # S3 object key
print(result.public_url)   # URL after upload
```

#### Frontend Direct Upload Example

```javascript
// 1. Get presigned URL from backend
const response = await fetch('/api/v1/upload/presign', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename: 'photo.jpg', folder: 'avatars' })
});
const { data } = await response.json();

// 2. Upload directly to S3
await fetch(data.upload_url, {
    method: 'PUT',
    body: file,
    headers: { 'Content-Type': file.type }
});

// 3. Use data.public_url for further processing
```

### Excel/PDF Parsing

```python
# Excel
from app.utils.excel import parse_excel, parse_excel_bytes, excel_to_dicts

doc = parse_excel("file.xlsx", password="optional")
data = doc.first_sheet.to_dicts()

# PDF
from app.utils.pdf import parse_pdf, parse_pdf_bytes

doc = parse_pdf("file.pdf", password="optional")
text = doc.full_text
tables = doc.all_tables
```

## K8s Multi-Pod Deployment

### Task Execution

| Type | Multi-Pod Behavior | Description |
|------|-------------------|-------------|
| Background Tasks (Worker) | ✅ No duplicates | Redis queue ensures tasks consumed once |
| Scheduled Tasks (Beat) | ✅ No duplicates | RedBeat distributed lock scheduling |

### Deployment Architecture

```
┌─────────────────────────────────────────────────────┐
│                    K8s Cluster                       │
├─────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │  API Pod 1  │  │  API Pod 2  │  │  API Pod N  │  │
│  │  (FastAPI)  │  │  (FastAPI)  │  │  (FastAPI)  │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
│         │               │               │           │
│         └───────────────┼───────────────┘           │
│                         ▼                           │
│  ┌─────────────────────────────────────────────┐   │
│  │              Redis (Queue/Lock)              │   │
│  └─────────────────────────────────────────────┘   │
│                         ▲                           │
│         ┌───────────────┼───────────────┐           │
│         │               │               │           │
│  ┌──────┴──────┐ ┌──────┴──────┐ ┌──────┴──────┐   │
│  │ Worker Pod 1│ │ Worker Pod 2│ │ Worker+Beat │   │
│  │  (Celery)   │ │  (Celery)   │ │  (Celery)   │   │
│  └─────────────┘ └─────────────┘ └─────────────┘   │
└─────────────────────────────────────────────────────┘
```

## Tech Stack

- **FastAPI**: Modern, fast web framework
- **SQLAlchemy 2.0**: ORM framework (async support)
- **Alembic**: Database migration tool
- **Celery**: Distributed task queue
- **RedBeat**: Distributed Beat scheduler (multi-instance safe)
- **Redis**: Message broker and result backend
- **Loguru**: Async logging library
- **asyncpg**: PostgreSQL async driver
- **Pydantic**: Data validation and serialization
- **Uvicorn**: ASGI server
- **aioboto3**: Async AWS SDK
- **pdfplumber**: PDF parsing
- **openpyxl/xlrd**: Excel parsing

## License

MIT
