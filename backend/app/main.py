from fastapi import FastAPI

from backend.app.config import settings


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
def health_check():
    return {
        "status": "healthy"
    }