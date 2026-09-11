# CivicAgent Backend

FastAPI backend for the CivicAgent platform.

## Quick Start

```bash
python -m venv venv
venv\Scripts\activate   # Windows
pip install -e ".[dev]"

uvicorn main:app --reload --port 8000
```

## API

- Swagger: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Health: `GET /api/v1/health`
- System health: `GET /api/v1/system/health`