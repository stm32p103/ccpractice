"""SecretSource(T013)。値は repr・例外に出ない。"""

from __future__ import annotations

import sys

import pytest

from job_runner_agent.secret_source import CredentialStoreSecretSource, EnvSecretSource, SecretNotFound, SecretValue


def test_env_source_reads_and_hides_value() -> None:
    source = EnvSecretSource({"NAME": "topsecret"})
    value = source.get("NAME")
    assert value.reveal() == "topsecret"
    assert "topsecret" not in repr(value) and "topsecret" not in str(value)
    assert SecretValue("a") == SecretValue("a") and hash(SecretValue("a")) == hash(SecretValue("a"))


def test_missing_secret_raises_without_value() -> None:
    with pytest.raises(SecretNotFound) as info:
        EnvSecretSource({"OTHER": "topsecret"}).get("NAME")
    assert "topsecret" not in str(info.value) and "NAME" in str(info.value)
    with pytest.raises(SecretNotFound):
        EnvSecretSource({"NAME": ""}).get("NAME")


@pytest.mark.windows
@pytest.mark.skipif(sys.platform != "win32", reason="Windows のみ")
def test_credential_store_unknown_name_is_not_found() -> None:
    with pytest.raises(SecretNotFound):
        CredentialStoreSecretSource().get("job-runner-agent-test-no-such-credential")
