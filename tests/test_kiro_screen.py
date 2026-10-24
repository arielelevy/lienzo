from lienzo import screen


def test_kiro_permission_has_exact_options_and_command():
    lines = [
        "─" * 50,
        "Read File requires approval",
        "fs_read → C:/work/file.txt",
        "",
        " ❯ Allow",
        "   Always allow",
        "   Deny",
        "   Always deny",
        "─" * 50,
        "esc to close · ↑↓ to navigate · ↵ to select · Tab to edit",
    ]
    d = screen.dialog(lines)
    assert d["teclas"] == "flechas"
    assert d["selected"] == 1
    assert d["question"] == "Read File requires approval"
    assert "C:/work/file.txt" in d["detail"]
    assert [o["text"] for o in d["options"]] == ["Allow", "Always allow", "Deny", "Always deny"]
    assert screen.dialog(lines[:-1]) is None


def test_kiro_input_uses_bottom_prompt_instead_of_previous_answer():
    r = screen.input_area(
        [
            "─" * 50,
            "old answer",
            "─" * 50,
            "Default · auto",
            "",
            "›  ask a question or describe a task ↵",
            "/sessions to resume · /copy to clipboard",
        ]
    )
    assert r["placeholder"] and r["input"] == ""
    r = screen.input_area(["›  Kiro is working · 8s · Type to steer · Ctrl+S to queue"])
    assert r["placeholder"] and r["input"] == ""
    assert "working" in r["status"]


def test_kiro_typed_input_is_preserved():
    r = screen.input_area(["Default · auto", "›  revisar el proyecto", "/sessions to resume · /copy to clipboard"])
    assert r["input"] == "revisar el proyecto"
    assert not r["placeholder"]


def test_kiro_permission_with_changed_selection():
    lines = [
        "─" * 50,
        "Shell requires approval",
        "execute → git status",
        "",
        "   Allow",
        "   Always allow",
        " ❯ Deny",
        "   Always deny",
        "─" * 50,
        "esc to close · ↑↓ to navigate · ↵ to select · Tab to edit",
    ]
    assert screen.dialog(lines)["selected"] == 3
    lines[6] = "   Deny"
    assert screen.dialog(lines) is None


def test_kiro_long_permission_is_detected_without_hidden_title():
    lines = [
        "Get-ChildItem C:/work",
        "",
        " ❯ Allow",
        "   Always allow",
        "   Deny",
        "   Always deny",
        "─" * 50,
        "esc to close · ↑↓ to navigate · ↵ to select · Tab to edit",
    ]
    result = screen.dialog(lines)
    assert result["truncated"]
    assert result["teclas"] == "flechas"
    assert "parcialmente visible" in result["question"]


def test_codex_approval_uses_arrows_and_enter():
    lines = [
        "Would you like to run the following command?",
        "",
        "Reason: run the test",
        "$ node --test test.mjs",
        "",
        "› 1. Yes, proceed (y)",
        "  2. Yes, and don't ask again (p)",
        "  3. No, and tell Codex what to do differently (esc)",
        "",
        "Press enter to confirm or esc to cancel",
    ]
    result = screen.dialog(lines)
    assert result["selected"] == 1
    assert result["teclas"] == "flechas"
    assert "$ node --test test.mjs" in result["detail"]


def test_kiro_2_34_cambio_las_opciones_y_se_sigue_eligiendo_solo_allow_once():
    """kiro-cli 2.34.0 (2026-10-23, opensyync): «Allow once / Deny once / Create allow rule… / Create deny
    rule…». Con las opciones de la 2.33 no se reconocia el dialogo y el auto-aprobar no lo contestaba."""
    from lienzo.agentes import perfil

    lines = [
        "  ,history_store.py,report_export.py,web_api.py | Select-Object Name,Length",
        "─" * 120,
        " Measure sizes of integration-owned files requires approval",
        " shell → Get-ChildItem",
        " opensyync.py,coverage_contract.py,engine_contract.py",
        "",
        " ❯ Allow once",
        "   Deny once",
        "   Create allow rule to approve future similar actions",
        "   Create deny rule to block future similar actions",
        "─" * 120,
        " esc to close · ↑↓ to navigate · ↵ to select · Tab to edit",
    ]
    d = screen.dialog(lines)
    assert d is not None and d["teclas"] == "flechas"
    assert d["question"] == "Measure sizes of integration-owned files requires approval"
    assert [o["text"] for o in d["options"]][:2] == ["Allow once", "Deny once"]
    assert perfil("kiro").permission_option(d) == 1  # «Allow once», nunca la regla permanente
