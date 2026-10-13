from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.anomaly import TrafficAnomaly
from app.models.prediction import TrafficPrediction
from app.models.traffic import TrafficObservation
from app.models.weather import WeatherObservation


def test_database_connection():
    db = SessionLocal()

    try:
        result = db.execute(text("SELECT 1"))
        assert result.scalar() == 1
    finally:
        db.close()


def test_create_traffic_observation():
    db = SessionLocal()
    observation = None

    try:
        observation = TrafficObservation(
            route_id="test_route_001",
            observed_at=datetime.now(timezone.utc),
            distance_meters=5000.0,
            duration_seconds=600.0,
            static_duration_seconds=450.0,
            congestion_ratio=600.0 / 450.0,
        )

        db.add(observation)
        db.commit()
        db.refresh(observation)

        assert observation.id is not None
        assert observation.route_id == "test_route_001"
        assert observation.congestion_ratio > 1.0

    finally:
        if observation is not None and observation.id is not None:
            db.delete(observation)
            db.commit()

        db.close()


def test_create_weather_observation():
    db = SessionLocal()
    observation = None

    try:
        observation = WeatherObservation(
            observed_at=datetime.now(timezone.utc),
            latitude=17.4065,
            longitude=78.4772,
            temperature=28.5,
            precipitation=0.0,
            humidity=65.0,
            wind_speed=12.0,
            cloud_cover=20.0,
        )

        db.add(observation)
        db.commit()
        db.refresh(observation)

        assert observation.id is not None
        assert observation.latitude == 17.4065
        assert observation.longitude == 78.4772

    finally:
        if observation is not None and observation.id is not None:
            db.delete(observation)
            db.commit()

        db.close()


def test_create_traffic_prediction():
    db = SessionLocal()
    prediction = None

    try:
        now = datetime.now(timezone.utc)

        prediction = TrafficPrediction(
            route_id="test_route_001",
            prediction_created_at=now,
            target_timestamp=now,
            horizon_minutes=15,
            predicted_duration_seconds=700.0,
            predicted_congestion_ratio=1.45,
            model_version="test_v1",
        )

        db.add(prediction)
        db.commit()
        db.refresh(prediction)

        assert prediction.id is not None
        assert prediction.horizon_minutes == 15
        assert prediction.model_version == "test_v1"

    finally:
        if prediction is not None and prediction.id is not None:
            db.delete(prediction)
            db.commit()

        db.close()


def test_create_traffic_anomaly():
    db = SessionLocal()

    observation = None
    anomaly = None

    try:
        observation = TrafficObservation(
            route_id="test_route_002",
            observed_at=datetime.now(timezone.utc),
            distance_meters=4000.0,
            duration_seconds=800.0,
            static_duration_seconds=400.0,
            congestion_ratio=2.0,
        )

        db.add(observation)
        db.commit()
        db.refresh(observation)

        anomaly = TrafficAnomaly(
            route_id="test_route_002",
            detected_at=datetime.now(timezone.utc),
            anomaly_type="congestion_spike",
            anomaly_score=0.95,
            severity="high",
            observation_id=observation.id,
            description="Test congestion anomaly",
            status="active",
        )

        db.add(anomaly)
        db.commit()
        db.refresh(anomaly)

        assert anomaly.id is not None
        assert anomaly.observation_id == observation.id
        assert anomaly.severity == "high"
        assert anomaly.status == "active"

    finally:
        if anomaly is not None and anomaly.id is not None:
            db.delete(anomaly)
            db.commit()

        if observation is not None and observation.id is not None:
            db.delete(observation)
            db.commit()

        db.close()


def test_prediction_rejects_invalid_horizon():
    db = SessionLocal()

    prediction = TrafficPrediction(
        route_id="test_route_invalid",
        prediction_created_at=datetime.now(timezone.utc),
        target_timestamp=datetime.now(timezone.utc),
        horizon_minutes=37,
        predicted_duration_seconds=700.0,
        predicted_congestion_ratio=1.4,
        model_version="test_v1",
    )

    try:
        db.add(prediction)

        with pytest.raises(IntegrityError):
            db.commit()

        db.rollback()

    finally:
        db.close()


def test_anomaly_rejects_invalid_severity():
    db = SessionLocal()

    anomaly = TrafficAnomaly(
        route_id="test_route_invalid",
        detected_at=datetime.now(timezone.utc),
        anomaly_type="test",
        anomaly_score=0.9,
        severity="banana",
        description="Invalid severity test",
        status="active",
    )

    try:
        db.add(anomaly)

        with pytest.raises(IntegrityError):
            db.commit()

        db.rollback()

    finally:
        db.close()


def test_anomaly_rejects_invalid_status():
    db = SessionLocal()

    anomaly = TrafficAnomaly(
        route_id="test_route_invalid",
        detected_at=datetime.now(timezone.utc),
        anomaly_type="test",
        anomaly_score=0.9,
        severity="high",
        description="Invalid status test",
        status="banana",
    )

    try:
        db.add(anomaly)

        with pytest.raises(IntegrityError):
            db.commit()

        db.rollback()

    finally:
        db.close()


def test_anomaly_rejects_invalid_observation_id():
    db = SessionLocal()

    anomaly = TrafficAnomaly(
        route_id="test_route_invalid",
        detected_at=datetime.now(timezone.utc),
        anomaly_type="test",
        anomaly_score=0.9,
        severity="high",
        observation_id=999999999,
        description="Invalid foreign key test",
        status="active",
    )

    try:
        db.add(anomaly)

        with pytest.raises(IntegrityError):
            db.commit()

        db.rollback()

    finally:
        db.close()