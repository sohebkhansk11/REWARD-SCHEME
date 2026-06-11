-- ============================================================================
-- Migration 001 — SDE Architecture Foundation
-- Apply to: existing production / staging databases
-- Fresh databases: skip — SQLAlchemy create_all() handles table creation
--
-- APPLY ORDER:
--   1. Run this file in a single transaction.
--   2. Verify row counts in the check queries at the bottom.
--   3. Deploy new application code.
--
-- ROLLBACK: see 001_rollback.sql
-- ============================================================================

BEGIN;

-- ── 1. users — SDE flag columns ──────────────────────────────────────────────
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS sde_required     BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS sde_flagged_week VARCHAR(10) NULL;

-- Partial index: only rows where sde_required is TRUE (small set — fast)
CREATE INDEX IF NOT EXISTS ix_users_sde_required
    ON users(sde_required)
    WHERE sde_required = TRUE;

-- ── 2. pools — draw-cycle tracking columns ───────────────────────────────────
ALTER TABLE pools
    ADD COLUMN IF NOT EXISTS draw_completed_this_week BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS pool_draw_type           VARCHAR(20) NULL,
    ADD COLUMN IF NOT EXISTS contains_flagged_l4      BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS ix_pools_flagged_l4
    ON pools(contains_flagged_l4)
    WHERE contains_flagged_l4 = TRUE;

CREATE INDEX IF NOT EXISTS ix_pools_draw_type
    ON pools(pool_draw_type);

-- ── 3. draw_history — classification columns ─────────────────────────────────
ALTER TABLE draw_history
    ADD COLUMN IF NOT EXISTS draw_type           VARCHAR(20) NULL,
    ADD COLUMN IF NOT EXISTS targeted_early_exit BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS sde_session_id      INTEGER NULL;

-- ── 4. weekly_draw_state — new table ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS weekly_draw_state (
    id                       SERIAL PRIMARY KEY,
    week_id                  VARCHAR(10)   UNIQUE NOT NULL,
    draw_time_utc            TIMESTAMPTZ   NULL,
    preparation_started_at   TIMESTAMPTZ   NULL,
    preparation_completed_at TIMESTAMPTZ   NULL,
    preparation_valid        BOOLEAN       NOT NULL DEFAULT FALSE,
    countdown_active         BOOLEAN       NOT NULL DEFAULT FALSE,
    lpi_snapshot             NUMERIC(5,2)  NULL,
    total_l4_count           INTEGER       NOT NULL DEFAULT 0,
    total_l3_count           INTEGER       NOT NULL DEFAULT 0,
    total_active_count       INTEGER       NOT NULL DEFAULT 0,
    sde_sessions_planned     INTEGER       NOT NULL DEFAULT 0,
    sde_sessions_completed   INTEGER       NOT NULL DEFAULT 0,
    sde_overflow_count       INTEGER       NOT NULL DEFAULT 0,
    admin_override_required  BOOLEAN       NOT NULL DEFAULT FALSE,
    admin_override_deadline  TIMESTAMPTZ   NULL,
    admin_override_choice    VARCHAR(10)   NULL,
    admin_override_applied_at TIMESTAMPTZ  NULL,
    float_projection_inr     INTEGER       NOT NULL DEFAULT 0,
    draw_executed            BOOLEAN       NOT NULL DEFAULT FALSE,
    draw_executed_at         TIMESTAMPTZ   NULL,
    idempotency_key          VARCHAR(64)   UNIQUE NULL,
    consecutive_type_b_weeks INTEGER       NOT NULL DEFAULT 0,
    created_at               TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_weekly_draw_state_week_id
    ON weekly_draw_state(week_id);

-- ── 5. sde_sessions — new table ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sde_sessions (
    id                 SERIAL PRIMARY KEY,
    week_id            VARCHAR(10)  NOT NULL,
    session_number     INTEGER      NOT NULL,
    status             VARCHAR(20)  NOT NULL DEFAULT 'planned',
    l4_count_planned   INTEGER      NOT NULL DEFAULT 0,
    l4_count_completed INTEGER      NOT NULL DEFAULT 0,
    total_payout_inr   NUMERIC(12,2) NOT NULL DEFAULT 0,
    started_at         TIMESTAMPTZ  NULL,
    completed_at       TIMESTAMPTZ  NULL,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_sde_session_week_number UNIQUE (week_id, session_number)
);

CREATE INDEX IF NOT EXISTS ix_sde_sessions_week_id
    ON sde_sessions(week_id);

-- ── 6. sde_checkpoints — new table ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sde_checkpoints (
    id                          SERIAL PRIMARY KEY,
    session_id                  INTEGER      NOT NULL,
    sub_draw_number             INTEGER      NOT NULL,
    pool_id                     INTEGER      NOT NULL,
    upper_winner_user_id        INTEGER      NOT NULL,
    upper_winner_level          INTEGER      NOT NULL,
    upper_payout_inr            NUMERIC(12,2) NOT NULL,
    lower_winner_user_id        INTEGER      NOT NULL,
    lower_winner_level          INTEGER      NOT NULL,
    lower_payout_inr            NUMERIC(12,2) NOT NULL,
    lower_winner_tier_override  BOOLEAN      NOT NULL DEFAULT FALSE,
    rng_seed_hash               VARCHAR(64)  NOT NULL,
    completed_at                TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_sde_checkpoint_session_subdraw UNIQUE (session_id, sub_draw_number)
);

CREATE INDEX IF NOT EXISTS ix_sde_checkpoints_session_id
    ON sde_checkpoints(session_id);

-- ── 7. system_locks — new table ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS system_locks (
    lock_name   VARCHAR(50) PRIMARY KEY,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL,
    held_by     VARCHAR(100) NULL
);

-- ── 8. Verify ────────────────────────────────────────────────────────────────
-- Run these SELECTs manually after migration to confirm:
--   SELECT column_name FROM information_schema.columns WHERE table_name = 'users'       AND column_name IN ('sde_required', 'sde_flagged_week');
--   SELECT column_name FROM information_schema.columns WHERE table_name = 'pools'       AND column_name IN ('draw_completed_this_week', 'pool_draw_type', 'contains_flagged_l4');
--   SELECT column_name FROM information_schema.columns WHERE table_name = 'draw_history' AND column_name IN ('draw_type', 'targeted_early_exit', 'sde_session_id');
--   SELECT table_name  FROM information_schema.tables  WHERE table_name IN ('weekly_draw_state', 'sde_sessions', 'sde_checkpoints', 'system_locks');

COMMIT;
