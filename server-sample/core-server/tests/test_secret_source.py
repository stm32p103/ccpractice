"""SecretSource の契約(contracts/ports.md「SecretSource」)。環境変数の実装(開発・試験専用)。"""

from __future__ import annotations

import pytest

from job_core_api.secret_source import SecretNotFound
from job_core_server.secret_source_env import EnvSecretSource


def test_returns_the_value_for_a_known_name() -> None:
    assert EnvSecretSource({"DB_SECRET": "s3cret-value"}).get("DB_SECRET") == "s3cret-value"


@pytest.mark.parametrize("environ", [{}, {"OTHER": "x"}, {"DB_SECRET": ""}])
def test_unknown_or_empty_name_raises_without_details(environ: dict[str, str]) -> None:
    with pytest.raises(SecretNotFound) as info:
        EnvSecretSource({**environ, "VISIBLE": "visible-value"}).get("DB_SECRET")
    text = str(info.value) + repr(info.value) + str(info.value.__cause__)
    assert "DB_SECRET" not in text and "visible-value" not in text


def test_values_do_not_appear_in_repr_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    source = EnvSecretSource({"DB_SECRET": "s3cret-value"})
    assert "s3cret-value" not in repr(source) and "s3cret-value" not in str(source)
    with caplog.at_level("DEBUG"):
        source.get("DB_SECRET")
    assert "s3cret-value" not in caplog.text
