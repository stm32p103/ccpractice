class ResolveError(Exception):
    """左辺値を解決できない (変数・メンバがない, 範囲外, 未対応の形式 など)"""
