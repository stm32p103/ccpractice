"""コメント中の数値表記 (LSB, オフセット) の評価"""
from __future__ import annotations

import ast
import operator
from fractions import Fraction

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def eval_fraction(expr: str) -> Fraction:
    """'1/(128*1000)' '0.1' '-40' を Fraction で評価する (四則演算と括弧のみ, eval は使わない)"""

    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return Fraction(str(n.value))
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        raise ValueError(f"数値として評価できない: {expr!r}")

    return ev(ast.parse(expr.strip(), mode="eval").body)


def try_fraction(expr: str | None) -> Fraction | None:
    """eval_fraction の失敗時に None を返す版 (空文字・None も None)"""
    if not expr:
        return None
    try:
        return eval_fraction(expr)
    except (ValueError, SyntaxError, ZeroDivisionError):
        return None
