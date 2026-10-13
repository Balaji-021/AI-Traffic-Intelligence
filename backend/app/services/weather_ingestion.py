from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.weather import WeatherObservation
from app.services.weather import (
    OpenMeteoClient,
    weather_response_to_observation,
)


class WeatherIngestionError(Exception):
    """Raised when weather ingestion fails."""


def ingest_current_weather(
    db: Session,
    client: OpenMeteoClient | None = None,
) -> WeatherObservation:
    """
    Fetch current weather, validate it, convert it to a
    WeatherObservation, and save it to PostgreSQL.
    """

    client = client or OpenMeteoClient()

    try:
        weather = client.get_current_weather()

        observation = weather_response_to_observation(weather)

        db.add(observation)
        db.commit()
        db.refresh(observation)

        return observation

    except Exception as exc:
        db.rollback()

        raise WeatherIngestionError(
            f"Weather ingestion failed: {exc}"
        ) from exc


def ingest_current_weather_with_new_session() -> WeatherObservation:
    """
    Run weather ingestion using a new database session.
    """

    db = SessionLocal()

    try:
        return ingest_current_weather(db)

    finally:
        db.close()