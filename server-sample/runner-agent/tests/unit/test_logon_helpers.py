"""LogonLauncher の補助(環境ブロック・コマンドライン・資格の分割)。OS の呼び出しは -m twoaccount で検査する。"""

from __future__ import annotations

import pytest

from job_runner_agent.launcher.logon import build_command_line, build_environment_block, split_account


def test_environment_block_is_sorted_and_double_null_terminated() -> None:
    block = build_environment_block({"b": "2", "A": "1"})
    assert block == "A=1\x00b=2\x00\x00"


@pytest.mark.parametrize("env", [{"": "x"}, {"A=B": "x"}, {"A": "x\x00y"}])
def test_environment_block_rejects_invalid_entries(env: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        build_environment_block(env)


def test_empty_environment_is_just_terminator() -> None:
    assert build_environment_block({}) == "\x00"


def test_command_line_quotes_arguments_without_a_shell() -> None:
    line = build_command_line("C:\\Program Files\tool.exe", ["a b", 'say "hi"', "x&y", "%PATH%"])
    assert line.startswith('"C:\\Program Files\tool.exe"')
    assert '"a b"' in line and "x&y" in line and "%PATH%" in line


def test_split_account() -> None:
    assert split_account(r"DOM\svc-tool:p:a:ss") == ("svc-tool", "DOM", "p:a:ss")
    assert split_account("svc-tool:pw") == ("svc-tool", ".", "pw")
    for bad in ("", "nopassword", ":pw", "user:"):
        with pytest.raises(ValueError) as info:
            split_account(bad)
        assert "pw" not in str(info.value)
