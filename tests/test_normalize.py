from leetcode_review.leetcode.normalize import (
    RawSubmission, extract_constraints, html_to_text, normalize_details, normalize_solved,
    normalize_submission, pick_latest_python,
)


def test_html_to_text_handles_entities_lists_and_superscripts():
    text = html_to_text("<p>Given <code>nums</code> &amp; target.</p><ul><li>10<sup>4</sup></li></ul>")
    assert "Given nums & target." in text
    assert "- 10^4" in text


def test_extract_constraints_stops_at_followup():
    text = "Intro\n\nConstraints:\n\n- 1 <= n <= 5\n- a is sorted\n\nFollow up: do better."
    assert extract_constraints(text) == ["1 <= n <= 5", "a is sorted"]


def test_normalize_solved_and_details():
    s = normalize_solved({"frontendQuestionId": 15, "title": "3Sum", "titleSlug": "3sum", "difficulty": "MEDIUM",
                          "paidOnly": False, "acRate": 36.4567, "topicTags": [{"name": "Array"}]})
    assert (s.leetcode_id, s.difficulty, s.tags, s.ac_rate) == ("15", "Medium", ["Array"], 36.46)
    d = normalize_details({"questionFrontendId": "15", "title": "3Sum", "titleSlug": "3sum", "difficulty": "Medium",
                           "isPaidOnly": True, "content": None, "hints": ["<p>h</p>", None], "topicTags": []})
    assert d.statement == "" and d.constraints == [] and d.hints == ["h"] and d.premium


def test_submission_normalization_and_python_preference():
    sub = normalize_submission({"id": 7, "statusDisplay": "Accepted", "lang": "Python3", "timestamp": "1700000000"})
    assert sub.lang == "python3" and sub.timestamp == "2023-11-14T22:13:20Z"
    subs = [RawSubmission("1", "Accepted", "python", "2024-01-01T00:00:00Z"),
            RawSubmission("2", "Accepted", "python3", "2023-01-01T00:00:00Z"),
            RawSubmission("3", "Accepted", "python3", "2023-06-01T00:00:00Z"),
            RawSubmission("4", "Wrong Answer", "python3", "2025-01-01T00:00:00Z"),
            RawSubmission("5", "Accepted", "cpp", "2025-01-01T00:00:00Z")]
    assert pick_latest_python(subs).id == "3"  # newest accepted python3 beats a newer python2
    assert pick_latest_python(subs[:1]).id == "1"  # falls back to python
    assert pick_latest_python(subs[3:]) is None
