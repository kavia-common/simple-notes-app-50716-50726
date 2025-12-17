import os
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Path
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Text, create_engine, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# Database setup
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    # Fallback to local DB started by notes_database container startup.sh defaults
    # Adjust via .env to production-grade URL, e.g., postgresql://user:pass@host:port/db
    "postgresql://appuser:dbuser123@localhost:5000/myapp",
)
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


class NoteORM(Base):
    __tablename__ = "notes"
    id = Column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    title = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


def init_db() -> None:
    """Initialize DB extensions and ensure table exists."""
    with engine.begin() as conn:
        # Ensure pgcrypto exists for gen_random_uuid()
        conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
        # Create table if not exists (idempotent with raw SQL to preserve defaults)
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )


# Pydantic Schemas
# PUBLIC_INTERFACE
class NoteCreate(BaseModel):
    """Payload for creating a new note."""
    title: str = Field(..., description="Title of the note", min_length=1)
    content: str = Field(..., description="Content of the note", min_length=1)


# PUBLIC_INTERFACE
class NoteUpdate(BaseModel):
    """Payload for updating an existing note."""
    title: Optional[str] = Field(None, description="Updated title of the note", min_length=1)
    content: Optional[str] = Field(None, description="Updated content of the note", min_length=1)


# PUBLIC_INTERFACE
class Note(BaseModel):
    """Note response model."""
    id: UUID = Field(..., description="Unique identifier of the note")
    title: str = Field(..., description="Title of the note")
    content: str = Field(..., description="Content of the note")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last updated timestamp")


openapi_tags = [
    {"name": "health", "description": "Health and status endpoints"},
    {"name": "notes", "description": "CRUD operations for notes"},
]

app = FastAPI(
    title="Notes API",
    description="Simple Notes API providing CRUD endpoints for notes.",
    version="0.1.0",
    openapi_tags=openapi_tags,
)

# CORS: allow React frontend on 3000 and localhost fallbacks
frontend_origins = [
    os.getenv("FRONTEND_ORIGIN", "http://localhost:3000"),
    "http://127.0.0.1:3000",
    "*",  # Development convenience; lock down for production
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db() -> Session:
    """FastAPI dependency to provide a SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    """Initialize DB objects and ensure schema exists on startup."""
    try:
        init_db()
    except SQLAlchemyError as exc:
        # In a real system, consider better logging
        raise RuntimeError(f"Database initialization failed: {exc}") from exc


# PUBLIC_INTERFACE
@app.get("/", tags=["health"], summary="Health Check")
def health_check():
    """Health check endpoint to verify the API is running."""
    return {"message": "Healthy"}


# PUBLIC_INTERFACE
@app.get(
    "/notes",
    response_model=List[Note],
    tags=["notes"],
    summary="List notes",
    description="Retrieve all notes ordered by updated_at DESC.",
)
def list_notes(db: Session = Depends(get_db)):
    """List all notes."""
    try:
        rows = db.query(NoteORM).order_by(NoteORM.updated_at.desc()).all()
        return [Note(**{
            "id": r.id,
            "title": r.title,
            "content": r.content,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }) for r in rows]
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")


# PUBLIC_INTERFACE
@app.post(
    "/notes",
    response_model=Note,
    tags=["notes"],
    summary="Create note",
    description="Create a new note with a title and content.",
)
def create_note(payload: NoteCreate, db: Session = Depends(get_db)):
    """Create a new note."""
    try:
        now_stmt = text("NOW()")
        # Manually set timestamps to ensure consistency
        note = NoteORM(title=payload.title, content=payload.content)
        db.add(note)
        db.flush()  # get PK
        # Update timestamps explicitly to reflect server clock
        db.execute(
            text("UPDATE notes SET created_at = NOW(), updated_at = NOW() WHERE id = :id"),
            {"id": str(note.id)},
        )
        db.commit()
        db.refresh(note)
        return Note(
            id=note.id,
            title=note.title,
            content=note.content,
            created_at=note.created_at,
            updated_at=note.updated_at,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")


# PUBLIC_INTERFACE
@app.get(
    "/notes/{note_id}",
    response_model=Note,
    tags=["notes"],
    summary="Get note",
    description="Get a single note by its ID.",
)
def get_note(
    note_id: UUID = Path(..., description="Note ID"),
    db: Session = Depends(get_db),
):
    """Retrieve a note by ID."""
    try:
        note = db.get(NoteORM, note_id)
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        return Note(
            id=note.id,
            title=note.title,
            content=note.content,
            created_at=note.created_at,
            updated_at=note.updated_at,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")


# PUBLIC_INTERFACE
@app.put(
    "/notes/{note_id}",
    response_model=Note,
    tags=["notes"],
    summary="Update note",
    description="Update title and/or content of a note.",
)
def update_note(
    payload: NoteUpdate,
    note_id: UUID = Path(..., description="Note ID"),
    db: Session = Depends(get_db),
):
    """Update a note's title/content."""
    if payload.title is None and payload.content is None:
        raise HTTPException(status_code=400, detail="Nothing to update")
    try:
        note = db.get(NoteORM, note_id)
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        if payload.title is not None:
            note.title = payload.title
        if payload.content is not None:
            note.content = payload.content
        # Update updated_at
        db.execute(
            text("UPDATE notes SET updated_at = NOW(), title = :title, content = :content WHERE id = :id"),
            {"id": str(note.id), "title": note.title, "content": note.content},
        )
        db.commit()
        db.refresh(note)
        return Note(
            id=note.id,
            title=note.title,
            content=note.content,
            created_at=note.created_at,
            updated_at=note.updated_at,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")


# PUBLIC_INTERFACE
@app.delete(
    "/notes/{note_id}",
    tags=["notes"],
    summary="Delete note",
    description="Delete a note by its ID.",
)
def delete_note(
    note_id: UUID = Path(..., description="Note ID"),
    db: Session = Depends(get_db),
):
    """Delete a note by ID."""
    try:
        note = db.get(NoteORM, note_id)
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        db.delete(note)
        db.commit()
        return {"status": "deleted", "id": str(note_id)}
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")


# PUBLIC_INTERFACE
@app.get(
    "/docs/websocket-info",
    tags=["health"],
    summary="WebSocket usage info",
    description="This API currently has no WebSocket endpoints. Use REST routes under /notes.",
)
def websocket_info():
    """Info endpoint to clarify WebSocket usage (none for this project)."""
    return {"websocket": "none", "notes_endpoints": ["/notes", "/notes/{id}"]}
