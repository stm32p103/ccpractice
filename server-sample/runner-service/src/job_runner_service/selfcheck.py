"""起動時の自己検査(research.md R17。脅威モデル T-W7・T-W9)。

prod では、不足があれば起動を拒否する。dev では省略する。構成の抜け(ランナー用の構築スクリプトの未実行・誤り)を
起動前に検知するためのもので、規則・権限の設定そのものはしない(低権限のエージェントは管理者権限を持たない)。
OS の問い合わせは、差し替えられる関数(プローブ)にして、試験できるようにする。
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from job_runner_agent.settings import AgentSettings

FIREWALL_RULE_NAME = "JobRunnerToolEgressBlock"
"""ツールのアカウントの外向きの通信を遮断する、Windows ファイアウォールの規則の名前(009 の構築スクリプトが作る)。"""

_BROAD_PRINCIPALS = ("everyone", "builtin\\users", "authenticated users", "nt authority\\authenticated users")
_WRITE_RIGHTS = re.compile(r"\((?:[A-Z,]*[FMW][A-Z,]*)\)")

FirewallProbe = Callable[[str], bool]
AclProbe = Callable[[Path], str]


@dataclass(frozen=True)
class SelfCheckFailure:
    item: str
    reason: str


def default_firewall_probe(rule_name: str) -> bool:
    result = subprocess.run(
        ["netsh", "advfirewall", "firewall", "show", "rule", f"name={rule_name}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return result.returncode == 0 and rule_name.lower() in result.stdout.lower()


def default_acl_probe(path: Path) -> str:
    result = subprocess.run(["icacls", str(path)], capture_output=True, text=True, check=False, timeout=30)
    return result.stdout


def _broadly_writable(acl_text: str) -> bool:
    for line in acl_text.splitlines():
        lowered = line.lower()
        if any(p in lowered for p in _BROAD_PRINCIPALS) and _WRITE_RIGHTS.search(line.upper()):
            return True
    return False


def run_selfcheck(
    settings: AgentSettings,
    *,
    firewall_probe: FirewallProbe = default_firewall_probe,
    acl_probe: AclProbe = default_acl_probe,
) -> list[SelfCheckFailure]:
    """prod の起動前の検査。不足の一覧を返す(空なら通過)。dev は検査しない。"""
    if settings.is_dev:
        return []
    failures: list[SelfCheckFailure] = []
    if settings.firewall_self_check and not firewall_probe(FIREWALL_RULE_NAME):
        failures.append(SelfCheckFailure("firewall", "ツールのアカウントの外向きを遮断する規則がない"))
    for item, path in (("state.dir", Path(settings.state.dir)), ("work.root", Path(settings.work.root))):
        if _broadly_writable(acl_probe(path)):
            failures.append(SelfCheckFailure(item, "全員・Users に書き込みの権限がある"))
    return failures
