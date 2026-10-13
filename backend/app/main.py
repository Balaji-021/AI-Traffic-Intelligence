from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db


app = FastAPI(
    title=settings.app_name,
    description="Backend API for the AI Traffic Intelligence platform.",
    version=settings.app_version,
)


@app.get("/")
def root():
    return {
        "message": "AI Traffic Intelligence API is running",
        "version": settings.app_version,
        "environment": settings.app_env,
    }


@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))

    return {
        "status": "healthy",
        "database": "connected",
    }