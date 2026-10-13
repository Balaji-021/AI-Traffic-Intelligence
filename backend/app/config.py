from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # =========================
    # Application
    # =========================
    app_name: str = "AI Traffic Intelligence API"
    app_env: str = "development"
    app_version: str = "0.1.0"

    # =========================
    # Database
    # =========================
    database_url: str

    # =========================
    # Weather Configuration
    # =========================
    weather_latitude: float = 17.4065
    weather_longitude: float = 78.4772
    weather_location_name: str = "Hyderabad"

    # =========================
    # Google Maps / Routes API
    # =========================
    google_maps_api_key: str

    # =========================
    # Traffic Route Configuration
    # =========================
    traffic_route_id: str = "hyderabad_route_1"

    traffic_origin_latitude: float = 17.4065
    traffic_origin_longitude: float = 78.4772

    traffic_destination_latitude: float = 17.4486
    traffic_destination_longitude: float = 78.3908

    traffic_routing_preference: str = "TRAFFIC_AWARE"

    # =========================
    # Background Ingestion
    # =========================
    ingestion_traffic_interval_seconds: int = Field(
        default=300,
        gt=0,
    )

    ingestion_weather_interval_seconds: int = Field(
        default=900,
        gt=0,
    )

    # =========================
    # Environment Configuration
    # =========================
    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()