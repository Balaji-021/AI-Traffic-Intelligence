from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TrafficAnomaly(Base):
    __tablename__ = "traffic_anomalies"

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

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    anomaly_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    anomaly_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    observation_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("traffic_observations.id"),
        nullable=True,
        index=True,
    )

    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
    )

    __table_args__ = (
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_traffic_anomalies_severity",
        ),
        CheckConstraint(
            "status IN ('active', 'resolved')",
            name="ck_traffic_anomalies_status",
        ),
    )