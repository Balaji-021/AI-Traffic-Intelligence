
from threading import Event
from types import SimpleNamespace

import pytest

from app.services import ingestion_worker


def test_ingestion_cycle_succeeds_for_both_services(monkeypatch):
    monkeypatch.setattr(
        ingestion_worker,
        "ingest_current_traffic_with_new_session",
        lambda: SimpleNamespace(id=101),
    )
    monkeypatch.setattr(
        ingestion_worker,
        "ingest_current_weather_with_new_session",
        lambda: SimpleNamespace(id=202),
    )

    result = ingestion_worker.run_ingestion_cycle()

    assert result.success is True
    assert result.traffic_status == "success"
    assert result.weather_status == "success"
    assert result.traffic_observation_id == 101
    assert result.weather_observation_id == 202


def test_weather_runs_even_when_traffic_fails(monkeypatch):
    weather_called = False

    def fail_traffic():
        raise RuntimeError("Simulated traffic API failure")

    def succeed_weather():
        nonlocal weather_called
        weather_called = True
        return SimpleNamespace(id=202)

    monkeypatch.setattr(
        ingestion_worker,
        "ingest_current_traffic_with_new_session",
        fail_traffic,
    )
    monkeypatch.setattr(
        ingestion_worker,
        "ingest_current_weather_with_new_session",
        succeed_weather,
    )

    result = ingestion_worker.run_ingestion_cycle()

    assert result.success is False
    assert result.traffic_status == "failed"
    assert "Simulated traffic API failure" in result.traffic_error
    assert result.weather_status == "success"
    assert result.weather_observation_id == 202
    assert weather_called is True


def test_worker_can_skip_weather_collection(monkeypatch):
    traffic_called = False

    def succeed_traffic():
        nonlocal traffic_called
        traffic_called = True
        return SimpleNamespace(id=101)

    def unexpected_weather_call():
        pytest.fail("Weather ingestion should have been skipped")

    monkeypatch.setattr(
        ingestion_worker,
        "ingest_current_traffic_with_new_session",
        succeed_traffic,
    )
    monkeypatch.setattr(
        ingestion_worker,
        "ingest_current_weather_with_new_session",
        unexpected_weather_call,
    )

    result = ingestion_worker.run_ingestion_cycle(
        collect_traffic=True,
        collect_weather=False,
    )

    assert result.success is True
    assert result.traffic_status == "success"
    assert result.weather_status == "skipped"
    assert traffic_called is True


def test_worker_rejects_nonpositive_interval():
    with pytest.raises(ValueError, match="Traffic interval"):
        ingestion_worker.run_forever(
            traffic_interval_seconds=0,
            weather_interval_seconds=900,
            stop_event=Event(),
        )


def test_worker_runs_traffic_on_a_repeated_schedule(monkeypatch):
    stop_event = Event()
    calls = []

    def fake_ingestion_cycle(
        *,
        collect_traffic=True,
        collect_weather=True,
    ):
        calls.append((collect_traffic, collect_weather))

        # Stop after the second scheduled cycle.
        if len(calls) == 2:
            stop_event.set()

    monkeypatch.setattr(
        ingestion_worker,
        "run_ingestion_cycle",
        fake_ingestion_cycle,
    )

    ingestion_worker.run_forever(
        traffic_interval_seconds=0.05,
        weather_interval_seconds=10,
        stop_event=stop_event,
    )

    assert calls == [
        (True, True),   # Both tasks run at startup.
        (True, False),  # Only traffic is due next.
    ]


def test_worker_stops_without_an_extra_ingestion_cycle(monkeypatch):
    stop_event = Event()
    calls = []

    def fake_ingestion_cycle(
        *,
        collect_traffic=True,
        collect_weather=True,
    ):
        calls.append((collect_traffic, collect_weather))
        stop_event.set()

    monkeypatch.setattr(
        ingestion_worker,
        "run_ingestion_cycle",
        fake_ingestion_cycle,
    )

    ingestion_worker.run_forever(
        traffic_interval_seconds=300,
        weather_interval_seconds=900,
        stop_event=stop_event,
    )

    assert len(calls) == 1
    assert calls[0] == (True, True)
