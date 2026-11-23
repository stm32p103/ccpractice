"""組み立て(T035)、エグゼキュータの追加(T063。US5-1)、サービスの雛形(T056)、起動前の自己検査(T074)。"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import pytest

from job_runner_agent.settings import AgentSettings, SettingsError
from job_runner_service.__main__ import main
from job_runner_service.selfcheck import FIREWALL_RULE_NAME, run_selfcheck
from job_runner_service.settings import load_settings
from job_runner_service.wiring import EXECUTOR_TABLE, WiringError, build_context, build_executors
from job_testing.runner_fakes.executors import FakeExecutor, payload
from job_testing.runner_fakes.harness import AgentHarness, base_settings

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "runner-service" / "config"


def prod_raw(tmp: Path) -> dict[str, Any]:
    return {
        "profile": "prod",
        "core": {"url": "https://core.example", "runner_token_secret": "token"},
        "work": {"root": str(tmp / "w")},
        "state": {"dir": str(tmp / "s")},
        "tools": {"py": {"path": "C:\\Python312\\python.exe"}},
        "executors": {"type-a": {"executor": "equipment-check", "tool_ids": ["py"]}},
        "source": {"repository_allowlist": [], "fetcher": "remote"},
        "launcher": {"kind": "logon", "tool_account_secret": "acct"},
    }


# ---------------------------------------------------------------- 組み立て(T035)


def test_unknown_executor_name_is_rejected_at_startup(tmp_path: Path) -> None:
    raw = prod_raw(tmp_path)
    raw["executors"]["type-a"]["executor"] = "no-such-executor"
    with pytest.raises(WiringError) as info:
        build_executors(AgentSettings.from_mapping(raw))
    assert "no-such-executor" not in str(info.value)


def test_prod_rejects_dev_choices_in_settings(tmp_path: Path) -> None:
    for path, value in (("launcher", {"kind": "direct"}), ("core", {"url": "http://x", "runner_token_secret": "t"})):
        raw = prod_raw(tmp_path)
        raw[path] = value
        with pytest.raises(SettingsError):
            AgentSettings.from_mapping(raw)


def test_templates_load_and_are_valid(tmp_path: Path) -> None:
    example = load_settings(CONFIG_DIR / "agent.example.toml")
    assert example.profile == "prod" and example.artifact_store.kind == "disabled"
    assert example.source.repository_allowlist == frozenset()  # 既定は拒否
    dev = load_settings(CONFIG_DIR / "agent.dev.toml")
    assert dev.is_dev and dev.launcher.kind == "direct"


def test_dev_context_builds_and_check_mode_exits_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tomllib

    raw = base_settings(tmp_path)
    raw["executors"] = {"type-a": {"executor": "equipment-check", "tool_ids": ["py"]}}
    monkeypatch.setenv("JOB_RUNNER_TOKEN", "rt_dummy0123456789abcdef")
    raw["core"]["runner_token_secret"] = "JOB_RUNNER_TOKEN"
    context = build_context(AgentSettings.from_mapping(raw))
    assert set(context.executors) == {"type-a"}
    assert context.artifact_store is None and context.secrets == ["rt_dummy0123456789abcdef"]
    asyncio.run(context.client.aclose())
    # --check: 設定ファイルの検証のみ
    config = tmp_path / "agent.toml"
    config.write_text(
        "\n".join(
            [
                'profile = "dev"',
                "[core]",
                'url = "http://127.0.0.1:1"',
                'runner_token_secret = "JOB_RUNNER_TOKEN"',
                "[work]",
                f'root = "{(tmp_path / "w").as_posix()}"'.replace("/", "\\\\"),
                "[state]",
                f'dir = "{(tmp_path / "s").as_posix()}"'.replace("/", "\\\\"),
                "[source]",
                "repository_allowlist = []",
                'fetcher = "remote"',
                "[launcher]",
                'kind = "direct"',
            ]
        ),
        encoding="utf-8",
    )
    assert tomllib.loads(config.read_text(encoding="utf-8"))["profile"] == "dev"
    assert main(["--config", str(config), "--check"]) == 0


def test_check_mode_fails_on_invalid_config_without_echoing_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "bad.toml"
    config.write_text(
        'profile = "prod"\n[core]\nurl = "http://SECRET-HOST"\nrunner_token_secret = "t"\n', encoding="utf-8"
    )
    assert main(["--config", str(config), "--check"]) == 2
    assert "SECRET-HOST" not in capsys.readouterr().err


# ---------------------------------------------------------------- エグゼキュータの追加(T063。US5-1)


def test_us5_1_adding_an_executor_needs_only_a_table_entry_and_config(tmp_path: Path) -> None:
    table = {**EXECUTOR_TABLE, "fake": FakeExecutor}  # 対応表に 1 行足す
    harness_raw = base_settings(tmp_path)
    harness_raw["executors"] = {"type-new": {"executor": "fake", "tool_ids": ["py"]}}  # 設定で対応付ける
    executors = build_executors(AgentSettings.from_mapping(harness_raw), table)
    assert isinstance(executors["type-new"], FakeExecutor)

    async def scenario() -> None:
        h = AgentHarness.create(
            tmp_path, executors=executors, settings_overrides={"executors": harness_raw["executors"]}
        )
        job_id = h.core.enqueue("type-new", payload("echo", "added"))
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "succeeded")
        await h.shutdown()
        assert h.core.log_text(job_id).strip() == "added"

    asyncio.run(scenario())


def test_executor_table_is_plain_code_without_dynamic_loading() -> None:
    sources = [
        p.read_text(encoding="utf-8") for p in (ROOT / "runner-service" / "src" / "job_runner_service").glob("*.py")
    ]
    sources += [
        p.read_text(encoding="utf-8") for p in (ROOT / "runner-agent" / "src" / "job_runner_agent").rglob("*.py")
    ]
    assert not any(re.search(r"\b(importlib|__import__|pkg_resources|entry_points)\b", text) for text in sources)


# ---------------------------------------------------------------- サービスの雛形(T056)


def test_winsw_template_is_safe_and_automatic() -> None:
    text = (ROOT / "runner-service" / "winsw" / "agent.xml.template").read_text(encoding="utf-8")
    assert "<startmode>Automatic</startmode>" in text and "delayedAutoStart" in text
    assert text.count('<onfailure action="restart"') >= 2
    assert "<stoptimeout>" in text and "{{agent_account}}" in text
    assert "password" not in re.sub(r"<!--.*?-->", "", text, flags=re.S).lower()  # 秘密を含めない
    assert "-I -m job_runner_service" in text  # 分離モードで起動する


# ---------------------------------------------------------------- 起動前の自己検査(T074)


def settings_of(tmp: Path, **extra: Any) -> AgentSettings:
    raw = prod_raw(tmp)
    raw.update(extra)
    return AgentSettings.from_mapping(raw)


def test_prod_refuses_to_start_without_firewall_rule(tmp_path: Path) -> None:
    failures = run_selfcheck(settings_of(tmp_path), firewall_probe=lambda name: False, acl_probe=lambda path: "")
    assert [f.item for f in failures] == ["firewall"]
    asked: list[str] = []
    ok = run_selfcheck(
        settings_of(tmp_path), firewall_probe=lambda name: asked.append(name) or True, acl_probe=lambda p: ""
    )
    assert ok == [] and asked == [FIREWALL_RULE_NAME]


def test_prod_refuses_broadly_writable_state_folder(tmp_path: Path) -> None:
    acl = "D:\\runner\\state BUILTIN\\Users:(OI)(CI)(M)\n    NT AUTHORITY\\SYSTEM:(F)\n"
    failures = run_selfcheck(settings_of(tmp_path), firewall_probe=lambda n: True, acl_probe=lambda p: acl)
    assert {f.item for f in failures} == {"state.dir", "work.root"}
    safe = "D:\\x svc-runner-agent:(OI)(CI)(F)\n    BUILTIN\\Users:(RX)\n"
    assert run_selfcheck(settings_of(tmp_path), firewall_probe=lambda n: True, acl_probe=lambda p: safe) == []


def test_dev_skips_selfcheck(tmp_path: Path) -> None:
    dev = AgentSettings.from_mapping(base_settings(tmp_path))
    assert run_selfcheck(dev, firewall_probe=lambda n: False, acl_probe=lambda p: "Everyone:(F)") == []


def test_firewall_check_can_be_disabled_by_setting_only_in_prod_config(tmp_path: Path) -> None:
    s = settings_of(tmp_path, firewall_self_check=False)
    assert run_selfcheck(s, firewall_probe=lambda n: False, acl_probe=lambda p: "") == []
