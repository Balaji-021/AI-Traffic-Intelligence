
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from app.services.historical_dataset import (
    DatasetConfig,
    _add_future_targets,
    _align_weather,
    _validate_traffic,
    _validate_weather,
)


def make_traffic(
    minutes: int,
    *,
    route_id: str = "route_a",
    congestion: float = 1.2,
) -> dict:
    observed_at = datetime(
        2026, 10, 13, 12, 0, tzinfo=timezone.utc
    ) + timedelta(minutes=minutes)

    return {
        "id": minutes + 100,
        "route_id": route_id,
        "observed_at": observed_at,
        "distance_meters": 10000.0,
        "duration_seconds": congestion * 1000.0,
        "static_duration_seconds": 1000.0,
        "congestion_ratio": congestion,
    }


def make_weather(
    minutes: int,
    *,
    latitude: float = 17.4065,
    longitude: float = 78.4772,
) -> dict:
    observed_at = datetime(
        2026, 10, 13, 12, 0, tzinfo=timezone.utc
    ) + timedelta(minutes=minutes)

    return {
        "id": minutes + 200,
        "observed_at": observed_at,
        "latitude": latitude,
        "longitude": longitude,
        "temperature": 30.0,
        "precipitation": 0.0,
        "humidity": 50.0,
        "wind_speed": 5.0,
        "cloud_cover": 20.0,
    }


def traffic_frame(records: list[dict]) -> pd.DataFrame:
    from app.services.historical_dataset import _traffic_frame

    objects = [
        SimpleNamespace(**record)
        for record in records
    ]
    return _traffic_frame(objects)


def weather_frame(records: list[dict]) -> pd.DataFrame:
    from app.services.historical_dataset import _weather_frame

    objects = [
        SimpleNamespace(**record)
        for record in records
    ]
    return _weather_frame(objects)


def test_dataset_config_rejects_negative_weather_age():
    with pytest.raises(ValueError):
        DatasetConfig(weather_max_age_minutes=-1)


def test_dataset_config_rejects_negative_target_tolerance():
    with pytest.raises(ValueError):
        DatasetConfig(target_tolerance_minutes=-1)


def test_traffic_validation_rejects_inconsistent_ratio():
    record = make_traffic(0)
    record["congestion_ratio"] = 9.0

    clean, invalid_count = _validate_traffic(
        traffic_frame([record])
    )

    assert clean.empty
    assert invalid_count == 1


def test_traffic_validation_rejects_nonpositive_duration():
    record = make_traffic(0)
    record["duration_seconds"] = 0.0

    clean, invalid_count = _validate_traffic(
        traffic_frame([record])
    )

    assert clean.empty
    assert invalid_count == 1


def test_traffic_validation_removes_duplicate_route_timestamps():
    record = make_traffic(0)

    clean, invalid_count = _validate_traffic(
        traffic_frame([record, record.copy()])
    )

    assert len(clean) == 1
    assert invalid_count == 1


def test_weather_validation_rejects_invalid_humidity():
    record = make_weather(0)
    record["humidity"] = 101.0

    clean, invalid_count = _validate_weather(
        weather_frame([record])
    )

    assert clean.empty
    assert invalid_count == 1


def test_weather_validation_allows_zero_precipitation():
    clean, invalid_count = _validate_weather(
        weather_frame([make_weather(0)])
    )

    assert len(clean) == 1
    assert invalid_count == 0
    assert clean.iloc[0]["precipitation"] == 0.0


def test_weather_alignment_never_uses_future_weather():
    traffic = traffic_frame([make_traffic(10)])
    weather = weather_frame([make_weather(15)])

    result = _align_weather(
        traffic,
        weather,
        max_age_minutes=30,
    )

    assert pd.isna(result.iloc[0]["temperature"])
    assert pd.isna(result.iloc[0]["weather_observed_at"])


def test_weather_alignment_uses_latest_past_observation():
    traffic = traffic_frame([make_traffic(20)])
    weather = weather_frame([
        make_weather(0),
        make_weather(15),
    ])

    result = _align_weather(
        traffic,
        weather,
        max_age_minutes=30,
    )

    assert result.iloc[0]["temperature"] == 30.0
    assert result.iloc[0]["weather_age_minutes"] == 5.0


def test_weather_alignment_respects_maximum_age():
    traffic = traffic_frame([make_traffic(40)])
    weather = weather_frame([make_weather(0)])

    result = _align_weather(
        traffic,
        weather,
        max_age_minutes=30,
    )

    assert pd.isna(result.iloc[0]["temperature"])



def test_future_target_requires_requested_time_tolerance():
    traffic = pd.DataFrame([
        {
            **make_traffic(0),
            "observed_at": pd.Timestamp(
                "2026-10-13T12:00:00Z"
            ),
        },
        {
            **make_traffic(17),
            "observed_at": pd.Timestamp(
                "2026-10-13T12:17:00Z"
            ),
        },
    ])

    result, unmatched = _add_future_targets(
        traffic,
        tolerance_minutes=2,
    )

    # 12:17 is two minutes after the requested 12:15 target.
    assert result.iloc[0]["target_congestion_15m"] == pytest.approx(
        1.2
    )

    # The second observation has no matching observation 15 minutes ahead.
    assert unmatched["target_congestion_15m"] == 1



def test_future_target_does_not_use_observation_outside_tolerance():
    traffic = pd.DataFrame([
        {
            **make_traffic(0),
            "observed_at": pd.Timestamp(
                "2026-10-13T12:00:00Z"
            ),
        },
        {
            **make_traffic(20),
            "observed_at": pd.Timestamp(
                "2026-10-13T12:20:00Z"
            ),
        },
    ])

    result, unmatched = _add_future_targets(
        traffic,
        tolerance_minutes=2,
    )

    assert pd.isna(result.iloc[0]["target_congestion_15m"])
    assert unmatched["target_congestion_15m"] == 2


def test_future_targets_are_separated_by_route():
    first = make_traffic(0, route_id="route_a")
    second = make_traffic(15, route_id="route_b")

    traffic = pd.DataFrame([
        {
            **first,
            "observed_at": pd.Timestamp(first["observed_at"]),
        },
        {
            **second,
            "observed_at": pd.Timestamp(second["observed_at"]),
        },
    ])

    result, _ = _add_future_targets(
        traffic,
        tolerance_minutes=2,
    )

    assert pd.isna(result.iloc[0]["target_congestion_15m"])
    assert pd.isna(result.iloc[1]["target_congestion_15m"])


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
        "observed_at": [pd.Timestamp("2026-10-13T20:00:00Z")],
    })

    result = _add_time_features(frame)

    assert result.iloc[0]["hour"] == 1
    assert result.iloc[0]["day_of_week"] == 2
    assert result.iloc[0]["is_weekend"] == 0


def test_target_tolerance_cannot_reach_shortest_horizon():
    import pytest

    from app.services.historical_dataset import DatasetConfig

    with pytest.raises(ValueError, match="shortest target horizon"):
        DatasetConfig(target_tolerance_minutes=15)
