import os


class Settings:
    app_name: str = os.getenv(
        "APP_NAME",
        "AI Traffic Intelligence API",
    )

    app_env: str = os.getenv(
        "APP_ENV",
        "development",
    )

    app_version: str = os.getenv(
        "APP_VERSION",
        "0.1.0",
    )

    database_url: str = os.getenv(
        "DATABASE_URL",
        "",
    )

    google_maps_api_key: str = os.getenv(
        "GOOGLE_MAPS_API_KEY",
        "",
    )


settings = Settings()