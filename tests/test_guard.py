from cinetrace.web.guard import extract_token, token_ok


def test_extract_prefers_x_run_token(monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISOR_RUN_TOKEN", "abc")
    assert extract_token("Bearer other", "abc") == "abc"


def test_empty_expected_token_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISOR_RUN_TOKEN", "")
    assert token_ok("anything") is False
