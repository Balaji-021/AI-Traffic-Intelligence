from datetime import datetime, timezone

import httpx
import pytest

from app.config import settings
from app.database import SessionLocal
from app.models.traffic import TrafficObservation
from app.services.traffic import (
    GoogleRoutesClient,
    TrafficAPIError,
    TrafficRoute,
    TrafficValidationError,
)
from app.services.traffic_ingestion import (
    TrafficIngestionError,
    ingest_current_traffic,
)


def mock_response(data):
    """Create a mock Google Routes API response."""

    class MockResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return data

    return MockResponse()


def test_google_routes_success(monkeypatch):
    """Validate a successful Google Routes response."""

    response_data = {
        "routes": [
            {
                "distanceMeters": 14093,
                "duration": "2930s",
                "staticDuration": "2373s",
            }
        ]
    }

    def mock_post(*args, **kwargs):
        assert kwargs["json"]["travelMode"] == "DRIVE"
        assert (
            kwargs["headers"]["X-Goog-FieldMask"]
            == GoogleRoutesClient.FIELD_MASK
        )
        return mock_response(response_data)

    monkeypatch.setattr(httpx, "post", mock_post)

    result = GoogleRoutesClient().get_route()

    assert isinstance(result, TrafficRoute)
    assert result.distance_meters == 14093
    assert result.duration_seconds == 2930
    assert result.static_duration_seconds == 2373
    assert result.congestion_ratio == pytest.approx(2930 / 2373)
    assert result.observed_at.tzinfo is not None


def test_google_routes_http_failure(monkeypatch):
    """Convert HTTP failures into a safe API exception."""

    def mock_post(*args, **kwargs):
        request = httpx.Request(
            "POST",
            GoogleRoutesClient.BASE_URL,
        )
        raise httpx.ConnectError(
            "Connection failed",
            request=request,
        )

    monkeypatch.setattr(httpx, "post", mock_post)

    with pytest.raises(
        TrafficAPIError,
        match="Google Routes request failed",
    ):
        GoogleRoutesClient().get_route()


def test_google_routes_empty_response(monkeypatch):
    """Reject responses with no routes."""

    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: mock_response({"routes": []}),
    )

    with pytest.raises(
        TrafficValidationError,
        match="returned no routes",
    ):
        GoogleRoutesClient().get_route()


def test_google_routes_invalid_duration(monkeypatch):
    """Reject invalid duration values."""

    response_data = {
        "routes": [
            {
                "distanceMeters": 14093,
                "duration": "unknown",
                "staticDuration": "2373s",
            }
        ]
    }

    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: mock_response(response_data),
    )

    with pytest.raises(
        TrafficValidationError,
        match="invalid route data",
    ):
        GoogleRoutesClient().get_route()


def test_google_routes_missing_field(monkeypatch):
    """Reject incomplete route responses."""

    response_data = {
        "routes": [
            {
                "distanceMeters": 14093,
                "duration": "2930s",
            }
        ]
    }

    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: mock_response(response_data),
    )

    with pytest.raises(TrafficValidationError):
        GoogleRoutesClient().get_route()


def test_traffic_database_insertion():
    """Test complete traffic ingestion into PostgreSQL."""

    class MockTrafficClient:
        def get_route(self):
            return TrafficRoute(
                observed_at=datetime.now(timezone.utc),
                distance_meters=14093,
                duration_seconds=2930,
                static_duration_seconds=2373,
                congestion_ratio=2930 / 2373,
            )

    db = SessionLocal()
    observation = None

    try:
        observation = ingest_current_traffic(
            db=db,
            client=MockTrafficClient(),
        )

        assert isinstance(observation, TrafficObservation)
        assert observation.id is not None
        assert observation.route_id == settings.traffic_route_id
        assert observation.distance_meters == 14093
        assert observation.duration_seconds == 2930
        assert observation.static_duration_seconds == 2373
        assert observation.congestion_ratio == pytest.approx(
            2930 / 2373
        )

    finally:
        if observation is not None and observation.id is not None:
            db.delete(observation)
            db.commit()

        db.close()


def test_traffic_ingestion_rolls_back_on_failure():
    """Verify rollback when route retrieval fails."""

    class MockTrafficClient:
        def get_route(self):
            raise TrafficAPIError("Simulated API failure")

    class MockDatabaseSession:
        def __init__(self):
            self.rollback_called = False

        def rollback(self):
            self.rollback_called = True

    db = MockDatabaseSession()

    with pytest.raises(
        TrafficIngestionError,
        match="Traffic ingestion failed",
    ):
        ingest_current_traffic(
            db=db,
            client=MockTrafficClient(),
        )

    assert db.rollback_called is True