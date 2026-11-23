"""外部ツールの環境ブロックの組み立て(research.md R5。FR-015)。

空から組み立てる。入れるのは (1) 設定 env_allow の固定の値、(2) エージェントが定める変数(TEMP、TMP、JOB_WORK_DIR、
JOB_SIGNAL_DIR)、(3) エグゼキュータが要求し、設定でそのエグゼキュータに許可された名前の値だけ。
親プロセスの環境(os.environ)は読まない。
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

AGENT_VARIABLES = ("TEMP", "TMP", "JOB_WORK_DIR", "JOB_SIGNAL_DIR")
MAX_VALUE_LENGTH = 1024


class EnvRejected(ValueError):
    """許可されていない名前・値。メッセージに値を含めない。"""

    def __init__(self, name: str, reason: str) -> None:
        super().__init__(f"{name}: {reason}")
        self.name = name
        self.reason = reason


def build_environment(
    *,
    env_allow: Mapping[str, str],
    work_dir: str,
    tmp_dir: str,
    signal_dir: str,
    allowed_names: Collection[str] = (),
    extra_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    agent_values = {"TEMP": tmp_dir, "TMP": tmp_dir, "JOB_WORK_DIR": work_dir, "JOB_SIGNAL_DIR": signal_dir}
    env: dict[str, str] = dict(env_allow)
    taken = {name.upper() for name in agent_values}
    for name in env:
        if name.upper() in taken:
            raise EnvRejected(name, "エージェントが定める名前と衝突する")
    env.update(agent_values)
    allowed = {name.upper() for name in allowed_names}
    seen = {name.upper() for name in env}
    for name, value in (extra_env or {}).items():
        if name.upper() not in allowed:
            raise EnvRejected(name, "このエグゼキュータに許可されていない名前")
        if name.upper() in seen:
            raise EnvRejected(name, "既に定められた名前")
        if not isinstance(value, str) or len(value) > MAX_VALUE_LENGTH or "\x00" in value:
            raise EnvRejected(name, "値の形式の違反")
        env[name] = value
        seen.add(name.upper())
    return env
