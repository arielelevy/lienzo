import agent_evaluation as evaluation


def test_counts_missing_results_partial_scope_and_invalid_durations():
    session = {"session_id": "s1", "agent": "codex", "repo": "test"}
    page = {
        "meta": {"truncated": True},
        "has_more": True,
        "turns": [
            {
                "id": "t1",
                "ended": True,
                "ts_start": "2026-10-12T10:00:00Z",
                "ts_end": "2026-10-12T10:00:05Z",
                "usage": {"total_tokens": 3000},
                "blocks": [
                    {
                        "kind": "tool",
                        "id": "a",
                        "name": "exec_command",
                        "input": {"cmd": "secret-input"},
                        "result": {"text": "secret-output", "is_error": True},
                    },
                    {"kind": "tool", "id": "b", "name": "read", "result": None},
                ],
            },
            {"id": "t2", "ended": False, "ts_start": "bad", "ts_end": "bad", "blocks": []},
            {
                "id": "t3",
                "ended": True,
                "ts_start": "bad",
                "ts_end": "bad",
                "usage": {"total_tokens": 5000},
                "blocks": [],
            },
        ],
    }
    report = evaluation.summarize(session, page)
    assert report["evidence"]["counts"] == {
        "turns": 3,
        "closed": 2,
        "tools": 2,
        "known_results": 1,
        "missing_results": 1,
        "errors": 1,
        "output_characters": 13,
    }
    assert report["durations"] == [{"turn": "t1", "seconds": 5}]
    assert report["evidence"]["partial"] and report["evidence"]["truncated"]
    assert "secret" not in str(report["evidence"])
    assert len(report["usage"]) == 2 and "total" not in report
    assert report["model"] is None and report["version"] is None


def test_open_turn_and_timezone_less_values_are_not_durations():
    assert evaluation._duration({"ended": False}) is None
    assert (
        evaluation._duration({"ended": True, "ts_start": "2026-10-12T10:00:00", "ts_end": "2026-10-12T10:00:05"})
        is None
    )
    assert (
        evaluation._duration({"ended": True, "ts_start": "2026-10-12T10:00:05Z", "ts_end": "2026-10-12T10:00:00Z"})
        is None
    )


def test_missing_transcript_is_unknown_not_zero():
    result = evaluation.summarize({"session_id": "s", "agent": "codex"}, {"turns": [], "note": "sin transcripcion"})
    assert result["evidence"]["unavailable"]
    assert result["evidence"]["counts"]["tools"] is None
