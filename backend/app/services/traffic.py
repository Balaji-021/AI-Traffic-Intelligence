from datetime import datetime, timezone

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import settings


class TrafficAPIError(Exception):
    """Raised when the Google Routes API request fails."""


class TrafficValidationError(Exception):
    """Raised when the Google Routes response is invalid."""


class GoogleRoute(BaseModel):
    """Validated route information returned by Google."""

    model_config = ConfigDict(extra="ignore")

    distanceMeters: int = Field(gt=0)
    duration: str
    staticDuration: str


class GoogleRoutesResponse(BaseModel):
    """Validated Google Routes API response."""

    model_config = ConfigDict(extra="ignore")

    routes: list[GoogleRoute]


class TrafficRoute(BaseModel):
    """Normalized traffic data ready for ingestion."""

    observed_at: datetime
    distance_meters: float = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    static_duration_seconds: float = Field(gt=0)
    congestion_ratio: float = Field(gt=0)


class GoogleRoutesClient:
    """Client for Google Routes Compute Routes API."""

    BASE_URL = (
        "https://routes.googleapis.com/directions/v2:computeRoutes"
    )

    FIELD_MASK = (
        "routes.distanceMeters,"
        "routes.duration,"
        "routes.staticDuration"
    )

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    @staticmethod
    def _parse_duration(value: str) -> float:
        """Convert a Google duration such as '2930s' to seconds."""

        if not value.endswith("s"):
            raise ValueError("Duration must end with 's'.")

        seconds = float(value[:-1])

        if not seconds > 0 or not seconds < float("inf"):
            raise ValueError("Duration must be finite and positive.")

        return seconds

    def get_route(self) -> TrafficRoute:
        """Fetch and validate traffic-aware route information."""

        payload = {
            "origin": {
                "location": {
                    "latLng": {
                        "latitude": settings.traffic_origin_latitude,
                        "longitude": settings.traffic_origin_longitude,
                    }
                }
            },
            "destination": {
                "location": {
                    "latLng": {
                        "latitude": settings.traffic_destination_latitude,
                        "longitude": settings.traffic_destination_longitude,
                    }
                }
            },
            "travelMode": "DRIVE",
            "routingPreference": settings.traffic_routing_preference,
        }

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": settings.google_maps_api_key,
            "X-Goog-FieldMask": self.FIELD_MASK,
        }

        try:
            response = httpx.post(
                self.BASE_URL,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()

        except httpx.HTTPError as exc:
            # Do not include request headers or the API key in errors.
            raise TrafficAPIError(
                f"Google Routes request failed: {type(exc).__name__}"
            ) from exc

        try:
            data = GoogleRoutesResponse.model_validate(response.json())

            if not data.routes:
                raise TrafficValidationError(
                    "Google Routes returned no routes."
                )

            route = data.routes[0]
            duration = self._parse_duration(route.duration)
            static_duration = self._parse_duration(route.staticDuration)

            return TrafficRoute(
                observed_at=datetime.now(timezone.utc),
                distance_meters=route.distanceMeters,
                duration_seconds=duration,
                static_duration_seconds=static_duration,
                congestion_ratio=duration / static_duration,
            )

        except (ValidationError, ValueError, TypeError) as exc:
            raise TrafficValidationError(
                "Google Routes returned invalid route data."
            ) from exc