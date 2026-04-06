CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    timezone VARCHAR(64) NOT NULL DEFAULT 'UTC',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS session_tags (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_tag_name UNIQUE (user_id, name)
);

CREATE TABLE IF NOT EXISTS focus_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tag_id INTEGER REFERENCES session_tags(id) ON DELETE SET NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    duration_seconds INTEGER NOT NULL DEFAULT 0,
    pause_threshold_seconds INTEGER NOT NULL DEFAULT 300,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_session_end_after_start CHECK (end_time IS NULL OR end_time >= start_time)
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'distractiontype') THEN
        CREATE TYPE distractiontype AS ENUM ('MANUAL', 'INFERRED');
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS distraction_events (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id INTEGER REFERENCES focus_sessions(id) ON DELETE SET NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    event_type distractiontype NOT NULL,
    reason VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_users_email ON users (email);
CREATE INDEX IF NOT EXISTS ix_session_tags_user_id ON session_tags (user_id);
CREATE INDEX IF NOT EXISTS ix_focus_sessions_user_id ON focus_sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_focus_sessions_start_time ON focus_sessions (start_time);
CREATE INDEX IF NOT EXISTS ix_focus_sessions_user_start_time ON focus_sessions (user_id, start_time);
CREATE INDEX IF NOT EXISTS ix_distraction_events_user_id ON distraction_events (user_id);
CREATE INDEX IF NOT EXISTS ix_distraction_events_timestamp ON distraction_events (timestamp);
CREATE INDEX IF NOT EXISTS ix_distraction_events_user_timestamp ON distraction_events (user_id, timestamp);

CREATE TABLE IF NOT EXISTS report_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    report_type VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_report_logs_user_created ON report_logs (user_id, created_at);
