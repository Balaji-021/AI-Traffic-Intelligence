from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.traffic import TrafficObservation
from app.services.traffic import GoogleRoutesClient


class TrafficIngestionError(Exception):
    """Raised when traffic ingestion fails."""


def ingest_current_traffic(
    db: Session,
    client: GoogleRoutesClient | None = None,
) -> TrafficObservation:
    """
    Fetch route data, normalize it, and persist an observation.
    """

    client = client or GoogleRoutesClient()

    try:
        route = client.get_route()

        observation = TrafficObservation(
            route_id=settings.traffic_route_id,
            observed_at=route.observed_at,
            distance_meters=route.distance_meters,
            duration_seconds=route.duration_seconds,
            static_duration_seconds=route.static_duration_seconds,
            congestion_ratio=route.congestion_ratio,
        )

        db.add(observation)
        db.commit()
        db.refresh(observation)

        return observation

    except Exception as exc:
        db.rollback()

        raise TrafficIngestionError(
            f"Traffic ingestion failed: {exc}"
        ) from exc


def ingest_current_traffic_with_new_session() -> TrafficObservation:
    """Run traffic ingestion using a new database session."""

    db = SessionLocal()

    try:
        return ingest_current_traffic(db)

    finally:
        db.close()