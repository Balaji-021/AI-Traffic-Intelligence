# AI Traffic Intelligence

Real-time traffic intelligence platform for congestion prediction, anomaly detection, and weather-aware traffic analysis using machine learning.

## Project Status

🚧 **Currently in development — Phase 01: Project Setup**

This project is being developed phase-by-phase as a production-style Data Science / Machine Learning portfolio project.

## Overview

AI Traffic Intelligence is designed to collect live traffic and weather observations, build historical traffic intelligence, predict future congestion, detect unusual traffic conditions, and present insights through an interactive web dashboard.

The system is designed around:

- Real-time traffic data
- Weather data
- Historical observations
- Machine learning-based congestion prediction
- Anomaly detection
- Prediction explainability
- Interactive maps and dashboards

## Architecture

```text
                ┌─────────────────────┐
                │     React + Vite    │
                │    Tailwind CSS     │
                └──────────┬──────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │       FastAPI       │
                │      Backend        │
                └──────┬───────┬──────┘
                       │       │
                       ▼       ▼
                ┌──────────┐ ┌──────────┐
                │PostgreSQL│ │ML Model  │
                └──────────┘ └──────────┘

External data sources:
- Google Routes Compute Routes Pro
- Open-Meteo
- Google Maps JavaScript API