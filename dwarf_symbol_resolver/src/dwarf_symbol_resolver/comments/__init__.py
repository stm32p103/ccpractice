"""宣言のコメントの解析。

- base.py     : CommentParser[T, P] (parse → extract → build), RegexCommentParser, Sample, parse_first
- fields.py   : dataclass 形式の parsed (MonitorFields など)
- formats/    : 形式ごとのパーサ (1 形式 1 モジュール)。formats/__init__.py は自動生成
- catalog.py  : 形式の集約・衝突確認・自己テスト
- extract.py  : ソースからのコメント候補の取り出し
- numbers.py  : 数値表記の評価 (eval_fraction)
"""
from .base import CommentParser, KeyValue, RegexCommentParser, Sample, parse_first
from .extract import extract_comments, scan_comments
from .fields import MonitorFields
from .formats import *  # noqa: F401,F403
from .formats import __all__ as _formats_all
from .numbers import eval_fraction, try_fraction

__all__ = ["CommentParser", "RegexCommentParser", "KeyValue", "Sample", "parse_first",
           "extract_comments", "scan_comments", "MonitorFields", "eval_fraction", "try_fraction",
           *_formats_all]
