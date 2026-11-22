"""起動: `uv run python -m job_core_server --config core-server/config/server.dev.toml`。

uvicorn のワーカーは 1 つ(通知の仲介と定期処理がプロセス内にあるため。research.md R9・R20)。
"""

from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

from .settings import ConfigError, load_settings
from .wiring import build_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="job_core_server", description="コア API のサーバーを起動する")
    parser.add_argument("--config", required=True, help="サーバーの設定ファイル(TOML)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        settings = load_settings(args.config)
        app = build_app(settings)
    except ConfigError as error:
        print(f"起動できない: {error}", file=sys.stderr)
        return 2
    # uvicorn のアクセスログはクエリ文字列を含むため使わない(アクセスログは API が、クエリ・認証情報を出さずに記録する)
    uvicorn.run(app, host=settings.host, port=settings.port, workers=1, log_config=None, access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
