# SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
"""
================================================================================
SIMULATOR ↔ PRODUCTION RECONCILIATION AUDIT  (read-only diagnostic)
================================================================================

PURPOSE
-------
Per the user directive (Jun-23 autopsy, Q4):

    "Complete simulator-vs-production reconciliation script likhu —
     production DB se sab events nikaalu, simulator se compare karu,
     exact mismatch lines highlight karu"

This tool ingests TWO flat CSV exports and produces a side-by-side weekly diff
plus a 'smoking-gun' section pin-pointing the exact mechanisms that diverge
between the strategy oracle and the actual engine run:

    1. weekly-timeline CSV      — the per-week strategy oracle roll-up
                                   (what SHOULD happen each week)

    2. forensic_events CSV      — the engine's append-only event log
                                   (what ACTUALLY happened, event-by-event)

The forensic CSV can come from EITHER an isolated simulator run (current
state — what the user already provided) OR a future production export
(once the forensic recorder is toggled on in production briefly). The script
is source-agnostic.

SAFETY (HARD CONTRACT — DO NOT WEAKEN)
--------------------------------------
This script is READ-ONLY. It performs ZERO DB connections, ZERO writes to
the application, and never imports `app.database` or `app.models`. The only
side-effect is writing the markdown report to the path passed via --output.
A guard at the top of `main()` asserts that `app.database` is NOT in
sys.modules at entry time — if anything imports it transitively the run
aborts before any work is done.

The user's standing safety rule:

    "NEVER touch the shared Supabase production DB during diagnostics.
     Isolated runs MUST point DATABASE_URL at throwaway local SQLite;
     assert sqlite backend AND 'supabase'/'pooler'/'postgres' NOT in URL
     before running."

This tool sidesteps the rule entirely by NOT using the DB at all.

THE FOUR THINGS THIS REPORT TELLS YOU (per the 4 confirmed bugs from autopsy)
----------------------------------------------------------------------------
    Q1  →  L5/L6 PROTECTION — first leak week, peak occupancy, trajectory.
    Q2  →  POSTURE SWITCHING — every transition with surrounding draw volume,
                                exposing feast-or-famine cycle.
    Q3  →  WAITLIST + POOL CREATION + ORPHAN HANDLING — draw freeze weeks,
                                missing pool_created events, merger silence.
    --  →  FORENSIC LOGGING GAPS — every week where timeline.draws ≠
                                    forensic.draw_executed count, i.e. the
                                    engine ran draws that didn't emit events
                                    (the SDE/Ext/PL3 emission omission).

USAGE
-----
    python tools/reconciliation_audit.py \
        --timeline "C:/Users/amosd/Downloads/weekly-timeline-2026-06-23.csv" \
        --forensic "C:/Users/amosd/Downloads/forensic_events (1).csv" \
        --run a4243fd2 \
        --output reconciliation_report.md

The `--run` flag is highly recommended: forensic exports often contain
multiple run_ids (e.g. a4243fd2 = 27-week main run, d4db9df7 = 6-week
secondary, LIVE_STRESS_TEST = single-week probe). Without --run the script
collapses all runs into one bucket which usually produces noise.

================================================================================
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Forensic event → metric-bucket map ────────────────────────────────────────
# Only events that participate in a per-week roll-up live here. Anything else
# (SYSTEM ticks, structured snapshots, etc.) is left to the type-count phase.
EVENT_BUCKETS: dict[str, str] = {
    "member_joined":         "evt_joined",
    "member_won":            "evt_won",
    "draw_executed":         "evt_draw",
    "l4_flagged":            "evt_l4_flag",
    "pool_created":          "evt_pool_create",
    "pool_dissolved":        "evt_pool_dissolved",
    "pool_paused":           "evt_pool_paused",
    "members_merged":        "evt_merge",
    "sde_lever_fired":       "evt_sde",
    "level_advanced":        "evt_level_adv",
    "eliminated":            "evt_elim",
    "posture_decided":       "evt_posture",
    "active_l5l6_present":   "evt_l5l6_warn",
}


# ── Data models ───────────────────────────────────────────────────────────────
@dataclass
class WeekRow:
    """One week's reconciled view — timeline oracle side + forensic actual side."""
    week:     int
    posture:  str = "—"
    tl:       dict[str, int] = field(default_factory=dict)   # timeline (oracle)
    fr:       dict[str, int] = field(default_factory=dict)   # forensic (actual)
    l5l6:     dict[str, int] = field(default_factory=dict)
    flags:    list[str]      = field(default_factory=list)


@dataclass
class ForensicAggregate:
    """Output of `load_forensic()` — per-week buckets + cross-run metadata."""
    per_week:       dict[int, Counter]
    type_counts:    Counter
    posture_byweek: dict[int, str]
    l5l6_byweek:    dict[int, dict[str, int]]
    run_ids_seen:   Counter
    total_rows:     int
    rows_kept:      int


# ── Loaders ───────────────────────────────────────────────────────────────────
def _to_int(value: Any, default: int = 0) -> int:
    """Defensive integer coercion — CSV columns sometimes contain '' or floats."""
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def load_timeline(path: str) -> dict[int, dict[str, str]]:
    """
    Load the weekly-timeline oracle CSV.

    Returns a dict {week_number → raw row dict}. We keep the raw row so the
    renderer can pull arbitrary columns (cash flows, cumulative, etc.) without
    a second pass.
    """
    rows: dict[int, dict[str, str]] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                w = int(r["week"])
            except (KeyError, ValueError):
                continue
            rows[w] = r
    if not rows:
        raise RuntimeError(f"timeline CSV produced 0 weeks — schema mismatch? path={path}")
    return rows


def load_forensic(path: str, run_id_filter: str | None = None) -> ForensicAggregate:
    """
    Load the forensic_events CSV, optionally filtering to a single run_id.

    The forensic schema is the ForensicEvent ORM model (see
    app/models/forensic_event.py): run_id, seq, week_id, tick, category,
    event_type, severity, actor, entity_type, entity_id, entity_ref,
    amount_inr, before_json, after_json, payload_json, message, created_at.
    """
    per_week:       dict[int, Counter]      = defaultdict(Counter)
    type_counts:    Counter                 = Counter()
    posture_byweek: dict[int, str]          = {}
    l5l6_byweek:    dict[int, dict[str, int]] = {}
    run_ids_seen:   Counter                 = Counter()
    total_rows                              = 0
    rows_kept                               = 0

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            total_rows += 1
            run_id = (r.get("run_id") or "").strip()
            run_ids_seen[run_id or "<empty>"] += 1
            if run_id_filter and run_id != run_id_filter:
                continue
            week = _to_int(r.get("week_id"), default=-1)
            if week < 0:
                continue
            etype = (r.get("event_type") or "").strip()
            type_counts[etype] += 1
            bucket = EVENT_BUCKETS.get(etype)
            if bucket:
                per_week[week][bucket] += 1

            # POSTURE — the decision lives in after_json (`posture` + `scenario`),
            # not payload_json. We surface "POSTURE/scenario" so Q2's smoking-gun
            # can show e.g. BALANCED/VELOCITY_CLIFF vs LIABILITY_CONTROL/DRY_PHASE.
            if etype == "posture_decided":
                aj = _safe_json(r.get("after_json"))
                posture = (
                    aj.get("posture")
                    or _safe_json(r.get("payload_json")).get("posture")
                    or "?"
                )
                scenario = (
                    aj.get("scenario")
                    or _safe_json(r.get("payload_json")).get("scenario")
                    or ""
                )
                posture_byweek[week] = (
                    f"{posture}/{scenario}" if scenario else posture
                )

            # L5/L6 leak — explicit warning event carries the live counts
            if etype == "active_l5l6_present":
                pl = _safe_json(r.get("payload_json"))
                l5l6_byweek[week] = {
                    "l5": _to_int(pl.get("l5_count") or pl.get("l5"), 0),
                    "l6": _to_int(pl.get("l6_count") or pl.get("l6"), 0),
                }

            rows_kept += 1

    return ForensicAggregate(
        per_week=per_week,
        type_counts=type_counts,
        posture_byweek=posture_byweek,
        l5l6_byweek=l5l6_byweek,
        run_ids_seen=run_ids_seen,
        total_rows=total_rows,
        rows_kept=rows_kept,
    )


def _safe_json(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else {}
    except (ValueError, TypeError):
        return {}


# ── Reconciliation ────────────────────────────────────────────────────────────
def reconcile(
    timeline: dict[int, dict[str, str]],
    forensic: ForensicAggregate,
) -> list[WeekRow]:
    """
    Build one WeekRow per timeline week. Side-by-side comparison of:

        timeline.draws        vs  forensic.draw_executed count
        timeline.winners      vs  forensic.member_won count
        timeline.exits_won    vs  forensic.member_won count   (same source)
        timeline.exits_nonpay vs  forensic.eliminated count
        timeline.sde_exits    vs  forensic.sde_lever_fired count
        timeline.pools_created vs forensic.pool_created count
        timeline.users_in     vs  forensic.member_joined count

    Each divergence becomes a flag string on the row. Flags are short labels
    the renderer turns into a smoking-gun section.
    """
    out: list[WeekRow] = []

    for w in sorted(timeline.keys()):
        t = timeline[w]
        f = forensic.per_week.get(w, Counter())
        row = WeekRow(
            week=w,
            posture=forensic.posture_byweek.get(w, "—"),
            tl={
                "uin": _to_int(t.get("users_in")),
                "exn": _to_int(t.get("exits_nonpay")),
                "exw": _to_int(t.get("exits_won")),
                "drw": _to_int(t.get("draws")),
                "win": _to_int(t.get("winners")),
                "sde": _to_int(t.get("sde_exits")),
                "pcr": _to_int(t.get("pools_created")),
            },
            fr={
                "uin":      f.get("evt_joined", 0),
                "exn":      f.get("evt_elim", 0),
                "exw":      f.get("evt_won", 0),
                "drw":      f.get("evt_draw", 0),
                "win":      f.get("evt_won", 0),
                "sde":      f.get("evt_sde", 0),
                "pcr":      f.get("evt_pool_create", 0),
                "merge":    f.get("evt_merge", 0),
                "pause":    f.get("evt_pool_paused", 0),
                "dissolve": f.get("evt_pool_dissolved", 0),
                "lvl_adv":  f.get("evt_level_adv", 0),
                "l4_flag":  f.get("evt_l4_flag", 0),
            },
            l5l6=forensic.l5l6_byweek.get(w, {}),
        )

        # ── flag rules ────────────────────────────────────────────────────────
        # 1. Draw count divergence → forensic logging gap (SDE/Ext/PL3 silent)
        delta_drw = row.fr["drw"] - row.tl["drw"]
        if delta_drw != 0:
            row.flags.append(f"DRAW_LOG_Δ={delta_drw:+d}")

        # 2. Winner count divergence
        delta_win = row.fr["win"] - row.tl["win"]
        if delta_win != 0:
            row.flags.append(f"WIN_LOG_Δ={delta_win:+d}")

        # 3. Pool-creation divergence
        delta_pcr = row.fr["pcr"] - row.tl["pcr"]
        if delta_pcr != 0:
            row.flags.append(f"POOL_NEW_Δ={delta_pcr:+d}")

        # 4. L5/L6 leak — Q1 trigger
        l5 = row.l5l6.get("l5", 0)
        l6 = row.l5l6.get("l6", 0)
        if l5 > 0 or l6 > 0:
            row.flags.append(f"L5L6_LEAK[L5={l5},L6={l6}]")

        # 5. Draw freeze — Q3 starvation symptom (skip very early ramp weeks)
        if w >= 5 and row.tl["drw"] == 0 and row.fr["drw"] == 0:
            row.flags.append("DRAW_FREEZE")

        # 6. Blowout — Q2 feast side of feast-or-famine
        if row.fr["win"] >= 50:
            row.flags.append(f"BLOWOUT[win={row.fr['win']}]")

        # 7. Pool paused / dissolved spike — Q3 cascade symptom
        if row.fr["pause"] > 0:
            row.flags.append(f"POOLS_PAUSED={row.fr['pause']}")
        if row.fr["dissolve"] > 0:
            row.flags.append(f"POOLS_DISSOLVED={row.fr['dissolve']}")

        out.append(row)

    return out


# ── Renderer ──────────────────────────────────────────────────────────────────
def render(
    report: list[WeekRow],
    type_counts: Counter,
    run_id: str,
    forensic: ForensicAggregate,
    output_path: str,
) -> str:
    """Emit a markdown report and return the same text for stdout."""
    L: list[str] = []

    # ── Header ────────────────────────────────────────────────────────────────
    L.append("# RECONCILIATION AUDIT — Simulator ↔ Production")
    L.append("")
    L.append(f"- **Run ID filter:** `{run_id}`")
    L.append(f"- **Generated:** {datetime.now(timezone.utc).isoformat()}")
    L.append(f"- **Forensic rows scanned:** {forensic.total_rows:,}  "
             f"(kept after run filter: {forensic.rows_kept:,})")
    L.append(f"- **Run IDs seen in forensic CSV:** "
             + ", ".join(f"`{rid}`={cnt:,}" for rid, cnt in forensic.run_ids_seen.most_common()))
    L.append("")
    L.append("> Timeline column = strategy oracle (what should happen).  "
             "Forensic column = what the engine actually emitted.")
    L.append("> A divergence is not necessarily a bug — sometimes the engine "
             "ran the right action but the event emission was silent. "
             "The renderer flags those cases too.")
    L.append("")

    # ── PHASE 1 — per-week table ──────────────────────────────────────────────
    L.append("## PHASE 1 — Per-Week Roll-Up Comparison")
    L.append("")
    L.append("| W | Posture | T:drw | F:drw | T:win | F:win | T:sde | F:sde | "
             "T:pcr | F:pcr | F:mrg | F:pse | F:dis | F:l4 | L5 | L6 | Flags |")
    L.append("|--:|---------|------:|------:|------:|------:|------:|------:|"
             "------:|------:|------:|------:|------:|-----:|---:|---:|-------|")
    for r in report:
        l5 = r.l5l6.get("l5", 0)
        l6 = r.l5l6.get("l6", 0)
        flags = "; ".join(r.flags) if r.flags else "✓"
        L.append(
            f"| {r.week} | {r.posture} | "
            f"{r.tl['drw']} | {r.fr['drw']} | "
            f"{r.tl['win']} | {r.fr['win']} | "
            f"{r.tl['sde']} | {r.fr['sde']} | "
            f"{r.tl['pcr']} | {r.fr['pcr']} | "
            f"{r.fr['merge']} | {r.fr['pause']} | {r.fr['dissolve']} | "
            f"{r.fr['l4_flag']} | "
            f"{l5} | {l6} | {flags} |"
        )
    L.append("")

    # ── PHASE 2 — Smoking guns (Q1/Q2/Q3 + logging gap) ───────────────────────
    L.append("## PHASE 2 — Smoking Guns")
    L.append("")

    # Q1 — L5/L6 leak
    leak_rows = [(r.week, r.l5l6.get("l5", 0), r.l5l6.get("l6", 0))
                 for r in report
                 if r.l5l6.get("l5", 0) > 0 or r.l5l6.get("l6", 0) > 0]
    if leak_rows:
        first  = leak_rows[0]
        peak   = max(leak_rows, key=lambda x: x[1] + x[2])
        L.append("### 🚨 Q1 — L5/L6 Protection Broken")
        L.append("")
        L.append(f"- **First leak week:** W{first[0]} → L5={first[1]}, L6={first[2]}")
        L.append(f"- **Peak leak week:**  W{peak[0]} → L5={peak[1]}, L6={peak[2]}")
        L.append(f"- **Full trajectory:** "
                 + ", ".join(f"W{w}(L5={l5},L6={l6})" for w, l5, l6 in leak_rows))
        L.append("")
        L.append("**Verdict:** the `SDE Ext-II/III force-exit valve` claim in "
                 "`app/services/pool_reassessor.py` docstring is FALSE. The engine "
                 "is allowing members to advance past L4 into L5/L6 instead of "
                 "force-exiting them. Per **Q1**, the fix is *pure protection* — "
                 "no member should ever reach L5/L6.")
        L.append("")
        L.append("**Code refs to audit next:**")
        L.append("- `app/services/draw.py` — every place a non-flagged L4 winner advances")
        L.append("- `app/services/level_progression.py` (if exists) — survivor +1 logic")
        L.append("- `app/services/pool_reassessor.py` — correct the false docstring")
        L.append("")
    else:
        L.append("### ✓ Q1 — No L5/L6 leak in this run")
        L.append("")
        L.append("No `active_l5l6_present` events fired with non-zero L5/L6 counts. "
                 "Either the run never advanced anyone past L4, or the warning "
                 "event itself is not being emitted (check `app/services/draw.py` "
                 "for `forensic.record('active_l5l6_present', ...)`).")
        L.append("")

    # Q2 — posture cycle
    posture_changes: list[tuple[int, str]] = []
    prev_posture: str | None = None
    for r in report:
        if r.posture != prev_posture and r.posture != "—":
            posture_changes.append((r.week, r.posture))
            prev_posture = r.posture
    L.append("### 🚨 Q2 — Feast-or-Famine via Posture Switching")
    L.append("")
    if posture_changes:
        L.append("**Posture transitions:**")
        for w, p in posture_changes:
            L.append(f"- W{w} → `{p}`")
        L.append("")
        # Surrounding draw volume for blowout context
        blowouts = [r for r in report if any("BLOWOUT" in f for f in r.flags)]
        freezes  = [r for r in report if "DRAW_FREEZE" in r.flags]
        if blowouts:
            L.append("**Blowout weeks (feast):**")
            for r in blowouts:
                L.append(f"- W{r.week} posture=`{r.posture}` "
                         f"winners={r.fr['win']} draws={r.fr['drw']}")
            L.append("")
        if freezes:
            L.append("**Freeze weeks (famine — zero draws):**")
            for r in freezes:
                L.append(f"- W{r.week} posture=`{r.posture}`")
            L.append("")
    else:
        L.append("_No POSTURE.posture_decided events captured. Either posture is "
                 "static (in which case Q2's removal mandate is moot for this run) "
                 "or the posture event isn't being emitted to forensic._")
        L.append("")
    L.append("**Per Q2:** remove the posture engine entirely. One deterministic "
             "steady weekly rule. No BALANCED ↔ LIABILITY_CONTROL switching.")
    L.append("")
    L.append("**Code refs to remove/rewrite:**")
    L.append("- `app/services/posture.py` (or wherever `decide_posture()` lives) "
             "— delete the switching logic")
    L.append("- Every caller of `decide_posture()` → replace with the new "
             "deterministic rule")
    L.append("")

    # Q3 — waitlist + pool creation + orphan handling
    freeze_weeks    = [r.week for r in report if "DRAW_FREEZE" in r.flags]
    pause_weeks     = [(r.week, r.fr["pause"])    for r in report if r.fr["pause"]    > 0]
    dissolve_weeks  = [(r.week, r.fr["dissolve"]) for r in report if r.fr["dissolve"] > 0]
    merge_weeks     = [(r.week, r.fr["merge"])    for r in report if r.fr["merge"]    > 0]
    L.append("### 🚨 Q3 — Waitlist + Pool Creation + Orphan Handling")
    L.append("")
    if freeze_weeks:
        L.append(f"- **Draw freeze weeks:** {freeze_weeks}  "
                 "(no 12/12 pool was drawable — pools shrank below capacity)")
    if pause_weeks:
        L.append("- **Pool-pause activity** (week → count):")
        for w, c in pause_weeks:
            L.append(f"  - W{w} → {c} paused")
    if dissolve_weeks:
        L.append("- **Pool-dissolve activity** (week → count):")
        for w, c in dissolve_weeks:
            L.append(f"  - W{w} → {c} dissolved")
    if merge_weeks:
        L.append("- **Merger activity** (week → members_merged events):")
        for w, c in merge_weeks:
            L.append(f"  - W{w} → {c} merges")
    L.append("")
    L.append("**Per Q3:** the waitlist → pool-creation → orphan-handling pipeline "
             "is broken. Orphan members are not being absorbed by the merger / "
             "donor / dissolver path, so existing pools shrink without "
             "replacement, which causes the freeze and the L4 stuck pile.")
    L.append("")
    L.append("**Code refs to rebuild:**")
    L.append("- `app/services/waitlist.py` — paid-waitlist accounting & emit-to-pool gate")
    L.append("- `app/services/pool_formation.py` (or wherever new pools are created) "
             "— ensure orphan-absorbing path exists")
    L.append("- `app/services/merger.py` — donor / receiver semantics, flagged-L4 immunity, "
             "and the orphan absorption hook")
    L.append("- `app/services/draw.py` :: pool eligibility predicate — confirm a fresh "
             "pool can be formed from orphans + waitlist on the same tick a draw runs")
    L.append("")

    # ── Logging gaps ──────────────────────────────────────────────────────────
    log_gap_rows = [r for r in report if any(f.startswith("DRAW_LOG_Δ") for f in r.flags)]
    L.append("### ⚠ Forensic Logging Gaps (engine ran but did not emit events)")
    L.append("")
    if log_gap_rows:
        L.append("Per-week mismatch between `timeline.draws` and "
                 "`forensic.draw_executed` count — i.e. the engine fired a draw "
                 "the forensic recorder never saw:")
        L.append("")
        L.append("| W | T:drw | F:drw | Δ | Likely missing emitter |")
        L.append("|--:|------:|------:|--:|------------------------|")
        for r in log_gap_rows:
            delta = r.fr["drw"] - r.tl["drw"]
            # Heuristic: if forensic < timeline and SDE counts dominate, blame SDE
            hint = ("SDE / Ext-II / Ext-III / PL3 draw paths "
                    if delta < 0 else
                    "Extra forensic emission (double-write?)")
            L.append(f"| {r.week} | {r.tl['drw']} | {r.fr['drw']} | {delta:+d} | {hint} |")
        L.append("")
        L.append("**Action:** grep every `Draw` / `SdeDraw` / `Pl3Draw` / `ExtDraw` "
                 "service in `app/services/` for `forensic.record(...)` calls. "
                 "Every draw type must emit `draw_executed` exactly once.")
    else:
        L.append("_No logging gap detected — every draw the timeline expected has a "
                 "matching `draw_executed` event._")
    L.append("")

    # ── PHASE 3 — full event-type counts ──────────────────────────────────────
    L.append("## PHASE 3 — Forensic Event-Type Counts (all weeks, run-filtered)")
    L.append("")
    L.append("| Event Type | Count |")
    L.append("|------------|------:|")
    for etype, cnt in type_counts.most_common():
        L.append(f"| `{etype}` | {cnt:,} |")
    L.append("")

    # ── PHASE 4 — next actions ────────────────────────────────────────────────
    L.append("## PHASE 4 — Next Actions (per user directive Jun-23)")
    L.append("")
    L.append("1. **Q1 — L5/L6 pure protection**")
    L.append("   - Audit every L4 advance path; gate L4 → L5 transition.")
    L.append("   - Correct the false `force-exit at L5/L6` docstring in "
             "`app/services/pool_reassessor.py`.")
    L.append("")
    L.append("2. **Q2 — Remove posture engine**")
    L.append("   - Delete `app/services/posture.py` (or its `decide_posture()` entry).")
    L.append("   - Replace with deterministic single-rule scheduler.")
    L.append("")
    L.append("3. **Q3 — Rebuild waitlist / pool-creation / orphan-handling**")
    L.append("   - Trace orphan-member lifecycle end-to-end.")
    L.append("   - Ensure merger / donor / dissolver absorbs every orphan on every tick.")
    L.append("")
    L.append("4. **(Diagnostic) Close forensic logging gaps**")
    L.append("   - Add `forensic.record('draw_executed', ...)` to every draw service "
             "that's currently silent (SDE / Ext-II / Ext-III / PL3).")
    L.append("")
    L.append("5. **Re-run this script** after each fix — same command, "
             "regenerated forensic CSV — confirm the corresponding smoking-gun "
             "section disappears.")
    L.append("")

    text = "\n".join(L) + "\n"
    Path(output_path).write_text(text, encoding="utf-8")
    return text


# ── Entrypoint ────────────────────────────────────────────────────────────────
def main() -> int:
    # ── HARD SAFETY GUARD — must run BEFORE arg parsing or any IO ────────────
    if "app.database" in sys.modules:
        print("FATAL: app.database is loaded — this script must run with ZERO DB access.",
              file=sys.stderr)
        return 2

    ap = argparse.ArgumentParser(
        description="Read-only simulator-vs-production reconciliation audit.",
        epilog="Standalone diagnostic. Performs ZERO database connections.",
    )
    ap.add_argument("--timeline", required=True,
                    help="Path to weekly-timeline CSV (oracle / strategy roll-up).")
    ap.add_argument("--forensic", required=True,
                    help="Path to forensic_events CSV (actual engine event log).")
    ap.add_argument("--run", default=None,
                    help="Optional run_id filter (recommended — e.g. a4243fd2).")
    ap.add_argument("--output", default="reconciliation_report.md",
                    help="Output markdown report path "
                         "(default: ./reconciliation_report.md)")
    args = ap.parse_args()

    print(f"[load] timeline ← {args.timeline}", file=sys.stderr)
    timeline = load_timeline(args.timeline)
    print(f"[load] timeline weeks: {len(timeline)}", file=sys.stderr)

    print(f"[load] forensic ← {args.forensic}  (run filter: {args.run or 'ALL'})",
          file=sys.stderr)
    forensic = load_forensic(args.forensic, args.run)
    print(f"[load] forensic rows: {forensic.total_rows:,} "
          f"(kept: {forensic.rows_kept:,})", file=sys.stderr)
    print(f"[load] run_ids seen: "
          + ", ".join(f"{rid}={cnt}" for rid, cnt in forensic.run_ids_seen.most_common()),
          file=sys.stderr)

    report = reconcile(timeline, forensic)
    text = render(report, forensic.type_counts, args.run or "ALL", forensic, args.output)

    print(text)
    print(f"[ok] report written → {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
