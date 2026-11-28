"""コメント形式の一覧。

dsr-comment-catalog --write (devtools/comment_catalog.py) で自動生成する。手で編集しない。
形式を追加するときは, このディレクトリにモジュールを置いてから再生成する。
"""

from .bracket import BracketCommentParser
from .key_value import KeyValueCommentParser

ALL_FORMATS = [BracketCommentParser, KeyValueCommentParser]
"""登録済みの形式 (モジュール名順。優先度ではない。優先度は SymbolResolver に渡す順で決める)"""

__all__ = ['ALL_FORMATS', 'BracketCommentParser', 'KeyValueCommentParser']
