from pathlib import Path

import pytest

from board_ai_governance.cli import main


EXAMPLES = Path(__file__).parents[1] / "examples"
TEMPLATES = Path(__file__).parents[1] / "templates"


def test_summarize_writes_dashboard(tmp_path, capsys):
    output = tmp_path / "board-summary.md"
    code = main(["summarize", str(EXAMPLES / "ai-risk-register.csv"), "--as-of", "2026-09-12", "--output", str(output)])

    assert code == 0
    assert "High or critical open risks: 1" in capsys.readouterr().out
    assert output.read_text().startswith("# Board AI Risk Dashboard")


def test_starter_template_validates():
    assert main(["summarize", str(TEMPLATES / "ai-risk-register.csv"), "--as-of", "2026-09-12"]) == 0


def test_diff_writes_change_report(tmp_path, capsys):
    output = tmp_path / "change-report.md"
    code = main([
        "diff",
        str(EXAMPLES / "ai-risk-register-previous.csv"),
        str(EXAMPLES / "ai-risk-register.csv"),
        "--as-of", "2026-09-12",
        "--output", str(output),
    ])

    assert code == 0
    assert "Reviews moved later: 2" in capsys.readouterr().out
    assert "## Requires Explanation" in output.read_text()


def test_invalid_register_reports_every_problem_without_a_traceback(tmp_path, capsys):
    path = tmp_path / "risks.csv"
    path.write_text(
        "id,system,owner,decision,impact,likelihood,control_strength,status,next_review\n"
        "AI-1,Model,,Approve,catastrophic,likely,weak,open,2026-12-01\n"
        "AI-2,Model,CTO,Approve,high,likely,weak,open,not-a-date\n"
    )

    code = main(["summarize", str(path), "--as-of", "2026-09-12"])
    err = capsys.readouterr().err

    assert code == 2
    assert err.startswith("error: ")
    assert "row 2: owner is required" in err
    assert "row 2: impact must be one of" in err
    assert "row 3: next_review must be YYYY-MM-DD" in err
    assert "Traceback" not in err


def test_missing_file_is_reported_cleanly(tmp_path, capsys):
    code = main(["summarize", str(tmp_path / "absent.csv")])

    assert code == 2
    assert "error: " in capsys.readouterr().err


def test_unknown_command_exits_with_usage():
    with pytest.raises(SystemExit):
        main(["explode"])


def test_check_without_thresholds_tests_nothing(capsys):
    code = main(["check", str(EXAMPLES / "ai-risk-register.csv"), "--as-of", "2026-09-12"])

    assert code == 0
    assert "No thresholds were set" in capsys.readouterr().out


def test_check_passes_when_the_policy_is_met(capsys):
    code = main(["check", str(EXAMPLES / "ai-risk-register.csv"), "--as-of", "2026-09-12", "--max-critical", "1"])

    assert code == 0
    assert "All 1 rules satisfied" in capsys.readouterr().out


def test_check_exits_one_on_policy_breach(capsys):
    code = main([
        "check", str(EXAMPLES / "ai-risk-register.csv"), "--as-of", "2026-09-12",
        "--max-critical", "0", "--require-evidence-for", "high,critical",
    ])
    out = capsys.readouterr().out

    assert code == 1
    assert "FAIL  critical risks: 1 critical (limit 0)" in out
    assert "AI-002 Recruitment ranking pilot" in out
    assert "2 of 2 rules breached" in out


def test_check_separates_a_breach_from_an_invalid_register(tmp_path, capsys):
    path = tmp_path / "risks.csv"
    path.write_text("id,system,owner\nAI-1,Model,CTO\n")

    assert main(["check", str(path), "--max-critical", "0"]) == 2
    assert "missing required columns" in capsys.readouterr().err


def test_unknown_level_is_refused():
    with pytest.raises(SystemExit):
        main(["check", str(EXAMPLES / "ai-risk-register.csv"), "--require-evidence-for", "catastrophic"])


def test_an_empty_level_list_is_refused_rather_than_silently_disarming_the_gate():
    with pytest.raises(SystemExit):
        main(["check", str(EXAMPLES / "ai-risk-register.csv"), "--require-evidence-for", ""])
