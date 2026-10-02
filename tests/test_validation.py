import json

from leetcode_review.content.validator import validate_all, validate_pack_file
from tests.conftest import free, make_pack, make_problem, mcq


def issues_for(paths, slug, pack_dict, *, create_problem=True):
    if create_problem:
        make_problem(paths, slug)
    (paths.review_packs / f"{slug}.json").write_text(json.dumps(pack_dict))
    return validate_pack_file(paths.review_packs / f"{slug}.json", {slug} if create_problem else set())


def base(slug="p", cards=None):
    return {"problemSlug": slug, "summary": "s", "patterns": ["Stack"],
            "approaches": [{"name": "A", "summary": "x", "timeComplexity": "O(n)", "spaceComplexity": "O(1)"}],
            "cards": cards if cards is not None else [mcq("p-1")]}


def errors(issues):
    return [i.message for i in issues if i.level == "error"]


def test_valid_pack_has_no_errors(paths):
    assert errors(issues_for(paths, "p", base(cards=[mcq("p-1"), free("p-2")]))) == []


def test_seed_style_pack_fully_valid(paths):
    make_problem(paths, "x")
    make_pack(paths, "x")
    assert [i for i in validate_all(paths, {"x"}) if i.level == "error"] == []


def test_invalid_json_is_actionable(paths):
    (paths.review_packs / "p.json").write_text("{oops")
    msg = validate_pack_file(paths.review_packs / "p.json", {"p"})[0]
    assert msg.level == "error" and "invalid JSON" in msg.message and "line" in msg.message


def test_duplicate_card_ids_and_unknown_problem_and_slug_mismatch(paths):
    errs = errors(issues_for(paths, "p", base(cards=[mcq("dup"), free("dup")])))
    assert any("duplicate card id 'dup'" in e for e in errs)
    errs = errors(issues_for(paths, "q", base("q"), create_problem=False))
    assert any("no problem file" in e for e in errs)
    errs = errors(issues_for(paths, "r", base("not-r")))
    assert any("must match the file name" in e for e in errs)


def test_card_rules(paths):
    bad_cat = {**free("c1"), "category": "vibes"}
    bad_type = {**free("c2"), "type": "essay"}
    no_answer = {k: v for k, v in free("c3").items() if k != "answer"}
    answer_not_option = {**mcq("c4"), "answer": "Z"}
    two_options = {**mcq("c5"), "options": ["A-opt", "B-opt"], "incorrectOptionExplanations": {}}
    bad_expl_key = {**mcq("c6"), "incorrectOptionExplanations": {"nope": "x"}}
    no_blank = {"id": "c7", "category": "time_complexity", "type": "fill_blank", "promptVariants": ["Time?"],
                "answer": "O(n)", "explanation": "e"}
    no_code = {"id": "c8", "category": "code_reasoning", "type": "code_question", "promptVariants": ["why?"],
               "answer": "a", "explanation": "e"}
    no_variants = {**free("c9"), "promptVariants": []}
    errs = " | ".join(errors(issues_for(paths, "p", base(cards=[
        bad_cat, bad_type, no_answer, answer_not_option, two_options, bad_expl_key, no_blank, no_code, no_variants]))))
    for needle in ["category 'vibes' is invalid", "type 'essay' is invalid", "answer is required",
                   "answer 'Z' is not one of the options", "needs 3-6 options", "is not an option",
                   "'___' blank", "needs a 'code' snippet", "at least one non-empty prompt"]:
        assert needle in errs, needle


def test_unknown_field_and_warnings(paths):
    raw = base(cards=[{**free("c1"), "promtVariants": ["typo"]}])
    assert any("unknown field" in e for e in errors(issues_for(paths, "p", raw)))
    skeleton = {"problemSlug": "p", "summary": "", "patterns": [], "cards": []}
    issues = issues_for(paths, "p", skeleton)
    assert errors(issues) == [] and {i.level for i in issues} == {"warning"}


def test_custom_cards_collision_detected(paths):
    make_problem(paths, "p")
    (paths.review_packs / "p.json").write_text(json.dumps(base()))
    (paths.custom_cards / "p.json").write_text(json.dumps({"problemSlug": "p", "cards": [free("p-1")]}))
    assert any("collide" in i.message for i in validate_all(paths, {"p"}))


def test_invalid_canonical_code_is_an_error(paths):
    from leetcode_review.content.validator import validate_pack_file
    from tests.conftest import make_pack, make_problem
    make_problem(paths, "two-sum", leetcode_id=1)
    make_pack(paths, "two-sum")
    f = paths.review_packs / "two-sum.json"
    d = json.loads(f.read_text())
    d["canonicalCode"] = "def f(:\n  pass"
    f.write_text(json.dumps(d))
    issues = validate_pack_file(f, {"two-sum"})
    assert any(i.level == "error" and "canonicalCode is not valid Python" in i.message for i in issues)
    d["canonicalCode"] = "def f():\n    return 1\n"
    f.write_text(json.dumps(d))
    assert not [i for i in validate_pack_file(f, {"two-sum"}) if i.level == "error"]


def test_duplicate_card_ids_across_packs_are_an_error(paths):
    from leetcode_review.content.validator import validate_all
    from tests.conftest import make_pack, make_problem
    for slug in ("one", "two"):
        make_problem(paths, slug, leetcode_id=hash(slug) % 1000)
    make_pack(paths, "one")
    make_pack(paths, "two")
    f = paths.review_packs / "two.json"
    d = json.loads(f.read_text())
    d["cards"][0]["id"] = "one-pattern-01"                     # collides with the card of pack 'one'
    f.write_text(json.dumps(d))
    issues = validate_all(paths, {"one", "two"})
    assert any(i.level == "error" and "one-pattern-01" in i.message and "unique across packs" in i.message for i in issues)
