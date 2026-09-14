"""Wake workflow must flip the ticker without wiping Cloud Run env."""

from pathlib import Path

WAKE = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "wake-clickhouse.yml"


def test_wake_workflow_is_dispatchable_and_additive() -> None:
    text = WAKE.read_text()
    assert "workflow_dispatch:" in text
    assert "--update-env-vars LIVE_TICKER_ENABLED=true" in text
    assert "--set-env-vars" not in text
    assert "--max-instances=2" in text
    assert "--cpu-boost" in text
    assert "gcloud logging read" in text
    assert "CLICKHOUSE_PASSWORD" not in text
