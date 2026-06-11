-- ============================================================================
-- Migration 001 — ROLLBACK
-- Only run this if the migration must be fully reverted.
-- WARNING: drops new tables entirely.
-- ============================================================================

BEGIN;

-- Drop new tables
DROP TABLE IF EXISTS sde_checkpoints;
DROP TABLE IF EXISTS sde_sessions;
DROP TABLE IF EXISTS system_locks;
DROP TABLE IF EXISTS weekly_draw_state;

-- Remove new columns from existing tables
ALTER TABLE draw_history
    DROP COLUMN IF EXISTS draw_type,
    DROP COLUMN IF EXISTS targeted_early_exit,
    DROP COLUMN IF EXISTS sde_session_id;

ALTER TABLE pools
    DROP COLUMN IF EXISTS draw_completed_this_week,
    DROP COLUMN IF EXISTS pool_draw_type,
    DROP COLUMN IF EXISTS contains_flagged_l4;

ALTER TABLE users
    DROP COLUMN IF EXISTS sde_required,
    DROP COLUMN IF EXISTS sde_flagged_week;

COMMIT;
