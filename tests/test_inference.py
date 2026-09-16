"""Row parsing, notebook generation and error typing."""
import json

import pytest

import inference


def test_parse_rows_handles_fenced_json_arrays():
    raw = '```json\n[{"question":"Q1","answer":"A1"},{"question":"Q2","answer":"A2"}]\n```'
    rows = inference._parse_rows(raw, ["question", "answer"])
    assert rows == [
        {"question": "Q1", "answer": "A1"},
        {"question": "Q2", "answer": "A2"},
    ]


def test_parse_rows_is_case_insensitive_about_keys():
    rows = inference._parse_rows('{"Question": "Q", "ANSWER": "A"}', ["question", "answer"])
    assert rows == [{"question": "Q", "answer": "A"}]


def test_parse_rows_fills_missing_columns():
    rows = inference._parse_rows('{"question": "Q"}', ["question", "answer"])
    assert rows == [{"question": "Q", "answer": ""}]


def test_parse_rows_drops_prose():
    assert inference._parse_rows("Sure! Here you go.", ["a"]) == []


def test_generate_rows_batches_requests(monkeypatch):
    calls = []

    def fake_call(repo, prompt, **kwargs):
        calls.append(prompt)
        return json.dumps([{"input": f"i{n}", "output": f"o{n}"} for n in range(10)])

    monkeypatch.setattr(inference, "call_hf", fake_call)
    rows = inference.generate_rows("topic", ["input", "output"], "tabular", 25)

    assert len(rows) == 25
    assert len(calls) == 3, "25 rows should take 3 batched calls, not 25"


def test_generate_rows_reports_progress(monkeypatch):
    monkeypatch.setattr(inference, "call_hf",
                        lambda *a, **k: json.dumps([{"a": "1"}] * 10))
    seen = []
    inference.generate_rows("t", ["a"], "tabular", 20, progress_cb=lambda d, t: seen.append(d))
    assert seen == [10, 20]


def test_generate_rows_raises_rather_than_inventing_data(monkeypatch):
    monkeypatch.setattr(inference, "call_hf", lambda *a, **k: "I cannot help with that.")
    with pytest.raises(inference.InferenceError):
        inference.generate_rows("t", ["a"], "tabular", 5)


def test_generate_rows_requires_columns():
    with pytest.raises(inference.InferenceError):
        inference.generate_rows("t", [], "tabular", 5)


def test_notebook_is_valid_json_with_hostile_content():
    rows = [{"text": 'quote " backslash \\ triple \'\'\' newline \n end'}]
    document = json.loads(inference.generate_colab_notebook("M", "base/x", "out/y", rows))

    assert document["nbformat"] == 4
    assert len(document["cells"]) == 9


def test_notebook_roundtrips_the_dataset():
    rows = [{"a": 'he said "hi"'}, {"a": "line\nbreak"}]
    document = json.loads(inference.generate_colab_notebook("M", "b", "o", rows))
    data_cell = "".join(document["cells"][4]["source"])

    assignment = next(l for l in data_cell.splitlines() if l.startswith("raw = "))
    namespace = {"json": json}
    exec(assignment, namespace)
    assert namespace["raw"] == rows


def test_notebook_never_embeds_a_token():
    notebook = inference.generate_colab_notebook(
        "M", "b", "o", [{"a": "1"}], hf_token="hf_supersecret")
    assert "hf_supersecret" not in notebook
    assert "notebook_login" in notebook


def test_notebook_caps_embedded_rows():
    rows = [{"a": str(i)} for i in range(900)]
    document = json.loads(inference.generate_colab_notebook("M", "b", "o", rows))
    assert "900 rows" not in "".join(document["cells"][0]["source"])
    assert "500 rows" in "".join(document["cells"][0]["source"])


def test_suggest_columns():
    assert inference.suggest_columns("customer reviews") == ["text", "sentiment", "score"]
    assert inference.suggest_columns("Q&A about python") == ["question", "answer"]
    assert inference.suggest_columns("something else") == ["input", "output"]


def test_extract_row_count():
    assert inference.extract_row_count("give me 120 rows") == 120
    assert inference.extract_row_count("50 examples please") == 50
    assert inference.extract_row_count("no numbers here") is None


def test_chat_falls_back_without_a_token(monkeypatch):
    monkeypatch.setattr(inference.config, "HF_TOKEN", "")
    reply = inference.chat_response("I want movie review data")
    assert "sentiment" in reply


def test_chat_falls_back_when_inference_fails(monkeypatch):
    monkeypatch.setattr(inference.config, "HF_TOKEN", "hf_test")
    monkeypatch.setattr(inference, "call_agent",
                        lambda *a, **k: (_ for _ in ()).throw(inference.InferenceError("down")))
    assert inference.chat_response("build me reviews")


def test_model_loading_is_a_distinct_error(monkeypatch):
    class Response:
        status_code = 503
        ok = False

    monkeypatch.setattr(inference.requests, "post", lambda *a, **k: Response())
    monkeypatch.setattr(inference.time, "sleep", lambda *_: None)

    with pytest.raises(inference.ModelLoadingError):
        inference.call_hf("repo/x", "hello")


def test_http_errors_raise_inference_error(monkeypatch):
    class Response:
        status_code = 404
        ok = False

    monkeypatch.setattr(inference.requests, "post", lambda *a, **k: Response())
    with pytest.raises(inference.InferenceError, match="not found"):
        inference.call_hf("repo/missing", "hello")
