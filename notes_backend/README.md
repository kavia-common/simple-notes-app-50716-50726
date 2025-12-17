# Notes Backend (FastAPI)

This service exposes a REST API for a simple notes app.

- Framework: FastAPI
- Port: 3001
- DB: PostgreSQL (via SQLAlchemy/psycopg)

## Environment

Copy `.env.example` to `.env` and set:

- DATABASE_URL: e.g. `postgresql://appuser:dbuser123@localhost:5000/myapp`
- FRONTEND_ORIGIN: e.g. `http://localhost:3000`

## Run

Install dependencies and run with uvicorn:

```
pip install -r requirements.txt
uvicorn src.api.main:app --host 0.0.0.0 --port 3001 --reload
```

## API

- GET /notes
- POST /notes
- GET /notes/{id}
- PUT /notes/{id}
- DELETE /notes/{id}

Auto-generated docs: /docs

## Database

Table `notes` (id UUID PK, title TEXT, content TEXT, created_at, updated_at).
On startup, the app ensures `pgcrypto` extension and creates the table if it does not exist.
