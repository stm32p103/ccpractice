"""試験用の偽のツール(004 T021)。エージェントが tool_id に登録した python.exe から、このスクリプトを起動する。

用途固有の語を使わない。コマンドは 1 つ目の引数で選ぶ。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)  # type: ignore[union-attr]
    command, args = (argv[0], argv[1:]) if argv else ("echo", [])
    if command == "sleep":
        time.sleep(float(args[0]))
        return 0
    if command == "echo":
        print(" ".join(args))
        return 0
    if command == "args":
        print(json.dumps(args, ensure_ascii=False))
        return 0
    if command == "env":
        print(json.dumps(dict(os.environ), ensure_ascii=False))
        return 0
    if command == "cwd":
        print(os.getcwd())
        return 0
    if command == "lines":
        count, delay = int(args[0]), float(args[1])
        for index in range(count):
            print(f"line-{index}")
            time.sleep(delay)
        return 0
    if command == "err":
        print(" ".join(args), file=sys.stderr)
        return 0
    if command == "exit":
        return int(args[0])
    if command == "spawn-child":
        # 孫のプロセスを起動して、pid をファイルに書き、自分も待つ
        seconds = args[0]
        pid_file = Path(args[1])
        child = subprocess.Popen([sys.executable, __file__, "spawn-grandchild", seconds, str(pid_file) + ".g"])
        pid_file.write_text(str(child.pid))
        print("child-started", flush=True)
        time.sleep(float(seconds))
        return 0
    if command == "spawn-grandchild":
        Path(args[1]).write_text(str(os.getpid()))
        subprocess.Popen([sys.executable, __file__, "sleep", args[0]])  # 孫の孫
        time.sleep(float(args[0]))
        return 0
    if command == "read-secrets":
        # 作業フォルダ外のファイルと環境変数(ダミーの秘密)を読んで、出力と成果物へ書こうとする
        file_path, env_name, out_rel = args
        parts = []
        try:
            parts.append("file=" + Path(file_path).read_text(encoding="utf-8"))
        except OSError:
            parts.append("file=<unreadable>")
        parts.append("env=" + os.environ.get(env_name, "<unset>"))
        text = "\n".join(parts)
        print(text)
        Path(out_rel).parent.mkdir(parents=True, exist_ok=True)
        Path(out_rel).write_text(text, encoding="utf-8")
        return 0
    if command == "cat":
        print(Path(args[0]).read_text(encoding="utf-8"))
        return 0
    if command == "ls":
        print(json.dumps(sorted(str(p.relative_to(args[0])) for p in Path(args[0]).rglob("*"))))
        return 0
    if command == "write-file":
        target = Path(args[0])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(args[1] if len(args) > 1 else "content", encoding="utf-8")
        return 0
    if command == "write-big":
        target = Path(args[0])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * int(args[1]))
        return 0
    if command == "make-link":
        # 作業フォルダ内にリンクを作る(成果物の収集でリンクを辿らないことの検査)
        link, target = Path(args[0]), Path(args[1])
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=False, capture_output=True)
        return 0
    if command == "fault":
        Path(os.environ["JOB_SIGNAL_DIR"], "fault.txt").write_text(" ".join(args), encoding="utf-8")
        return 0
    if command == "recovered":
        Path(os.environ["JOB_SIGNAL_DIR"], "recovered").write_text("", encoding="utf-8")
        return 0
    if command == "print-raw":
        # 引数をそのまま標準出力へ(秘密の形の文字列のマスクの検査)
        sys.stdout.write("\n".join(args) + "\n")
        return 0
    print(f"unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
