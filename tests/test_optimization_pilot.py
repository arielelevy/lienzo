import copy

import agent_evaluation
import optimization_pilot as p
import pytest


def report():
    return agent_evaluation.summarize({"session_id": "synthetic-secret", "agent": "codex",
        "repo": "project", "model": "model"}, {"turns": [], "meta": {"version": "version"}})


def test_sample_contains_no_raw_identifiers_or_tools():
    data = report()
    data["evidence"]["tools"] = [{"tool": "secret-tool-name", "turn": "secret-id"}]
    body = p.sample(data, "source")
    assert "synthetic-secret" not in str(body) and "secret-tool-name" not in str(body)
    assert body["state"]["context"]["profile"] == "unknown"
    assert not body["state"]["metrics"]["quality_labels_available"]


def test_context_and_source_changes_invalidate_sample():
    data = report()
    before = p.sample(data, "source")["snapshot"]
    for name in ("project", "agent", "model", "version", "profile_origin"):
        changed = copy.deepcopy(data)
        changed["context"][name] = "changed"
        assert p.sample(changed, "source")["snapshot"] != before
    assert p.sample(data, "new-source")["snapshot"] != before


def test_evaluation_hash_includes_context():
    page = {"turns": [], "meta": {}}
    one = agent_evaluation.summarize({"session_id": "1", "agent": "codex", "repo": "one"}, page)
    two = agent_evaluation.summarize({"session_id": "1", "agent": "codex", "repo": "two"}, page)
    assert one["snapshot"] != two["snapshot"]


def test_new_tool_reference_changes_version_without_leaking_it():
    data = report()
    first = p.sample(data, "source")
    data["evidence"]["tools"] = [{"tool_id": "private-new-id"}]
    second = p.sample(data, "source")
    assert first["snapshot"] != second["snapshot"]
    assert "private-new-id" not in str(second)


def test_automatic_tick_records_only_hypothesis_and_revalidates_activity(monkeypatch):
    import optimization_scheduler as s
    checks = []
    observed = []
    class Budget:
        def status(self):
            return {"blocked": False, "pilot": {"within_window": True}}
        def pilot_eligible(self, reference):
            return True
    monkeypatch.setattr(s.optimization_budget, "Budget", Budget)
    monkeypatch.setattr(s.state, "sessions", {"test": {"session_id": "test", "repo": "p", "state": "termino", "alive": True}})
    data = report()
    data["evidence"]["counts"].update(closed=1, tools=1)
    monkeypatch.setattr(s.agent_evaluation, "evaluate", lambda _: data)
    monkeypatch.setattr(s.experiment, "manifest", lambda: "source")
    monkeypatch.setattr(s.conocimiento, "proyecto", lambda _: {})
    monkeypatch.setattr(s.activity, "cancellation_reason", lambda _: checks.append("activity") or None)
    def decide(evidence, snapshot, before_send):
        before_send()
        return {"choice": "datos_insuficientes", "usage": {"cost": .00002}}
    monkeypatch.setattr(s.jev, "pilot_decide", decide)
    monkeypatch.setattr(s.pilot, "save", lambda *args: "artifact")
    monkeypatch.setattr(s.memory, "record_jev", lambda *args: observed.append(args))
    scheduler = s.Scheduler()
    scheduler.queue.configure(True)
    assert scheduler._pilot_tick()
    assert len(checks) == 2 and len(observed) == 1
    assert "pendiente" in scheduler.reason
    monkeypatch.setattr(s.activity, "cancellation_reason", lambda _: "usuario activo")
    monkeypatch.setattr(s.jev, "pilot_decide", lambda *a: pytest.fail("must not send"))
    assert scheduler._pilot_tick()
    assert len(observed) == 1


def test_activation_reserves_all_time_usage_without_zeroing_history(monkeypatch, tmp_path):
    import io
    import json
    import os

    import jev
    import jev_credentials
    import optimization_budget as b
    policy = {"round": "test", "owner_pc": "owner", "limit_usd": "2",
              "prior": [{"id": "jev-initial-http400", "cost_usd": None, "source": "HTTP400"}]}
    budget = b.Budget(policy, "owner")
    monkeypatch.setattr(p.optimization_budget, "Budget", lambda: budget)
    credential = tmp_path / "credential"
    credential.write_text("synthetic")
    os.utime(credential, (1791817500, 1791817500))
    monkeypatch.setattr(jev_credentials, "load", lambda: "synthetic-private-key")
    monkeypatch.setattr(jev_credentials, "path", lambda: credential)
    monkeypatch.setattr(p.optimization_cost, "fresh_jev_quote", lambda: {"maximum_usd": ".002688"})
    monkeypatch.setattr(jev, "_open", lambda *a, **k: io.BytesIO(json.dumps({"data": {
        "usage": .04, "byok_usage": 0, "limit_reset": None}}).encode()))
    status = p.activate()
    assert status["reserved_usd"] == "0.04" and status["unknown_charges"] == 1
    assert status["spent_usd"] == "0" and status["pilot"]["maximum_calls"] == 24
    proofs = list((p.Path(p.state.LIENZO) / "improvements").glob("historical-bound-*.json"))
    proof = json.loads(proofs[0].read_text())
    assert proof["actual_cost_usd"] is None and "synthetic-private-key" not in str(proof)
    os.utime(credential, (1791820000, 1791820000))
    with pytest.raises(ValueError, match="credencial cambió"):
        p.activate()
    assert budget.status()["reserved_usd"] == "0.04"


def pilot_transport(monkeypatch):
    import jev
    import optimization_budget as b
    budget = b.Budget({"round": "transport", "owner_pc": "owner", "limit_usd": "2", "prior": []}, "owner")
    budget.start_pilot()
    monkeypatch.setattr(jev.optimization_budget, "Budget", lambda: budget)
    monkeypatch.setattr(jev.jev_credentials, "load", lambda: "synthetic")
    quote = {"maximum_usd": ".002688", "effective_model": "typesafe/jev-1.13-20260917",
             "source": "primary-test", "provider": {"only": ["typesafe"], "allow_fallbacks": False,
             "max_price": {"prompt": .042, "completion": 0, "request": 0, "image": 0}}}
    monkeypatch.setattr(jev.optimization_cost, "fresh_jev_quote", lambda: quote)
    return budget


def test_activity_after_reserve_cancels_only_unsent_and_can_resume(monkeypatch):
    import jev
    budget = pilot_transport(monkeypatch)
    monkeypatch.setattr(jev, "_open", lambda *a, **k: pytest.fail("zero POST required"))
    count = [0]
    def activity():
        count[0] += 1
        if count[0] == 3:
            raise ValueError("usuario activo")
    with pytest.raises(ValueError, match="usuario activo"):
        jev.pilot_decide({"metrics": {}}, "sample", activity)
    status = budget.status()
    assert not status["blocked"] and status["reserved_usd"] == "0"
    assert status["pilot"]["attempts"] == 0 and status["pilot"]["last_attempt"] is None
    assert budget.pilot_eligible("jev-pilot:sample")


def test_timeout_after_mark_sent_keeps_reserve_and_blocks_retry(monkeypatch):
    import jev
    budget = pilot_transport(monkeypatch)
    def timeout(*a, **k):
        raise TimeoutError()
    monkeypatch.setattr(jev, "_open", timeout)
    with pytest.raises(ValueError, match="no respondio"):
        jev.pilot_decide({"metrics": {}}, "sample")
    assert budget.status()["reserved_usd"] == "0.002688" and budget.status()["blocked"]
    with budget.transaction() as con:
        reservation = con.execute("SELECT id FROM ledger WHERE status='held'").fetchone()[0]
    with pytest.raises(ValueError, match="sin prueba"):
        budget.cancel_unsent(reservation)


def test_real_contract_shape_routes_price_caps_and_settles_cost(monkeypatch):
    import io
    import json

    import jev
    budget = pilot_transport(monkeypatch)
    def response(request, timeout):
        body = json.loads(request.data)
        assert body["provider"]["allow_fallbacks"] is False
        assert body["provider"]["max_price"]["request"] == 0
        assert set(body["questions"]["mejora"]["criteria"]) == set(jev.PILOT_OPTIONS)
        return io.BytesIO(json.dumps({"answers": {"mejora": {"type": "choice", "choice": "datos_insuficientes",
            "probabilities": {k: int(k == "datos_insuficientes") for k in jev.PILOT_OPTIONS}}},
            "model": "typesafe/jev-1.13-20260917", "id": "synthetic-generation",
            "usage": {"cost": .00003, "input_tokens": 714, "output_tokens": 20}}).encode())
    monkeypatch.setattr(jev, "_open", response)
    result = jev.pilot_decide({"metrics": {}}, "sample")
    assert result["maximum_usd"] == ".002688" and not result["budget_exceeded"]
    assert budget.status()["spent_usd"] == "0.00003" and budget.status()["reserved_usd"] == "0"
