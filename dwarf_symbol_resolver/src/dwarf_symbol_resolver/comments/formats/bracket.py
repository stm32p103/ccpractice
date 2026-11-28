"""形式A: 角括弧の単位 + LSB= / OFS= + 説明"""
from __future__ import annotations

import re

from ..base import RegexCommentParser, Sample
from ..fields import MonitorFields


class BracketCommentParser[T](RegexCommentParser[T, MonitorFields]):
    """`/* [単位] LSB=式 OFS=式 説明 */` または `// [単位] ...`。LSB= / OFS= / 説明は省略可。

    判定の特徴: コメント記号の直後 (空白可) が `[`。
    """

    pattern = re.compile(
        r"(?:/\*|//)\s*\[(?P<unit>[^\]]*)\]\s*"
        r"(?:LSB=(?P<lsb>\S+))?\s*"
        r"(?:OFS=(?P<offset>\S+))?\s*"
        r"(?P<description>.*?)\s*(?:\*/)?", re.S)

    samples = (
        Sample("/* [rpm] LSB=1/(128*1000) OFS=0 エンジン回転数 */",
               MonitorFields("rpm", "1/(128*1000)", "0", "エンジン回転数"), "sample.c"),
        Sample("/* [degC] LSB=0.1 OFS=-40 温度 */", MonitorFields("degC", "0.1", "-40", "温度"), "sample.c"),
        Sample("/* [-] 有効フラグ */", MonitorFields("-", None, None, "有効フラグ"), "sample.c"),
        Sample("// [V] LSB=2 電源電圧", MonitorFields("V", "2", None, "電源電圧")),
    )

    @classmethod
    def to_parsed(cls, m: re.Match[str]) -> MonitorFields | None:
        g = m.groupdict()
        return MonitorFields(unit=g["unit"].strip() or None, lsb=g["lsb"], offset=g["offset"],
                             description=g["description"] or None)
