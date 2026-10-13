from datetime import timezone

import httpx
import pytest

from app.database import SessionLocal
from app.models.weather import WeatherObservation
from app.services.weather import (
    OpenMeteoClient,
    WeatherAPIError,
    WeatherResponse,
    WeatherValidationError,
    weather_response_to_observation,
)
from app.services.weather_ingestion import ingest_current_weather


def test_open_meteo_success(monkeypatch):
    """Test successful Open-Meteo response handling."""

    mock_response_data = {
        "latitude": 17.4065,
        "longitude": 78.4772,
        "timezone": "Asia/Kolkata",
        "current": {
            "time": "2026-10-06T18:00",
            "interval": 900,
            "temperature_2m": 30.5,
            "relative_humidity_2m": 60,
            "precipitation": 0.0,
            "wind_speed_10m": 10.5,
            "cloud_cover": 40,
        },
    }

    class MockResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return mock_response_data

    def mock_get(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr(httpx, "get", mock_get)

    client = OpenMeteoClient()
    result = client.get_current_weather()

    assert isinstance(result, WeatherResponse)
    assert result.latitude == 17.4065
    assert result.longitude == 78.4772
    assert result.current.temperature_2m == 30.5
    assert result.current.relative_humidity_2m == 60
    assert result.current.precipitation == 0.0
    assert result.current.wind_speed_10m == 10.5
    assert result.current.cloud_cover == 40


def test_open_meteo_http_failure(monkeypatch):
    """Test handling of an Open-Meteo HTTP/request failure."""

    def mock_get(*args, **kwargs):
        raise httpx.RequestError("Connection failed")

    monkeypatch.setattr(httpx, "get", mock_get)

    client = OpenMeteoClient()

    with pytest.raises(
        WeatherAPIError,
        match="Open-Meteo request failed",
    ):
        client.get_current_weather()


def test_open_meteo_malformed_response(monkeypatch):
    """Test rejection of an invalid Open-Meteo response."""

    mock_response_data = {
        "latitude": 17.4065,
        "longitude": 78.4772,
        "timezone": "Asia/Kolkata",
        "current": {
            "time": "2026-10-06T18:00",
            "interval": 900,
            "temperature_2m": 30.5,
            # relative_humidity_2m is intentionally missing
            "precipitation": 0.0,
            "wind_speed_10m": 10.5,
            "cloud_cover": 40,
        },
    }

    class MockResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return mock_response_data

    def mock_get(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr(httpx, "get", mock_get)

    client = OpenMeteoClient()

    with pytest.raises(
        WeatherValidationError,
        match="Invalid Open-Meteo response",
    ):
        client.get_current_weather()


def test_weather_response_to_observation():
    """Test conversion from validated API response to database model."""

    weather = WeatherResponse.model_validate(
        {
            "latitude": 17.4065,
            "longitude": 78.4772,
            "timezone": "Asia/Kolkata",
            "current": {
                "time": "2026-10-06T18:00",
                "interval": 900,
                "temperature_2m": 30.5,
                "relative_humidity_2m": 60,
                "precipitation": 0.0,
                "wind_speed_10m": 10.5,
                "cloud_cover": 40,
            },
        }
    )

    observation = weather_response_to_observation(weather)

    assert isinstance(observation, WeatherObservation)
    assert observation.latitude == 17.4065
    assert observation.longitude == 78.4772
    assert observation.temperature == 30.5
    assert observation.precipitation == 0.0
    assert observation.humidity == 60
    assert observation.wind_speed == 10.5
    assert observation.cloud_cover == 40


def test_weather_timestamp_is_normalized_to_utc():
    """Test that a naive Hyderabad timestamp is converted to UTC."""

    weather = WeatherResponse.model_validate(
        {
            "latitude": 17.4065,
            "longitude": 78.4772,
            "timezone": "Asia/Kolkata",
            "current": {
                "time": "2026-10-13T17:00",
                "interval": 900,
                "temperature_2m": 30.0,
                "relative_humidity_2m": 60,
                "precipitation": 0.0,
                "wind_speed_10m": 10.0,
                "cloud_cover": 20,
            },
        }
    )

    observation = weather_response_to_observation(weather)

    assert observation.observed_at.isoformat() == (
        "2026-10-13T11:30:00+00:00"
    )
    assert observation.observed_at.utcoffset() == timezone.utc.utcoffset(
        observation.observed_at
    )


def test_weather_database_insertion():
    """Test complete weather ingestion into PostgreSQL."""

    class MockWeatherClient:
        def get_current_weather(self):
            return WeatherResponse.model_validate(
                {
                    "latitude": 17.4065,
                    "longitude": 78.4772,
                    "timezone": "Asia/Kolkata",
                    "current": {
                        "time": "2026-10-06T18:00",
                        "interval": 900,
                        "temperature_2m": 30.5,
                        "relative_humidity_2m": 60,
                        "precipitation": 0.0,
                        "wind_speed_10m": 10.5,
                        "cloud_cover": 40,
                    },
                }
            )

    db = SessionLocal()
    observation = None

    try:
        observation = ingest_current_weather(
            db=db,
            client=MockWeatherClient(),
        )

        assert observation.id is not None
        assert observation.latitude == 17.4065
        assert observation.longitude == 78.4772
        assert observation.temperature == 30.5
        assert observation.precipitation == 0.0
        assert observation.humidity == 60
        assert observation.wind_speed == 10.5
        assert observation.cloud_cover == 40

        assert observation.observed_at.utcoffset() == timezone.utc.utcoffset(
            observation.observed_at
        )

    finally:
        if observation is not None and observation.id is not None:
            db.delete(observation)
            db.commit()

        db.close()