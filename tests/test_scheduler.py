from datetime import timedelta

from leetcode_review import config as C
from leetcode_review.review.scheduler import (
    apply_problem_event, compute_problem_outcome, days_overdue, due_status, interval_days, next_review_at,
)
from leetcode_review.review.scoring import (
    compute_weak_categories, core_blocking_failure, problem_score, record_card_result,
)
from leetcode_review.schemas import ProblemState

ALL_CORRECT = [("pattern", "correct"), ("main_insight", "correct"), ("time_complexity", "correct")]


def test_problem_score_weights_core_categories_more():
    assert problem_score(ALL_CORRECT) == 1.0
    assert problem_score([("pattern", "failed"), ("edge_case", "correct")]) < 0.5
    assert problem_score([("pattern", "correct"), ("edge_case", "failed")]) > 0.5
    assert problem_score([("pattern", "partial")]) == 0.5
    assert problem_score([]) == 0.0


def test_intervals_follow_levels_and_shrink_for_hold_and_weak():
    assert [interval_days(l) for l in range(7)] == [0, 1, 3, 7, 14, 30, 60]
    assert interval_days(4, hold=True) == 10  # 14 * .75 -> 10.5 -> round half even = 10
    assert interval_days(4, weak=True) == 10
    assert interval_days(1, hold=True, weak=True) == 1  # never below one day
    assert interval_days(0, weak=True) == 0


def test_next_review_is_midnight_utc_or_now(now):
    assert next_review_at(3, now) == "2026-10-08T00:00:00Z"
    assert next_review_at(0, now) == "2026-10-01T12:00:00Z"


def test_due_status_boundaries(now):
    assert due_status(None, now) == "new"
    ps = ProblemState(level=2, review_count=1, next_review="2026-10-01T00:00:00Z")
    assert due_status(ps, now) == "due"             # due date is today
    ps.next_review = "2026-09-28T00:00:00Z"
    assert due_status(ps, now) == "overdue" and days_overdue(ps, now) == 3
    ps.next_review = "2026-10-02T00:00:00Z"
    assert due_status(ps, now) == "upcoming"


def outcome(level, results, now, **kw):
    ps = ProblemState(level=level, review_count=1, next_review=(now - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z"))
    return compute_problem_outcome(ps, problem_score(results), blocking_failure=core_blocking_failure(results), now=now, **kw)


def test_strong_performance_promotes_and_schedules_longer(now):
    o = outcome(2, ALL_CORRECT, now)
    assert (o.outcome, o.level_after, o.next_review) == ("promote", 3, "2026-10-08T00:00:00Z")
    assert outcome(C.MAX_LEVEL, ALL_CORRECT, now).level_after == C.MAX_LEVEL


def test_mixed_holds_with_shorter_interval_poor_demotes_fail_drops(now):
    mixed = [("pattern", "correct"), ("main_insight", "partial"), ("time_complexity", "partial")]
    o = outcome(4, mixed, now)
    assert (o.outcome, o.level_after) == ("hold", 4) and o.next_review == "2026-10-11T00:00:00Z"  # 10 days
    poor = [("pattern", "partial"), ("main_insight", "partial"), ("time_complexity", "failed")]
    o = outcome(4, poor, now)
    assert (o.outcome, o.level_after) == ("demote", 3)
    bad = [("pattern", "failed"), ("main_insight", "failed"), ("time_complexity", "partial")]
    o = outcome(4, bad, now)
    assert (o.outcome, o.level_after) == ("fail", 2)
    assert outcome(1, bad, now).level_after == 0 and outcome(1, bad, now).next_review == "2026-10-01T12:00:00Z"


def test_failed_core_card_blocks_promotion_even_with_high_score(now):
    results = [("pattern", "failed")] + [("edge_case", "correct")] * 10 + [("implementation_detail", "correct")] * 10
    assert problem_score(results) >= C.PROMOTE_SCORE
    assert outcome(2, results, now).outcome == "hold"


def test_forgot_drops_mastery_significantly_and_is_due_immediately(now):
    o = outcome(5, [], now, forgot=True)
    assert (o.outcome, o.level_after, o.next_review) == ("forgot", 2, "2026-10-01T12:00:00Z")  # due next session
    assert outcome(2, [], now, forgot=True).level_after == 0


def test_early_successful_review_does_not_change_schedule(now):
    ps = ProblemState(level=4, review_count=3, next_review="2026-10-10T00:00:00Z")
    o = compute_problem_outcome(ps, 1.0, blocking_failure=False, now=now)
    assert (o.outcome, o.level_after, o.next_review) == ("early_keep", 4, "2026-10-10T00:00:00Z")
    # ...but an early failure still demotes
    o = compute_problem_outcome(ps, 0.1, blocking_failure=True, now=now)
    assert o.level_after == 2


def test_weak_categories_shorten_interval(now):
    ps = ProblemState(level=2, review_count=1, next_review="2026-09-30T00:00:00Z")
    for ts in ("t1", "t2"):
        record_card_result(ps, "c-space", "space_complexity", "failed", ts)
    assert ps.weak_categories == ["space_complexity"]
    o = compute_problem_outcome(ps, 1.0, blocking_failure=False, now=now)
    assert o.level_after == 3 and o.next_review == "2026-10-06T00:00:00Z"  # 7 * .75 = 5.25 -> 5 days


def test_apply_problem_event_updates_state_and_ema(now):
    ps = ProblemState()
    ev = {"timestamp": "2026-10-01T12:00:00Z", "score": 1.0, "levelAfter": 1, "nextReview": "2026-10-02T00:00:00Z", "outcome": "promote"}
    apply_problem_event(ps, ev)
    assert (ps.level, ps.review_count, ps.recent_accuracy, ps.lapses) == (1, 1, 1.0, 0)
    apply_problem_event(ps, {**ev, "score": 0.0, "levelAfter": 0, "outcome": "fail"})
    assert (ps.recent_accuracy, ps.lapses) == (0.5, 1)


def test_card_and_category_stats_and_weak_detection():
    ps = ProblemState()
    record_card_result(ps, "c1", "pattern", "correct", "t1")
    record_card_result(ps, "c2", "space_complexity", "failed", "t2")
    assert ps.card_stats["c2"].incorrect_streak == 1 and ps.weak_categories == []  # one miss is not a pattern
    record_card_result(ps, "c2", "space_complexity", "partial", "t3")
    cs = ps.card_stats["c2"]
    assert (cs.seen, cs.failed, cs.partial, cs.incorrect_streak, cs.last_result) == (2, 1, 1, 2, "partial")
    assert ps.weak_categories == ["space_complexity"]
    for t in ("t4", "t5", "t6"):
        record_card_result(ps, "c2", "space_complexity", "correct", t)
    assert compute_weak_categories(ps) == []  # recovered
