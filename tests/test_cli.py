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
