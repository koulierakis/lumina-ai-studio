from mentor import _normalize_answer


def test_normalize_answer_accepts_structured_json() -> None:
    answer = _normalize_answer('{"summary":"Focus","priorities":["A"],"next_actions":["B"],"risks":["C"],"reflection_question":"Why now?"}')
    assert answer["summary"] == "Focus"
    assert answer["priorities"] == ["A"]
    assert answer["next_actions"] == ["B"]
    assert answer["risks"] == ["C"]
    assert answer["reflection_question"] == "Why now?"


def test_normalize_answer_falls_back_without_losing_content() -> None:
    answer = _normalize_answer("A direct unstructured response")
    assert answer["summary"] == "A direct unstructured response"
    assert answer["next_actions"] == []
    assert answer["reflection_question"]


def test_normalize_answer_caps_structured_lists() -> None:
    raw = '{"summary":"x","priorities":["1","2","3","4","5","6"],"next_actions":["1","2","3","4","5","6","7","8"],"risks":["1","2","3","4","5","6"],"reflection_question":"q"}'
    answer = _normalize_answer(raw)
    assert len(answer["priorities"]) == 5
    assert len(answer["next_actions"]) == 7
    assert len(answer["risks"]) == 5
