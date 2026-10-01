import asyncio

import httpx
import pytest

from leetcode_review.config import Credentials
from leetcode_review.leetcode.graphql import CredentialsExpiredError, CredentialsMissingError
from leetcode_review.leetcode.provider import LeetCodeProvider
from leetcode_review.schemas import Note
from leetcode_review.storage.problems import ProblemStore, parse_slug
from leetcode_review.sync import add_problem, sync_problems
from tests.conftest import make_pack


def run(coro):
    return asyncio.run(coro)


def do_sync(paths, fake, creds, now, **kw):
    async def go():
        async with LeetCodeProvider(creds, transport=fake.transport()) as prov:
            return await sync_problems(prov, ProblemStore(paths), now=now, **kw)
    return run(go())


def test_import_creates_one_file_per_problem_with_python_solution(paths, fake, creds, now):
    report = do_sync(paths, fake, creds, now)
    assert (report.solved_found, report.new, report.updated, report.unchanged) == (3, 3, 0, 0)
    assert report.with_python == 2 and report.python_unavailable == 1
    assert sorted(f.stem for f in paths.problems.glob("*.json")) == ["lonely-cpp", "two-sum", "valid-parentheses"]
    two = ProblemStore(paths).get("two-sum")
    assert two.status == "solved" and two.leetcode_id == "1" and two.difficulty == "Easy"
    assert two.latest_submission.language == "Python3"
    assert "old" in two.latest_submission.code          # newest ACCEPTED python3, not the wrong answer/cpp
    assert two.latest_submission.submission_id == "102"
    assert two.constraints == ["1 <= n <= 10"] and two.problem_statement.startswith("Statement.")
    assert ProblemStore(paths).get("lonely-cpp").latest_submission is None  # still imported


def test_sync_is_idempotent_and_does_not_rewrite_unchanged_files(paths, fake, creds, now):
    do_sync(paths, fake, creds, now)
    before = {f.name: f.read_bytes() for f in paths.problems.glob("*.json")}
    again = do_sync(paths, fake, creds, now.replace(hour=15))
    assert (again.new, again.updated, again.unchanged) == (0, 0, 3)
    assert {f.name: f.read_bytes() for f in paths.problems.glob("*.json")} == before
    assert len(list(paths.problems.glob("*.json"))) == 3


def test_incremental_sync_picks_up_new_solve_and_newer_submission(paths, fake, creds, now):
    do_sync(paths, fake, creds, now)
    fake.add_submission("two-sum", 104, "python3", "Accepted", 1700009999, "class Solution:\n    pass  # new")
    fake.add_problem("3sum", 15, "3Sum", subs=[(401, "python3", "Accepted", 1700003000, "# 3sum")])
    report = do_sync(paths, fake, creds, now.replace(day=2))
    assert (report.new, report.updated, report.unchanged) == (1, 1, 2)
    assert "new" in ProblemStore(paths).get("two-sum").latest_submission.code
    assert report.new_slugs == ["3sum"]


def test_sync_converts_unsolved_to_solved_preserving_notes_and_packs(paths, fake, creds, now):
    store = ProblemStore(paths)
    run(_add_offline(paths, "valid-parentheses", now))
    prob = store.get("valid-parentheses")
    assert prob.status == "unsolved"
    prob.notes.append(Note(id="n1", text="remember the stack", created_at="2026-10-01T00:00:00Z"))
    prob.model_extra["customField"] = "keep me"
    store.save(prob)
    make_pack(paths, "valid-parentheses")
    pack_bytes = (paths.review_packs / "valid-parentheses.json").read_bytes()

    report = do_sync(paths, fake, creds, now)
    after = store.get("valid-parentheses")
    assert after.status == "solved" and after.source == "manual"
    assert after.latest_submission.code.endswith("# vp")
    assert after.notes[0].text == "remember the stack" and after.model_extra["customField"] == "keep me"
    assert report.converted_to_solved == ["valid-parentheses"]
    assert (paths.review_packs / "valid-parentheses.json").read_bytes() == pack_bytes


async def _add_offline(paths, slug, now):
    async with LeetCodeProvider(None) as prov:
        return await add_problem(prov, ProblemStore(paths), slug, now=now, offline=True)


def test_add_problem_online_and_existing(paths, fake, now):
    async def go():
        async with LeetCodeProvider(None, transport=fake.transport()) as prov:
            first = await add_problem(prov, ProblemStore(paths), "https://leetcode.com/problems/two-sum/description/", now=now)
            second = await add_problem(prov, ProblemStore(paths), "two-sum", now=now)
            return first, second
    (p1, created1), (p2, created2) = run(go())
    assert created1 and not created2
    assert p1.status == "unsolved" and p1.title == "Two Sum" and p1.problem_statement


def test_parse_slug():
    assert parse_slug("https://leetcode.com/problems/minimum-window-substring/") == "minimum-window-substring"
    assert parse_slug("Minimum-Window-Substring") == "minimum-window-substring"
    with pytest.raises(ValueError):
        parse_slug("not a slug!")


def test_expired_session_raises_clear_error(paths, fake, creds, now):
    fake.signed_in = False
    with pytest.raises(CredentialsExpiredError) as exc:
        do_sync(paths, fake, creds, now)
    assert "appears to have expired" in str(exc.value) and "LEETCODE_SESSION and csrftoken" in str(exc.value)
    fake.signed_in, fake.http_status = True, 403
    with pytest.raises(CredentialsExpiredError):
        do_sync(paths, fake, creds, now)


def test_missing_credentials_error(paths, fake, now):
    with pytest.raises(CredentialsMissingError):
        do_sync(paths, fake, None, now)


def test_secrets_not_in_repr_and_csrf_fetched_when_missing(fake):
    assert "secret" not in repr(Credentials("session-secret", "csrf-secret"))
    seen = {}

    def handler(req: httpx.Request):
        if req.method == "POST":
            seen["csrf"] = req.headers.get("x-csrftoken")
            seen["cookie"] = req.headers.get("cookie")
        return fake.handler(req)

    async def go():
        async with LeetCodeProvider(Credentials("sess"), transport=httpx.MockTransport(handler)) as prov:
            return await prov.validate_credentials()
    assert run(go()) == "tester"
    assert seen["csrf"] == "fetched-token" and "LEETCODE_SESSION=sess" in seen["cookie"]


def test_pagination_of_solved_list(paths, fake, creds, now):
    for i in range(250):
        fake.add_problem(f"p-{i}", 2000 + i, f"P {i}", subs=())
    async def go():
        async with LeetCodeProvider(creds, transport=fake.transport()) as prov:
            return await prov.get_solved_problems()
    assert len(run(go())) == 253


def test_seed_problems_get_real_statement_on_first_sync(paths, fake, creds, now):
    store = ProblemStore(paths)
    run(_add_offline(paths, "two-sum", now))
    seed = store.get("two-sum")
    seed.source, seed.problem_statement, seed.constraints = "seed", "paraphrased seed text", ["seed constraint"]
    store.save(seed)
    do_sync(paths, fake, creds, now)
    real = store.get("two-sum")
    assert real.source == "leetcode" and real.problem_statement.startswith("Statement.")
    assert real.constraints == ["1 <= n <= 10"] and real.status == "solved"
