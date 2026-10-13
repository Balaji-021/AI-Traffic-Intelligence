from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TrafficPrediction(Base):
    __tablename__ = "traffic_predictions"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    route_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    prediction_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    target_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    horizon_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    predicted_duration_seconds: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    predicted_congestion_ratio: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    model_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "horizon_minutes IN (15, 30, 60)",
            name="ck_traffic_predictions_horizon_minutes",
        ),
    )