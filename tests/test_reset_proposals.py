"""reset_proposals CLI: TRUNCATE remediation_proposals only, print counts."""

from cinetrace.clickhouse import reset_proposals as rp


class _FakeQuery:
    def __init__(self, n: int) -> None:
        self.result_rows = [[n]]


class _FakeClient:
    def __init__(self, n: int = 4) -> None:
        self.n = n
        self.commands: list[str] = []
        self.queries: list[str] = []
        self.closed = False

    def query(self, sql, parameters=None):
        self.queries.append(sql)
        assert "render_jobs" not in sql.lower()
        assert "remediation_proposals" in sql.lower()
        return _FakeQuery(self.n)

    def command(self, sql) -> None:
        self.commands.append(sql)
        assert sql == rp.TRUNCATE_SQL
        assert "render_jobs" not in sql.lower()
        self.n = 0

    def close(self) -> None:
        self.closed = True


def test_reset_proposals_truncates_only_proposals(monkeypatch) -> None:
    fake = _FakeClient(n=4)
    monkeypatch.setattr(rp, "get_client", lambda: fake)
    counts = rp.reset_proposals()
    assert counts == {"before": 4, "after": 0}
    assert fake.commands == [rp.TRUNCATE_SQL]
    assert fake.queries == [rp.COUNT_SQL, rp.COUNT_SQL]
    assert fake.closed is True


def test_reset_proposals_main_prints_before_after(monkeypatch, capsys) -> None:
    monkeypatch.setattr(rp, "reset_proposals", lambda: {"before": 3, "after": 0})
    rp.main()
    out = capsys.readouterr().out
    assert "before = 3" in out
    assert "after = 0" in out
    assert "render_jobs" not in out
