import copy
import io
import json
import urllib.error

import jev
import pytest


@pytest.fixture
def synthetic_budget(monkeypatch):
    """Contrato de transporte aislado: no autoriza ni llama al proveedor real."""
    class FakeBudget:
        def status(self):
            return {"blocked": False}
        def reserve(self, maximum, reference):
            return "synthetic-reservation"
        def settle(self, reservation, actual):
            return None
    monkeypatch.setattr(jev.optimization_budget, "Budget", FakeBudget)
    monkeypatch.setattr(jev.optimization_cost, "maximum", lambda adapter: ".001")


def valid_response():
    return {"model": "typesafe/jev-1.13", "id": "test-generation", "answers": {
        "mejora": {"type": "choice", "choice": "datos_insuficientes",
                   "probabilities": {key: int(key == "datos_insuficientes") for key in jev.OPTIONS}}},
        "usage": {"input_tokens": 100, "output_tokens": 12, "cost": .0000042}}


def test_choice_preserves_cost_and_does_not_claim_correctness():
    result = jev.parse_response(valid_response())
    assert result["choice"] == "datos_insuficientes"
    assert result["usage"]["cost"] == .0000042
    assert "no valida" in result["note"]


@pytest.mark.parametrize("mutation", [
    lambda d: d["usage"].pop("cost"),
    lambda d: d["usage"].update(cost=float("nan")),
    lambda d: d["answers"]["mejora"].update(choice="rea"),
    lambda d: d["answers"]["mejora"]["probabilities"].update(rtk=1),
    lambda d: d["answers"]["mejora"]["probabilities"].update(rtk=-.1),
    lambda d: d["answers"]["mejora"]["probabilities"].pop("rtk"),
    lambda d: d.update(id=None),
])
def test_invalid_provider_response_is_rejected(mutation):
    data = copy.deepcopy(valid_response())
    mutation(data)
    with pytest.raises(ValueError):
        jev.parse_response(data)


def test_request_is_bounded_and_has_retention_policy():
    body = json.loads(jev.request_body({"counts": {"errors": 2}}))
    assert body["provider"] == {"zdr": True, "data_collection": "deny"}
    assert body["questions"]["mejora"]["criteria"] == jev.OPTIONS
    assert "options" not in body["questions"]["mejora"]
    with pytest.raises(ValueError, match="presupuesto"):
        jev.request_body({"large": "x" * 12000})


def test_transport_success_uses_key_only_in_header(monkeypatch, synthetic_budget):
    monkeypatch.setattr(jev.jev_credentials, "load", lambda: "synthetic-secret")
    calls = []
    def open_request(request, timeout):
        calls.append((request, timeout))
        return io.BytesIO(json.dumps(valid_response()).encode())
    monkeypatch.setattr(jev, "_open", open_request)
    result = jev.decide({"counts": {"errors": 1}})
    assert len(calls) == 1 and calls[0][1] == 12
    assert "synthetic-secret" not in json.dumps(result)
    assert b"synthetic-secret" not in calls[0][0].data


@pytest.mark.parametrize("failure", [TimeoutError(), urllib.error.HTTPError(jev.URL, 401, "secret", {}, None)])
def test_transport_failure_has_no_retry_and_no_provider_payload(monkeypatch, failure, synthetic_budget):
    monkeypatch.setattr(jev.jev_credentials, "load", lambda: "synthetic-secret")
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise failure
    monkeypatch.setattr(jev, "_open", fail)
    with pytest.raises(jev.JevError) as error:
        jev.decide({"counts": {}})
    assert len(calls) == 1 and "synthetic-secret" not in str(error.value)


def test_redirect_is_refused():
    assert jev.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.example") is None
