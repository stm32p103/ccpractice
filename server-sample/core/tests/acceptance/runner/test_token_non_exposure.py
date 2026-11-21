"""トークンの非露出の property-based テスト(spec SC-008。research.md R15-4)。

ランダムな操作の列を実行し、発行以外のすべてのユースケースの戻り値・監査記録・例外のメッセージを直列化して、
発行したトークンの値とそのハッシュが現れないことを確かめる(発行の戻り値も repr では値を出さない)。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from job_core.shared.errors import JobCoreError

from .conftest import RunnerEnv, make_env

OPERATIONS = [
    "create",
    "register",
    "heartbeat",
    "request",
    "fault",
    "recover",
    "maintenance_set",
    "maintenance_clear",
    "reissue",
    "revoke",
    "delete",
    "authenticate_old",
    "authenticate_bad",
    "sweep",
    "advance",
    "submit",
    "clear_fault",
    "list",
    "history",
    "audit",
]

free_text = st.text(min_size=1, max_size=30).filter(lambda s: s.strip() != "")


def serialize(value: Any) -> str:
    return repr(value)


def serialize_error(error: BaseException) -> str:
    details = error.details if isinstance(error, JobCoreError) else {}
    return f"{type(error).__name__}|{error}|{error!r}|{details!r}|{error.args!r}"


@settings(max_examples=80, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(st.tuples(st.sampled_from(OPERATIONS), free_text), min_size=1, max_size=25))
def test_token_value_and_hash_never_appear_outside_issuance(steps: list[tuple[str, str]]) -> None:
    env = make_env()
    tokens: list[str] = []
    outputs: list[str] = []
    state: dict[str, Any] = {"runner": None, "old_tokens": []}

    def current() -> Any:
        return state["runner"]

    def record(value: Any) -> None:
        outputs.append(serialize(value))

    def do_create(text: str) -> None:
        created = env.core.create_runner(env.admin, name=text)
        tokens.append(created.token.value)
        record(created)
        principal = env.core.authenticate_runner(created.token.value)
        state["runner"] = (created.runner_id, principal)

    def need(action: Callable[[str, Any], Any]) -> Callable[[str], None]:
        def run(text: str) -> None:
            if current() is None:
                do_create(f"auto-{len(tokens)}")
            runner_id, principal = current()
            record(action(text, (runner_id, principal)))

        return run

    handlers: dict[str, Callable[[str], None]] = {
        "create": do_create,
        "register": need(
            lambda t, r: env.core.register_runner(r[1], runner_id=r[0], capabilities={"k1": t[:20], "set1": [t[:5]]})
        ),
        "heartbeat": need(lambda t, r: env.core.heartbeat(r[1], runner_id=r[0])),
        "request": need(lambda t, r: env.core.request_job(r[1], runner_id=r[0])),
        "fault": need(lambda t, r: env.core.report_fault(r[1], runner_id=r[0], description=t)),
        "recover": need(lambda t, r: env.core.report_recovered(r[1], runner_id=r[0])),
        "maintenance_set": need(lambda t, r: env.core.set_maintenance(env.admin, runner_id=r[0], reason=t)),
        "maintenance_clear": need(lambda t, r: env.core.clear_maintenance(env.admin, runner_id=r[0], reason=t)),
        "reissue": need(lambda t, r: _reissue(env, r[0], tokens, state, t)),
        "revoke": need(lambda t, r: env.core.revoke_token(env.admin, runner_id=r[0], reason=t)),
        "delete": need(lambda t, r: env.core.delete_runner(env.admin, runner_id=r[0], reason=t)),
        "authenticate_old": lambda t: record(env.core.authenticate_runner(tokens[0] if tokens else t)),
        "authenticate_bad": lambda t: record(env.core.authenticate_runner("rt_" + t)),
        "sweep": lambda t: record(env.core.sweep_runners(env.sweeper)),
        "advance": lambda t: env.advance(40),
        "submit": lambda t: record(env.submit()),
        "clear_fault": need(lambda t, r: env.core.clear_fault(env.admin, runner_id=r[0], reason=t)),
        "list": lambda t: record(env.core.list_runners(env.viewer)),
        "history": need(lambda t, r: env.core.get_runner_history(env.viewer, runner_id=r[0])),
        "audit": lambda t: record(env.core.get_audit_log(env.auditor, limit=1000)),
    }
    for name, text in steps:
        try:
            handlers[name](text)
        except JobCoreError as error:
            outputs.append(serialize_error(error))
        except KeyError:  # 実装に関わらない入力の組み合わせ
            continue

    outputs.append(serialize(env.core.get_audit_log(env.auditor, limit=10000)))
    outputs.append(serialize(env.core.list_runners(env.viewer)))
    text_all = "\n".join(outputs)
    for token in tokens:
        assert token not in text_all
        assert hashlib.sha256(token.encode()).hexdigest() not in text_all
    # 追加の再発行で得たトークンも同様
    for token in state["old_tokens"]:
        assert token not in text_all
        assert hashlib.sha256(token.encode()).hexdigest() not in text_all


def _reissue(env: RunnerEnv, runner_id: str, tokens: list[str], state: dict[str, Any], reason: str) -> Any:
    issued = env.core.reissue_token(env.admin, runner_id=runner_id, reason=reason)
    state["old_tokens"].append(issued.value)
    return issued


def test_scenario_with_known_tokens_leaves_no_trace() -> None:
    """property の補強: 固定のシナリオで、全部の記録を直列化して確認する(失敗時の原因の切り分けが容易)。"""
    env = make_env()
    runner = env.runner("r-a", {"k1": "a"})
    env.submit()
    env.request(runner)
    env.advance(200)
    env.core.sweep_runners(env.sweeper)
    reissued = env.core.reissue_token(env.admin, runner_id=runner.runner_id)
    env.core.revoke_token(env.admin, runner_id=runner.runner_id)
    for bad in (runner.token, reissued.value):
        try:
            env.core.authenticate_runner(bad)
        except JobCoreError as error:
            assert bad not in serialize_error(error)
    dump = serialize(env.core.get_audit_log(env.auditor, limit=10000)) + serialize(env.core.list_runners(env.viewer))
    for token in (runner.token, reissued.value):
        assert token not in dump
        assert hashlib.sha256(token.encode()).hexdigest() not in dump
    env.advance(1)
    assert env.core.clock.peek() > env.core.clock.peek() - timedelta(seconds=1)
