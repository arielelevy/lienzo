import copy

import optimization_cost
import pytest


def metadata():
    return {
        "data": {
            "id": "typesafe/jev-1.13",
            "endpoints": [
                {
                    "name": optimization_cost.JEV_ENDPOINT,
                    "model_id": "typesafe/jev-1.13",
                    "provider_name": "TypeSafe",
                    "tag": "typesafe",
                    "status": 0,
                    "max_prompt_tokens": 32000,
                    "context_length": 64000,
                    "pricing": {"prompt": "0.000000042", "completion": "0"},
                }
            ],
        }
    }


def test_conservative_quote_does_not_enable_or_reconcile():
    result = optimization_cost.jev_quote(metadata())
    assert result["maximum_usd"] == "0.002688000"
    assert result["enabled"] is False
    assert result["provider"]["max_price"] == {
        "prompt": 0.042,
        "completion": 0,
        "request": 0,
        "image": 0,
    }
    assert result["provider"]["allow_fallbacks"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("context_length", 64001),
        ("context_length", True),
        ("context_length", 1),
        ("max_prompt_tokens", None),
        ("max_prompt_tokens", 32001),
        ("name", "different-version"),
        ("provider_name", "other"),
        ("status", 1),
        ("pricing", {"prompt": "NaN", "completion": "0"}),
        ("pricing", {"prompt": "0.000000043", "completion": "0"}),
        ("pricing", {"prompt": "0.000000042", "completion": "0.1"}),
    ],
)
def test_invalid_quote_blocks(field, value):
    sample = copy.deepcopy(metadata())
    sample["data"]["endpoints"][0][field] = value
    with pytest.raises(ValueError):
        optimization_cost.jev_quote(sample)


def test_multiple_endpoints_block():
    sample = metadata()
    sample["data"]["endpoints"] *= 2
    with pytest.raises(ValueError):
        optimization_cost.jev_quote(sample)
