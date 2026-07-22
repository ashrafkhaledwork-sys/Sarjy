from app.db import engine
from app.db.repositories import MetricsRepo, _percentile


def make_repo():
    engine.init_db("sqlite:///:memory:")
    gen = engine.get_db()
    db = next(gen)
    return MetricsRepo(db), db


class TestPercentile:
    def test_empty(self):
        assert _percentile([], 0.5) == 0

    def test_single(self):
        assert _percentile([100], 0.5) == 100
        assert _percentile([100], 0.95) == 100

    def test_p50_and_p95(self):
        values = sorted(range(1, 101))  # 1..100
        assert _percentile(values, 0.50) == 50
        assert _percentile(values, 0.95) == 95


class TestSummary:
    def test_empty_summary(self):
        repo, db = make_repo()
        assert repo.summary() == {"turns": 0}
        db.close()

    def test_summary_aggregates(self):
        repo, db = make_repo()
        for i in range(10):
            repo.add(
                request_id=f"r{i}",
                kind="voice" if i % 2 else "text",
                stt_ms=100 * i,
                llm_ms=500,
                tool_ms=0,
                total_ms=1000 + 100 * i,
                tokens_in=1000,
                tokens_out=100,
                workflow_status="IDLE",
            )
        s = repo.summary()
        assert s["turns"] == 10
        assert s["voice_turns"] == 5
        assert s["llm"]["p50_ms"] == 500
        assert s["server_total"]["p95_ms"] >= s["server_total"]["p50_ms"]
        assert s["tokens"] == {"in": 10000, "out": 1000}
        # 10k in * 0.15/M + 1k out * 0.60/M
        assert s["est_llm_cost_usd"] == round(10000 * 0.15 / 1e6 + 1000 * 0.60 / 1e6, 4)
        db.close()
