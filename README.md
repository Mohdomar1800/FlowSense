# FlowSense
# FlowSense

FlowSense is a backend-first productivity intelligence system that helps users track deep work, capture distractions, and convert raw behavior into actionable recommendations.

The project is designed as a production-style API service using FastAPI + PostgreSQL + Redis, with JWT authentication, background scheduling, analytics caching, and deterministic (rule-based) insight generation.

---

## Table of Contents

1. [What FlowSense Solves](#what-flowsense-solves)
2. [Core Product Capabilities](#core-product-capabilities)
3. [System Architecture](#system-architecture)
4. [Technology Stack](#technology-stack)
5. [Project Structure](#project-structure)
6. [Environment Configuration](#environment-configuration)
7. [Local Setup (Step by Step)](#local-setup-step-by-step)
8. [Running the Service](#running-the-service)
9. [Database Schema Overview](#database-schema-overview)
10. [Authentication Model](#authentication-model)
11. [API Reference](#api-reference)
    - [Health Endpoints](#health-endpoints)
    - [Auth Endpoints](#auth-endpoints)
    - [Focus Session Endpoints](#focus-session-endpoints)
    - [Distraction Endpoints](#distraction-endpoints)
    - [Analytics Endpoint](#analytics-endpoint)
    - [Insights Endpoint](#insights-endpoint)
    - [Reports Endpoint](#reports-endpoint)
12. [Caching Strategy](#caching-strategy)
13. [Scheduler and Automated Reports](#scheduler-and-automated-reports)
14. [Demo Data Seeding](#demo-data-seeding)
15. [Error Handling and API Behavior](#error-handling-and-api-behavior)
16. [Known Runtime Notes](#known-runtime-notes)
17. [How to Extend FlowSense](#how-to-extend-flowsense)

---

## What FlowSense Solves

Most productivity tools stop at timers and checklists. FlowSense focuses on **behavioral feedback loops**:

- Track where focused time is actually spent.
- Capture distraction events (manual and inferred).
- Aggregate data into measurable patterns.
- Generate practical recommendations users can act on.
- Produce periodic summaries without manual effort.

In short: **FlowSense is not only a tracker, it is a decision-support backend for deep work habits.**

---

## Core Product Capabilities

- **User authentication with JWT**
- **Focus session lifecycle** (start / stop / pause with split behavior)
- **Distraction event logging** (manual and inferred)
- **Productivity analytics** (period-based aggregate metrics)
- **Rule-based insights** (best focus window, trend cues)
- **Scheduled reports** (daily + weekly)
- **Redis-backed analytics caching** with invalidation on writes
- **Report retrieval with pagination + filtering**

---

## System Architecture

FlowSense follows a layered backend architecture:

1. **API Layer (`app/api`)**
   - FastAPI routers define request/response contracts.
   - Input is validated with Pydantic schemas.
   - Protected routes use Bearer token auth dependency.

2. **Service Layer (`app/services`)**
   - Business logic is centralized here.
   - Session/distraction mutations live here.
   - Analytics/report generation and cache behavior are implemented here.

3. **Persistence Layer (`app/models`, `app/db`, `sql/schema.sql`)**
   - SQLAlchemy models map to PostgreSQL tables.
   - SQL bootstrap file initializes schema on container startup.

4. **Background Processing**
   - APScheduler runs daily and weekly report jobs.

5. **Caching Layer**
   - Redis stores analytics responses with TTL.

---

## Technology Stack

- **Framework:** FastAPI
- **Database:** PostgreSQL 16
- **ORM:** SQLAlchemy 2
- **Cache:** Redis 7
- **Auth:** JWT (PyJWT) + bcrypt hashing (passlib)
- **Scheduler:** APScheduler
- **Containerization:** Docker + Docker Compose

---

## Project Structure

```text
app/
  api/            # HTTP routes
  core/           # settings/config
  db/             # SQLAlchemy base/session dependencies
  models/         # DB models
  schemas/        # request/response contracts
  services/       # business logic
  main.py         # FastAPI app entrypoint
sql/
  schema.sql      # bootstrap schema executed by postgres container
scripts/
  seed_demo_data.py
```

---

## Environment Configuration

Create `.env` from `.env.example` and update as needed.

### Variables

- `APP_NAME`, `APP_ENV`, `APP_DEBUG`
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`
- `REDIS_HOST`, `REDIS_PORT`
- `ANALYTICS_CACHE_TTL_SECONDS`
- `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_EXPIRE_MINUTES`

---

## Local Setup (Step by Step)

### 1) Clone and enter repo

```bash
git clone <your-repo-url>
cd FlowSense
```

### 2) Create environment file

```bash
cp .env.example .env
```

### 3) Start all services

```bash
docker compose up --build
```

This brings up:

- API on `http://localhost:8000`
- PostgreSQL on `localhost:5432`
- Redis on `localhost:6379`

### 4) Open interactive docs

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### 5) (Optional) Seed demo data

```bash
python scripts/seed_demo_data.py
```

---

## Running the Service

The default container command starts uvicorn with:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

For local non-container usage, ensure dependencies are installed first:

```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

---

## Database Schema Overview

### Core tables

- `users`
- `session_tags`
- `focus_sessions`
- `distraction_events`
- `report_logs`

### Important constraints and indexes

- Unique user emails
- Unique `(user_id, tag_name)` in `session_tags`
- Session integrity check: `end_time >= start_time`
- Time-window indexes for session/distraction analytics queries
- User + created_at index for report listing

---

## Authentication Model

FlowSense uses JWT bearer tokens.

### Auth flow

1. Register user via `/auth/register`
2. Login via `/auth/login` to receive `access_token`
3. Pass token in header for protected endpoints:

```http
Authorization: Bearer <token>
```

### Protected routes include

- `/auth/me`
- `/sessions/*`
- `/distractions/*`
- `/analytics/*`
- `/insights/*`
- `/reports`

---

## API Reference

Base URL (local): `http://localhost:8000`

---

### Health Endpoints

#### `GET /health`
Simple liveness check.

**Response (200):**

```json
{ "status": "ok" }
```

#### `GET /ready`
Readiness + environment metadata.

**Response (200):** includes env, DB URL, Redis URL.

---

### Auth Endpoints

#### `POST /auth/register`
Create new user.

**Body:**

```json
{
  "email": "user@example.com",
  "password": "strong-password",
  "timezone": "UTC"
}
```

**Response (201):** user profile.

#### `POST /auth/login`
Authenticate user and issue JWT.

**Body:**

```json
{
  "email": "user@example.com",
  "password": "strong-password"
}
```

**Response (200):**

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer"
}
```

#### `GET /auth/me`
Get current authenticated user.

---

### Focus Session Endpoints

#### `POST /sessions/start`
Start new focus session.

**Body:**

```json
{
  "tag_id": 1,
  "start_time": "2026-04-02T10:00:00Z"
}
```

- `start_time` is optional (defaults to current UTC time).
- Rejects if user already has an active session.

#### `POST /sessions/stop`
Stop currently active session and compute duration.

**Body:**

```json
{
  "end_time": "2026-04-02T11:15:00Z"
}
```

- `end_time` optional (defaults to current UTC).
- Validates `end_time >= start_time`.

#### `POST /sessions/pause`
Pause logic with split behavior.

**Body:**

```json
{
  "paused_at": "2026-04-02T10:30:00Z",
  "resumed_at": "2026-04-02T10:40:00Z"
}
```

Behavior:

- If pause duration <= threshold: no split.
- If pause duration > threshold: current session closed and new session created from `resumed_at`.

#### `GET /sessions`
List sessions with aggregate total focus seconds.

**Query params:**

- `period=day|week|month|custom`
- `reference_date=YYYY-MM-DD` (for day/week/month)
- `start_date`, `end_date` (for custom)

---

### Distraction Endpoints

#### `POST /distractions/manual`
Log manually recorded distraction.

**Body:**

```json
{
  "session_id": 10,
  "reason": "Checked phone",
  "timestamp": "2026-04-02T10:20:00Z"
}
```

#### `POST /distractions/inferred`
Log inferred distraction (e.g., inactivity).

**Body:**

```json
{
  "session_id": 10,
  "inactive_minutes": 12,
  "reason": "Inferred due to inactivity",
  "timestamp": "2026-04-02T10:35:00Z"
}
```

#### `GET /distractions`
List distractions with pagination.

**Query params:**

- `day=YYYY-MM-DD` (optional filter)
- `limit` (1..200)
- `offset` (>=0)

#### `GET /distractions/summary/daily`
Daily totals split by manual vs inferred.

---

### Analytics Endpoint

#### `GET /analytics/productivity`
Aggregated productivity metrics.

**Query params:**

- `period=day|week|month`
- `reference_date=YYYY-MM-DD` (optional)

**Returns:**

- overview (focus seconds, distractions, avg session, count)
- focus grouped by tag
- distractions grouped by hour

---

### Insights Endpoint

#### `GET /insights/recommendations`
Rule-based personalized recommendations from recent behavior.

Examples:

- Best focus window
- Evening distraction pattern
- Session length optimization
- Low-data fallback message

---

### Reports Endpoint

#### `GET /reports`
Fetch historical generated reports.

**Query params:**

- `report_type=daily|weekly` (optional)
- `limit` (1..100)
- `offset` (>=0)
- `start_date` (optional)
- `end_date` (optional)

Response includes:

- `items`
- `total_count`

---

## Caching Strategy

FlowSense caches analytics response payloads in Redis.

### Cache key pattern

`analytics:productivity:user:{user_id}:period:{period}:ref:{reference}`

### TTL

Configured by `ANALYTICS_CACHE_TTL_SECONDS`.

### Invalidation

Analytics cache for a user is invalidated when:

- sessions are started/stopped/split
- distractions are logged

This keeps reads fast while preserving data freshness.

---

## Scheduler and Automated Reports

APScheduler is started during app lifespan startup and stopped gracefully on shutdown.

### Jobs

- **Daily reports:** 21:00 UTC
- **Weekly reports:** Sundays at 21:00 UTC

Each job computes aggregate metrics and stores textual summaries in `report_logs`.

---

## Demo Data Seeding

Use the seed script to quickly prepare demo-ready data:

```bash
python scripts/seed_demo_data.py
```

Creates:

- demo user: `demo@flowsense.local`
- password: `demo-password`
- sample tags/sessions/distractions

If the demo user already exists, script exits safely.

---

## Error Handling and API Behavior

FlowSense defines centralized exception handlers:

- HTTP exceptions are normalized to:

```json
{
  "error": {
    "type": "http_error",
    "message": "..."
  }
}
```

- Validation errors are normalized to:

```json
{
  "error": {
    "type": "validation_error",
    "message": "Request validation failed",
    "details": [...]
  }
}
```

---

## Known Runtime Notes

- You need PostgreSQL and Redis available (or run via Docker Compose).
- Scheduler jobs run in UTC by default.
- API date filtering currently uses UTC boundaries.
- For production, use a strong JWT secret and secure deployment settings.

---

## How to Extend FlowSense

Potential next upgrades:

- Add refresh tokens and token revocation
- Add per-user configurable distraction thresholds and report time windows
- Add richer report formats (JSON dashboards)
- Add full integration test suite using ephemeral Postgres + Redis
- Add observability (structured logs, metrics, traces)

---

FlowSense is now structured as a complete backend product foundation, ready for demonstration, extension, and deeper quality hardening.
