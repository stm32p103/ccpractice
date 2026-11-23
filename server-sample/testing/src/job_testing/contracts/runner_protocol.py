"""RunnerProtocolContract(004 contracts/runner-protocol.md)。

偽のコア(FakeRunnerCore)と、本物のコア API(build_api())の両方で、同じ呼び出しの列が同じ結果になることを確かめる。
使い方: `proto`(下の ProtocolEnv を返すフィクスチャ)を定義して、このクラスを継承する。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from job_runner_agent.core_client import CoreClient, CoreRejected
from job_runner_protocol.messages import FinishReport, LogChunk
from job_runner_protocol.vocabulary import FailureReason, Outcome, Stream


@dataclass
class ProtocolEnv:
    client: CoreClient
    enqueue: Callable[..., str]
    """ジョブを 1 件、待機列へ入れる(source、revision を指定できる)。ジョブの識別子を返す。"""
    request_abort: Callable[[str], None]
    log_text: Callable[[str], str]
    """コアが保存したログ(seq の順に連結)。"""
    job_state: Callable[[str], str]
    capabilities: dict[str, Any]


def run(coro: Any) -> Any:
    return asyncio.run(coro)


class RunnerProtocolContract:
    def test_registration_and_heartbeat_shape(self, proto: ProtocolEnv) -> None:
        async def go() -> None:
            registered = await proto.client.register(proto.capabilities)
            assert registered.heartbeat_interval_seconds > 0 and registered.abort_requested is False
            assert registered.lease_expires_at is None
            beat = await proto.client.heartbeat()
            assert beat.state == "online" and beat.abort_requested is False

        run(go())

    def test_no_job_then_assignment_with_definition(self, proto: ProtocolEnv) -> None:
        async def go() -> None:
            await proto.client.register(proto.capabilities)
            assert (await proto.client.request_job()).assignment is None
            job_id = proto.enqueue(source="repo-1", revision="abc123")
            result = await proto.client.request_job()
            assignment = result.assignment
            assert assignment is not None and assignment.job_id == job_id
            assert assignment.source == "repo-1" and assignment.revision == "abc123" and assignment.lease_id
            assert assignment.timeout_seconds > 0
            busy = await proto.client.request_job()  # 同時に 1 件(使用中は割り当てなし)
            assert busy.assignment is None

        run(go())

    def test_log_append_is_idempotent_and_conflicts_are_rejected(self, proto: ProtocolEnv) -> None:
        async def go() -> str:
            await proto.client.register(proto.capabilities)
            job_id = proto.enqueue()
            assert (await proto.client.request_job()).assignment is not None
            first = await proto.client.append_log(job_id, LogChunk(0, Stream.STDOUT, "hello "))
            assert first.stored_up_to_seq == 0
            again = await proto.client.append_log(job_id, LogChunk(0, Stream.STDOUT, "hello "))
            assert again.stored_up_to_seq == 0  # 冪等
            second = await proto.client.append_log(job_id, LogChunk(1, Stream.STDERR, "world"))
            assert second.stored_up_to_seq == 1
            with pytest.raises(CoreRejected) as info:
                await proto.client.append_log(job_id, LogChunk(0, Stream.STDOUT, "DIFFERENT"))
            assert info.value.code == "log_seq_conflict" and info.value.status == 409
            return job_id

        job_id = run(go())
        assert proto.log_text(job_id) == "hello world"

    def test_result_report_and_rejection_of_second_report(self, proto: ProtocolEnv) -> None:
        async def go() -> str:
            await proto.client.register(proto.capabilities)
            job_id = proto.enqueue()
            assert (await proto.client.request_job()).assignment is not None
            report = FinishReport(Outcome.FAILED, "要約", 3, FailureReason.TOOL_FAILED)
            done = await proto.client.report_result(job_id, report)
            assert done["state"] == "failed"
            with pytest.raises(CoreRejected) as info:
                await proto.client.report_result(job_id, report)  # 2 回目は確定の拒否
            assert info.value.final and info.value.status == 409
            with pytest.raises(CoreRejected) as late:
                await proto.client.append_log(job_id, LogChunk(0, Stream.STDOUT, "late"))
            assert late.value.code == "target_not_running"
            return job_id

        job_id = run(go())
        assert proto.job_state(job_id) == "failed"

    def test_abort_request_is_signaled_by_heartbeat_and_confirmed_by_stopped(self, proto: ProtocolEnv) -> None:
        async def go() -> str:
            await proto.client.register(proto.capabilities)
            job_id = proto.enqueue()
            assert (await proto.client.request_job()).assignment is not None
            assert (await proto.client.heartbeat()).abort_requested is False
            proto.request_abort(job_id)
            beat = await proto.client.heartbeat()
            assert beat.abort_requested is True and beat.lease_expires_at is not None
            confirmed = await proto.client.confirm_stopped(job_id)
            assert confirmed["state"] == "cancelled"
            assert (await proto.client.heartbeat()).abort_requested is False
            return job_id

        assert proto.job_state(run(go())) == "cancelled"

    def test_stopped_without_abort_is_rejected(self, proto: ProtocolEnv) -> None:
        async def go() -> None:
            await proto.client.register(proto.capabilities)
            job_id = proto.enqueue()
            assert (await proto.client.request_job()).assignment is not None
            with pytest.raises(CoreRejected) as info:
                await proto.client.confirm_stopped(job_id)
            assert info.value.status == 409

        run(go())

    def test_source_credential_for_the_assigned_job(self, proto: ProtocolEnv) -> None:
        async def go() -> None:
            await proto.client.register(proto.capabilities)
            job_id = proto.enqueue(source="repo-1", revision="abc123")
            assert (await proto.client.request_job()).assignment is not None
            a = await proto.client.source_credential(job_id)
            b = await proto.client.source_credential(job_id)
            assert a.kind == "token" and a.secret and b.secret and a.secret != b.secret  # 呼び出しごとに新しい資格
            assert a.secret not in repr(a)

        run(go())

    def test_fault_and_recovery_roundtrip_and_validation(self, proto: ProtocolEnv) -> None:
        async def go() -> None:
            await proto.client.register(proto.capabilities)
            await proto.client.report_fault("short description")
            with pytest.raises(CoreRejected) as info:
                await proto.client.report_fault("x" * 201)
            assert info.value.status == 422
            await proto.client.report_recovered()

        run(go())

    def test_other_jobs_and_unknown_jobs_are_rejected(self, proto: ProtocolEnv) -> None:
        async def go() -> None:
            await proto.client.register(proto.capabilities)
            with pytest.raises(CoreRejected) as info:
                await proto.client.append_log("no-such-job", LogChunk(0, Stream.STDOUT, "x"))
            assert info.value.status == 404 and info.value.final

        run(go())
