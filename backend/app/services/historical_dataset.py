
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.traffic import TrafficObservation
from app.models.weather import WeatherObservation


# ---------------------------------------------------------------------------
# Configuration and column definitions
# ---------------------------------------------------------------------------

TARGET_HORIZONS_MINUTES = (15, 30, 60)

TRAFFIC_COLUMNS = [
    "id",
    "route_id",
    "observed_at",
    "distance_meters",
    "duration_seconds",
    "static_duration_seconds",
    "congestion_ratio",
]

WEATHER_COLUMNS = [
    "id",
    "observed_at",
    "latitude",
    "longitude",
    "temperature",
    "precipitation",
    "humidity",
    "wind_speed",
    "cloud_cover",
]

NUMERIC_TRAFFIC_COLUMNS = [
    "distance_meters",
    "duration_seconds",
    "static_duration_seconds",
    "congestion_ratio",
]

NUMERIC_WEATHER_COLUMNS = [
    "temperature",
    "precipitation",
    "humidity",
    "wind_speed",
    "cloud_cover",
]

WEATHER_FEATURE_COLUMNS = [
    "temperature",
    "precipitation",
    "humidity",
    "wind_speed",
    "cloud_cover",
]

DEFAULT_WEATHER_MAX_AGE_MINUTES = 30
DEFAULT_TARGET_TOLERANCE_MINUTES = 2
DEFAULT_LOCAL_TIMEZONE = "Asia/Kolkata"


@dataclass(frozen=True)
class DatasetConfig:
    """Configuration for time-aware historical dataset generation."""

    weather_max_age_minutes: int = DEFAULT_WEATHER_MAX_AGE_MINUTES
    target_tolerance_minutes: int = DEFAULT_TARGET_TOLERANCE_MINUTES

    def __post_init__(self) -> None:
        if self.weather_max_age_minutes < 0:
            raise ValueError(
                "weather_max_age_minutes cannot be negative"
            )

        if self.target_tolerance_minutes < 0:
            raise ValueError(
                "target_tolerance_minutes cannot be negative"
            )

        if (
            self.target_tolerance_minutes
            >= min(TARGET_HORIZONS_MINUTES)
        ):
            raise ValueError(
                "target_tolerance_minutes must be less than "
                "the shortest target horizon"
            )


@dataclass
class DatasetReport:
    """Quality and generation statistics for a historical dataset."""

    traffic_records_loaded: int
    weather_records_loaded: int
    invalid_traffic_records: int
    invalid_weather_records: int
    duplicate_traffic_records: int
    duplicate_weather_records: int
    weather_unavailable_rows: int
    unmatched_targets: dict[str, int]
    output_rows: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HistoricalDatasetResult:
    """Dataset and its associated quality report."""

    dataset: pd.DataFrame
    report: DatasetReport


# ---------------------------------------------------------------------------
# Convert database records to pandas DataFrames
# ---------------------------------------------------------------------------

def _traffic_frame(
    records: list[TrafficObservation],
) -> pd.DataFrame:
    rows = [
        {
            column: getattr(record, column)
            for column in TRAFFIC_COLUMNS
        }
        for record in records
    ]

    frame = pd.DataFrame(rows, columns=TRAFFIC_COLUMNS)

    if not frame.empty:
        # Store timestamps in UTC for reliable temporal matching.
        frame["observed_at"] = pd.to_datetime(
            frame["observed_at"],
            utc=True,
            errors="coerce",
        )

        for column in NUMERIC_TRAFFIC_COLUMNS:
            frame[column] = pd.to_numeric(
                frame[column],
                errors="coerce",
            )

    return frame


def _weather_frame(
    records: list[WeatherObservation],
) -> pd.DataFrame:
    rows = [
        {
            column: getattr(record, column)
            for column in WEATHER_COLUMNS
        }
        for record in records
    ]

    frame = pd.DataFrame(rows, columns=WEATHER_COLUMNS)

    if not frame.empty:
        frame["observed_at"] = pd.to_datetime(
            frame["observed_at"],
            utc=True,
            errors="coerce",
        )

        for column in ["latitude", "longitude", *NUMERIC_WEATHER_COLUMNS]:
            frame[column] = pd.to_numeric(
                frame[column],
                errors="coerce",
            )

    return frame


# ---------------------------------------------------------------------------
# Data validation
# ---------------------------------------------------------------------------

def _validate_traffic(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    """
    Remove invalid traffic observations and duplicate route timestamps.

    Returns:
        Clean DataFrame and total number of excluded records.
    """

    if frame.empty:
        return frame.copy(), 0

    valid = (
        frame["route_id"].notna()
        & frame["route_id"].astype(str).str.strip().ne("")
    )

    valid &= frame["observed_at"].notna()

    for column in NUMERIC_TRAFFIC_COLUMNS:
        valid &= np.isfinite(frame[column])

    valid &= frame["distance_meters"] > 0
    valid &= frame["duration_seconds"] > 0
    valid &= frame["static_duration_seconds"] > 0
    valid &= frame["congestion_ratio"] > 0

    calculated_ratio = (
        frame["duration_seconds"]
        / frame["static_duration_seconds"].replace(0, np.nan)
    )

    valid &= np.isclose(
        frame["congestion_ratio"],
        calculated_ratio,
        rtol=1e-5,
        atol=1e-8,
        equal_nan=False,
    )

    # First remove invalid rows, then deduplicate the valid rows.
    valid_frame = frame.loc[valid].copy()

    deduplicated_frame = valid_frame.drop_duplicates(
        subset=["route_id", "observed_at"],
        keep="first",
    )

    excluded_count = len(frame) - len(deduplicated_frame)

    return deduplicated_frame, excluded_count


def _validate_weather(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    """
    Remove invalid weather observations and duplicate timestamp/location keys.

    Returns:
        Clean DataFrame and total number of excluded records.
    """

    if frame.empty:
        return frame.copy(), 0

    valid = frame["observed_at"].notna()

    for column in [
        "latitude",
        "longitude",
        *NUMERIC_WEATHER_COLUMNS,
    ]:
        valid &= np.isfinite(frame[column])

    valid &= frame["latitude"].between(-90, 90)
    valid &= frame["longitude"].between(-180, 180)
    valid &= frame["precipitation"] >= 0
    valid &= frame["humidity"].between(0, 100)
    valid &= frame["wind_speed"] >= 0
    valid &= frame["cloud_cover"].between(0, 100)

    valid_frame = frame.loc[valid].copy()

    deduplicated_frame = valid_frame.drop_duplicates(
        subset=["observed_at", "latitude", "longitude"],
        keep="first",
    )

    excluded_count = len(frame) - len(deduplicated_frame)

    return deduplicated_frame, excluded_count


# ---------------------------------------------------------------------------
# Weather alignment
# ---------------------------------------------------------------------------

def _align_weather(
    traffic: pd.DataFrame,
    weather: pd.DataFrame,
    max_age_minutes: int,
) -> pd.DataFrame:
    """
    Attach the latest past weather observation to each traffic observation.

    Future weather observations are never used.

    This implementation supports one weather location at a time. If multiple
    locations are present, it fails explicitly rather than mixing locations.
    """

    result = traffic.copy()

    for column in WEATHER_FEATURE_COLUMNS:
        result[column] = np.nan

    result["weather_observed_at"] = pd.Series(
        pd.NaT,
        index=result.index,
        dtype="datetime64[ns, UTC]",
    )
    result["weather_age_minutes"] = np.nan

    if traffic.empty or weather.empty:
        return result

    locations = weather[
        ["latitude", "longitude"]
    ].drop_duplicates()

    if len(locations) > 1:
        raise ValueError(
            "Weather observations contain multiple locations. "
            "Select the weather location appropriate to the route "
            "before building the historical dataset."
        )

    available_weather = weather.sort_values(
        "observed_at"
    ).copy()

    available_weather = available_weather[
        ["observed_at", *WEATHER_FEATURE_COLUMNS]
    ].rename(
        columns={"observed_at": "weather_observed_at"}
    )

    left = traffic.sort_values("observed_at").copy()

    aligned = pd.merge_asof(
        left,
        available_weather,
        left_on="observed_at",
        right_on="weather_observed_at",
        direction="backward",
        tolerance=pd.Timedelta(minutes=max_age_minutes),
    )

    aligned["weather_age_minutes"] = (
        aligned["observed_at"] - aligned["weather_observed_at"]
    ).dt.total_seconds() / 60

    return aligned


# ---------------------------------------------------------------------------
# Time and historical traffic features
# ---------------------------------------------------------------------------

def _add_time_features(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """
    Add calendar features using Hyderabad local time.

    The original observed_at column remains in UTC.
    """

    result = frame.copy()

    local_time = result["observed_at"].dt.tz_convert(
        DEFAULT_LOCAL_TIMEZONE
    )

    result["hour"] = local_time.dt.hour
    result["day_of_week"] = local_time.dt.dayofweek

    result["is_weekend"] = (
        result["day_of_week"] >= 5
    ).astype("int8")

    return result


def _add_traffic_lags(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """
    Add exact-time traffic lags.

    Missing historical timestamps remain NaN. No future observations or
    approximate timestamps are substituted for missing lag values.
    """

    result = frame.copy()

    for lag_minutes in (5, 15, 30):
        result[f"congestion_ratio_lag_{lag_minutes}m"] = np.nan
        result[f"duration_seconds_lag_{lag_minutes}m"] = np.nan

    for _, group in result.groupby("route_id", sort=False):
        lookup = group.set_index("observed_at")

        for index, row in group.iterrows():
            timestamp = row["observed_at"]

            for lag_minutes in (5, 15, 30):
                lag_time = timestamp - pd.Timedelta(
                    minutes=lag_minutes
                )

                if lag_time not in lookup.index:
                    continue

                previous = lookup.loc[lag_time]

                result.loc[
                    index,
                    f"congestion_ratio_lag_{lag_minutes}m",
                ] = previous["congestion_ratio"]

                result.loc[
                    index,
                    f"duration_seconds_lag_{lag_minutes}m",
                ] = previous["duration_seconds"]

    return result


# ---------------------------------------------------------------------------
# Future prediction targets
# ---------------------------------------------------------------------------

def _add_future_targets(
    frame: pd.DataFrame,
    tolerance_minutes: int,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """
    Create congestion targets for 15, 30, and 60 minutes in the future.

    A target must be strictly later than the current observation and within
    the configured tolerance of the requested target timestamp.
    """

    result = frame.copy()
    unmatched: dict[str, int] = {}

    for horizon in TARGET_HORIZONS_MINUTES:
        target_name = f"target_congestion_{horizon}m"
        result[target_name] = np.nan
        unmatched[target_name] = len(result)

    if result.empty:
        return result, unmatched

    tolerance = pd.Timedelta(minutes=tolerance_minutes)

    for _, group in result.groupby("route_id", sort=False):
        group = group.sort_values("observed_at")

        future = group[
            ["observed_at", "congestion_ratio"]
        ].rename(
            columns={
                "observed_at": "target_observed_at",
                "congestion_ratio": "target_value",
            }
        )

        for index, row in group.iterrows():
            current_time = row["observed_at"]

            for horizon in TARGET_HORIZONS_MINUTES:
                target_name = f"target_congestion_{horizon}m"

                requested_time = current_time + pd.Timedelta(
                    minutes=horizon
                )

                # Require a genuinely future observation within tolerance.
                candidates = future[
                    (future["target_observed_at"] > current_time)
                    & (
                        future["target_observed_at"] - requested_time
                    ).abs().le(tolerance)
                ]

                if candidates.empty:
                    continue

                # Choose the closest observation. If equally close, choose
                # the earlier observation for deterministic results.
                candidates = candidates.assign(
                    time_difference=(
                        candidates["target_observed_at"]
                        - requested_time
                    ).abs()
                ).sort_values(
                    ["time_difference", "target_observed_at"]
                )

                result.loc[index, target_name] = (
                    candidates.iloc[0]["target_value"]
                )

    for horizon in TARGET_HORIZONS_MINUTES:
        target_name = f"target_congestion_{horizon}m"

        unmatched[target_name] = int(
            result[target_name].isna().sum()
        )

    return result, unmatched


# ---------------------------------------------------------------------------
# Historical dataset builder
# ---------------------------------------------------------------------------

def build_historical_dataset(
    db: Session,
    config: DatasetConfig | None = None,
) -> HistoricalDatasetResult:
    """
    Load observations from PostgreSQL and construct an ML-ready dataset.

    This function is read-only. It never inserts, updates, or deletes
    database records.
    """

    config = config or DatasetConfig()

    # Load observations in chronological order.
    traffic_records = list(
        db.scalars(
            select(TrafficObservation).order_by(
                TrafficObservation.observed_at
            )
        ).all()
    )

    weather_records = list(
        db.scalars(
            select(WeatherObservation).order_by(
                WeatherObservation.observed_at
            )
        ).all()
    )

    traffic = _traffic_frame(traffic_records)
    weather = _weather_frame(weather_records)

    original_traffic_count = len(traffic)
    original_weather_count = len(weather)

    # Count duplicate keys among valid records so that invalid and duplicate
    # exclusions can be reported separately.
    valid_traffic_mask = pd.Series(
        True,
        index=traffic.index,
        dtype=bool,
    )

    if not traffic.empty:
        valid_traffic_mask &= (
            traffic["route_id"].notna()
            & traffic["route_id"].astype(str).str.strip().ne("")
        )
        valid_traffic_mask &= traffic["observed_at"].notna()

        for column in NUMERIC_TRAFFIC_COLUMNS:
            valid_traffic_mask &= np.isfinite(traffic[column])

        valid_traffic_mask &= traffic["distance_meters"] > 0
        valid_traffic_mask &= traffic["duration_seconds"] > 0
        valid_traffic_mask &= traffic["static_duration_seconds"] > 0
        valid_traffic_mask &= traffic["congestion_ratio"] > 0

        calculated_ratio = (
            traffic["duration_seconds"]
            / traffic["static_duration_seconds"].replace(0, np.nan)
        )

        valid_traffic_mask &= np.isclose(
            traffic["congestion_ratio"],
            calculated_ratio,
            rtol=1e-5,
            atol=1e-8,
            equal_nan=False,
        )

    duplicate_traffic = int(
        traffic.loc[valid_traffic_mask].duplicated(
            subset=["route_id", "observed_at"],
            keep="first",
        ).sum()
    )

    valid_weather_mask = pd.Series(
        True,
        index=weather.index,
        dtype=bool,
    )

    if not weather.empty:
        valid_weather_mask &= weather["observed_at"].notna()

        for column in [
            "latitude",
            "longitude",
            *NUMERIC_WEATHER_COLUMNS,
        ]:
            valid_weather_mask &= np.isfinite(weather[column])

        valid_weather_mask &= weather["latitude"].between(-90, 90)
        valid_weather_mask &= weather["longitude"].between(-180, 180)
        valid_weather_mask &= weather["precipitation"] >= 0
        valid_weather_mask &= weather["humidity"].between(0, 100)
        valid_weather_mask &= weather["wind_speed"] >= 0
        valid_weather_mask &= weather["cloud_cover"].between(0, 100)

    duplicate_weather = int(
        weather.loc[valid_weather_mask].duplicated(
            subset=["observed_at", "latitude", "longitude"],
            keep="first",
        ).sum()
    )

    traffic, excluded_traffic = _validate_traffic(traffic)
    weather, excluded_weather = _validate_weather(weather)

    invalid_traffic = max(
        0,
        excluded_traffic - duplicate_traffic,
    )

    invalid_weather = max(
        0,
        excluded_weather - duplicate_weather,
    )

    # Align weather without looking into the future.
    dataset = _align_weather(
        traffic,
        weather,
        config.weather_max_age_minutes,
    )

    # Generate time features, historical lags, and future targets.
    dataset = _add_time_features(dataset)
    dataset = _add_traffic_lags(dataset)

    dataset, unmatched_targets = _add_future_targets(
        dataset,
        config.target_tolerance_minutes,
    )

    weather_unavailable = int(
        dataset["weather_observed_at"].isna().sum()
    )

    dataset = dataset.sort_values(
        ["route_id", "observed_at"]
    ).reset_index(drop=True)

    report = DatasetReport(
        traffic_records_loaded=original_traffic_count,
        weather_records_loaded=original_weather_count,
        invalid_traffic_records=invalid_traffic,
        invalid_weather_records=invalid_weather,
        duplicate_traffic_records=duplicate_traffic,
        duplicate_weather_records=duplicate_weather,
        weather_unavailable_rows=weather_unavailable,
        unmatched_targets=unmatched_targets,
        output_rows=len(dataset),
    )

    return HistoricalDatasetResult(
        dataset=dataset,
        report=report,
    )



def test_weather_alignment_rejects_multiple_locations():
    import pandas as pd
    import pytest

    from app.services.historical_dataset import _align_weather

    traffic = pd.DataFrame({
        "route_id": ["hyderabad_route_1"],
        "observed_at": [pd.Timestamp("2026-10-13T12:00:00Z")],
    })

    weather = pd.DataFrame({
        "observed_at": [
            pd.Timestamp("2026-10-13T11:55:00Z"),
            pd.Timestamp("2026-10-13T11:56:00Z"),
        ],
        "latitude": [17.4, 17.5],
        "longitude": [78.4, 78.6],
        "temperature": [30.0, 31.0],
        "precipitation": [0.0, 0.0],
        "humidity": [50.0, 51.0],
        "wind_speed": [10.0, 11.0],
        "cloud_cover": [20.0, 25.0],
    })

    with pytest.raises(ValueError, match="multiple locations"):
        _align_weather(traffic, weather, max_age_minutes=30)


def test_time_features_use_hyderabad_timezone():
    import pandas as pd

    from app.services.historical_dataset import _add_time_features

    frame = pd.DataFrame({
        "observed_at": [
            pd.Timestamp("2026-10-13T20:00:00Z"),
        ],
    })

    result = _add_time_features(frame)

    # 20:00 UTC is 01:30 on Wednesday in Hyderabad.
    assert result.iloc[0]["hour"] == 1
    assert result.iloc[0]["day_of_week"] == 2
    assert result.iloc[0]["is_weekend"] == 0


def test_target_tolerance_cannot_reach_shortest_horizon():
    import pytest

    from app.services.historical_dataset import DatasetConfig

    with pytest.raises(
        ValueError,
        match="shortest target horizon",
    ):
        DatasetConfig(target_tolerance_minutes=15)
