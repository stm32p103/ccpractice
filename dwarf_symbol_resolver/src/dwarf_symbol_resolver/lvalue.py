"""左辺値の表現 (AccessPath) と, プリプロセス済みの C 式からの変換 (parse_lvalue)。"""
from __future__ import annotations

import operator
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from .errors import ResolveError


@dataclass
class AccessPath:
    """左辺値を「ルート変数 + メンバ/インデックスの並び」で表したもの。入力形態 (文字列, GUI など) に依存しない。"""

    root: str
    """ルート変数名"""
    scope: tuple[str, ...] = ()
    """ルート変数のスコープ。("tick",) = 関数 tick 内の static, ("sample.c",) = sample.c のファイル内 static,
    ("sample.c", "tick") = 両方を指定"""
    steps: list[tuple[str, object]] = field(default_factory=list)
    """("member", メンバ名) / ("index", 整数) の並び"""

    def __str__(self):
        s = "::".join(self.scope + (self.root,))
        for kind, v in self.steps:
            s += f".{v}" if kind == "member" else f"[{v}]"
        return s

    def designator(self):
        """C の指示付き初期化子 (.a[1].b) 形式。検証用。"""
        return "".join(f".{v}" if k == "member" else f"[{v}]" for k, v in self.steps)


_TOKEN = re.compile(r"\s*(?:(0[xX][0-9a-fA-F]+|\d+)[uUlL]*|([A-Za-z_]\w*)|(<<|>>|[.\[\]()+\-*/%~]))")


def _tokenize(text):
    pos, out = 0, []
    text = text.rstrip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise ResolveError(f"解析できない文字: {text[pos:]!r}")
        num, ident, punct = m.groups()
        if num is not None:
            out.append(("num", int(num, 0)))
        elif ident is not None:
            out.append(("id", ident))
        else:
            out.append(("p", punct))
        pos = m.end()
    out.append(("eof", None))
    return out


class _Parser:
    """postfix := primary ('.' ID | '[' cexpr ']')* ;  primary := ID | '(' postfix ')'"""

    def __init__(self, text, enum_lookup):
        self.toks = _tokenize(text)
        self.i = 0
        self.enum = enum_lookup

    def peek(self, kind=None, val=None):
        k, v = self.toks[self.i]
        return (kind is None or k == kind) and (val is None or v == val)

    def take(self, kind, val=None):
        if not self.peek(kind, val):
            raise ResolveError(f"'{val or kind}' が必要: {self.toks[self.i][1]!r} の位置")
        tok = self.toks[self.i]
        self.i += 1
        return tok[1]

    def lvalue(self):
        if self.peek("p", "("):
            self.take("p", "(")
            path = self.lvalue()
            self.take("p", ")")
        else:
            path = AccessPath(self.take("id"))
        while True:
            if self.peek("p", "."):
                self.take("p", ".")
                path.steps.append(("member", self.take("id")))
            elif self.peek("p", "["):
                self.take("p", "[")
                path.steps.append(("index", self.cexpr()))
                self.take("p", "]")
            else:
                return path

    # 定数式 (インデックス用): | 未対応, + - * / % << >> 単項 - ~ のみ
    _BIN = [({"<<": operator.lshift, ">>": operator.rshift}),
            ({"+": operator.add, "-": operator.sub}),
            ({"*": operator.mul, "/": lambda a, b: int(a / b), "%": operator.mod})]

    def cexpr(self, level=0):
        if level == len(self._BIN):
            return self.unary()
        v = self.cexpr(level + 1)
        while self.peek("p") and self.toks[self.i][1] in self._BIN[level]:
            op = self._BIN[level][self.take("p")]
            v = op(v, self.cexpr(level + 1))
        return v

    def unary(self):
        if self.peek("p", "-"):
            self.take("p")
            return -self.unary()
        if self.peek("p", "~"):
            self.take("p")
            return ~self.unary()
        if self.peek("p", "("):
            self.take("p")
            v = self.cexpr()
            self.take("p", ")")
            return v
        if self.peek("num"):
            return self.take("num")
        name = self.take("id")
        if name == "sizeof":
            raise ResolveError("sizeof は未対応")
        val = self.enum(name)
        if val is None:
            raise ResolveError(f"定数として評価できない識別子: {name}")
        return val


def parse_lvalue(text: str, enum_lookup: Callable[[str], int | None] = lambda n: None) -> AccessPath:
    """プリプロセス済みの C の左辺値式を AccessPath に変換する。

    text        : "st.ar[1].m[4]", "(ch[CH_B]).m[3]", "tick::call_cnt" など。先頭の "scope::" はスコープ指定
    enum_lookup : インデックス式に出てくる識別子 (enum 定数) の値を返す関数
    """
    scope = ()
    if "::" in text:
        *scope, text = text.split("::")
        scope = tuple(s.strip() for s in scope)
    p = _Parser(text, enum_lookup)
    path = p.lvalue()
    p.take("eof")
    path.scope = scope
    return path
