
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from threading import Event
from typing import Literal

from app.config import settings
from app.services.traffic_ingestion import (
    ingest_current_traffic_with_new_session,
)
from app.services.weather_ingestion import (
    ingest_current_weather_with_new_session,
)

logger = logging.getLogger(__name__)

IngestionStatus = Literal["success", "failed", "skipped"]


@dataclass(frozen=True)
class IngestionCycleResult:
    """Outcome of one worker cycle."""

    traffic_status: IngestionStatus
    weather_status: IngestionStatus
    traffic_observation_id: int | None = None
    weather_observation_id: int | None = None
    traffic_error: str | None = None
    weather_error: str | None = None

    @property
    def success(self) -> bool:
        """True when no attempted ingestion failed."""
        return (
            self.traffic_status != "failed"
            and self.weather_status != "failed"
        )


def run_ingestion_cycle(
    *,
    collect_traffic: bool = True,
    collect_weather: bool = True,
) -> IngestionCycleResult:
    """
    Run selected ingestion tasks independently.

    A failure in one task does not prevent the other task from running.
    Each existing ingestion service manages its own database session.
    """

    traffic_status: IngestionStatus = "skipped"
    weather_status: IngestionStatus = "skipped"

    traffic_id: int | None = None
    weather_id: int | None = None

    traffic_error: str | None = None
    weather_error: str | None = None

    if collect_traffic:
        try:
            observation = ingest_current_traffic_with_new_session()
            traffic_id = observation.id
            traffic_status = "success"

            logger.info(
                "Traffic ingestion succeeded: observation_id=%s",
                traffic_id,
            )
        except Exception as exc:
            traffic_status = "failed"
            traffic_error = str(exc)

            logger.exception("Traffic ingestion failed")

    if collect_weather:
        try:
            observation = ingest_current_weather_with_new_session()
            weather_id = observation.id
            weather_status = "success"

            logger.info(
                "Weather ingestion succeeded: observation_id=%s",
                weather_id,
            )
        except Exception as exc:
            weather_status = "failed"
            weather_error = str(exc)

            logger.exception("Weather ingestion failed")

    result = IngestionCycleResult(
        traffic_status=traffic_status,
        weather_status=weather_status,
        traffic_observation_id=traffic_id,
        weather_observation_id=weather_id,
        traffic_error=traffic_error,
        weather_error=weather_error,
    )

    logger.info(
        "Ingestion cycle completed: traffic=%s, weather=%s",
        result.traffic_status,
        result.weather_status,
    )

    return result


def run_forever(
    *,
    traffic_interval_seconds: int | None = None,
    weather_interval_seconds: int | None = None,
    stop_event: Event | None = None,
) -> None:
    """
    Run traffic and weather ingestion on independent schedules.

    Both tasks run on startup. Subsequent runs use their configured
    intervals. Pass a stop_event for graceful shutdown in tests or
    when integrating with a process supervisor.
    """

    traffic_interval = (
        traffic_interval_seconds
        if traffic_interval_seconds is not None
        else settings.ingestion_traffic_interval_seconds
    )

    weather_interval = (
        weather_interval_seconds
        if weather_interval_seconds is not None
        else settings.ingestion_weather_interval_seconds
    )

    if traffic_interval <= 0:
        raise ValueError("Traffic interval must be greater than zero")

    if weather_interval <= 0:
        raise ValueError("Weather interval must be greater than zero")

    stop_event = stop_event or Event()

    next_traffic_at = 0.0
    next_weather_at = 0.0

    logger.info(
        "Starting ingestion worker: traffic_interval=%ss, "
        "weather_interval=%ss",
        traffic_interval,
        weather_interval,
    )

    while not stop_event.is_set():
        now = time.monotonic()

        collect_traffic = now >= next_traffic_at
        collect_weather = now >= next_weather_at

        if collect_traffic or collect_weather:
            run_ingestion_cycle(
                collect_traffic=collect_traffic,
                collect_weather=collect_weather,
            )

            # Measure the next interval from completion of this cycle.
            completed_at = time.monotonic()

            if collect_traffic:
                next_traffic_at = completed_at + traffic_interval

            if collect_weather:
                next_weather_at = completed_at + weather_interval

            continue

        next_run_at = min(next_traffic_at, next_weather_at)
        wait_seconds = max(0.0, next_run_at - time.monotonic())

        # Event.wait allows prompt shutdown instead of an uninterruptible
        # sleep for the entire collection interval.
        stop_event.wait(wait_seconds)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | %(levelname)s | "
            "%(name)s | %(message)s"
        ),
    )

    try:
        run_forever()
    except KeyboardInterrupt:
        logger.info("Ingestion worker stopped by user")


if __name__ == "__main__":
    main()
