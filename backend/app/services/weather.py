from datetime import datetime

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import settings
from app.models.weather import WeatherObservation


class WeatherAPIError(Exception):
    """Raised when the Open-Meteo API request fails."""


class WeatherValidationError(Exception):
    """Raised when the Open-Meteo response is invalid."""


class CurrentWeather(BaseModel):
    """Validated current weather values returned by Open-Meteo."""

    model_config = ConfigDict(extra="ignore")

    time: datetime
    interval: int = Field(gt=0)
    temperature_2m: float
    relative_humidity_2m: float = Field(ge=0, le=100)
    precipitation: float = Field(ge=0)
    wind_speed_10m: float = Field(ge=0)
    cloud_cover: float = Field(ge=0, le=100)


class WeatherResponse(BaseModel):
    """Validated Open-Meteo response."""

    model_config = ConfigDict(extra="ignore")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str
    current: CurrentWeather


class OpenMeteoClient:
    """Client for communicating with the Open-Meteo API."""

    BASE_URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def get_current_weather(
        self,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> WeatherResponse:
        """Fetch and validate current weather data from Open-Meteo."""

        latitude = (
            settings.weather_latitude
            if latitude is None
            else latitude
        )

        longitude = (
            settings.weather_longitude
            if longitude is None
            else longitude
        )

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": (
                "temperature_2m,"
                "relative_humidity_2m,"
                "precipitation,"
                "wind_speed_10m,"
                "cloud_cover"
            ),
            "timezone": "auto",
        }

        try:
            response = httpx.get(
                self.BASE_URL,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()

        except httpx.HTTPError as exc:
            raise WeatherAPIError(
                f"Open-Meteo request failed: {exc}"
            ) from exc

        try:
            return WeatherResponse.model_validate(response.json())

        except ValidationError as exc:
            raise WeatherValidationError(
                f"Invalid Open-Meteo response: {exc}"
            ) from exc


def weather_response_to_observation(
    weather: WeatherResponse,
) -> WeatherObservation:
    """Convert a validated Open-Meteo response into a WeatherObservation."""

    return WeatherObservation(
        observed_at=weather.current.time,
        latitude=weather.latitude,
        longitude=weather.longitude,
        temperature=weather.current.temperature_2m,
        precipitation=weather.current.precipitation,
        humidity=weather.current.relative_humidity_2m,
        wind_speed=weather.current.wind_speed_10m,
        cloud_cover=weather.current.cloud_cover,
    )