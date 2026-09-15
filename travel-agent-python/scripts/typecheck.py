"""pyright 基线 ratchet（G-0.3）：存量报错冻结在 pyright-baseline.txt，只减不增（INV-1）。

用法：
    uv run python scripts/typecheck.py           # 对照基线检查；出现基线外的新报错 → exit 1
    uv run python scripts/typecheck.py --update  # 重新生成基线（修掉存量后用来记录进展）

基线键 = `文件路径:规则:消息`（不含行列号）：格式化/移动代码不会误报"新增"，
只有真正的类型错误（或措辞变化）才会被拦下。修好存量后请跑 --update 让基线只减不增。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "pyright-baseline.txt"


def current_errors() -> list[str]:
    proc = subprocess.run(
        ["uv", "run", "pyright", "--outputjson"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if not proc.stdout.strip():
        print(proc.stderr, file=sys.stderr)
        raise SystemExit("pyright produced no JSON output")
    data = json.loads(proc.stdout)
    keys: list[str] = []
    for diag in data.get("generalDiagnostics", []):
        if diag.get("severity") != "error":
            continue
        file = str(diag.get("file", "")).replace("\\", "/")
        root = str(ROOT).replace("\\", "/")
        if file.lower().startswith(root.lower() + "/"):
            file = file[len(root) + 1 :]
        rule = diag.get("rule") or "no-rule"
        # 消息含多行子诊断：压平换行，保证一个报错 = 基线里一行
        message = " | ".join(str(diag.get("message", "")).splitlines())
        keys.append(f"{file}:{rule}:{message}")
    return sorted(set(keys))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true", help="重新生成基线")
    args = parser.parse_args()

    current = current_errors()
    if args.update:
        BASELINE.write_text("\n".join(current) + ("\n" if current else ""), encoding="utf-8")
        print(f"baseline updated: {len(current)} errors frozen")
        return 0

    baseline = (
        [line for line in BASELINE.read_text(encoding="utf-8").splitlines() if line.strip()]
        if BASELINE.exists()
        else []
    )
    new = [key for key in current if key not in set(baseline)]
    print(f"pyright: {len(current)} errors (baseline {len(baseline)})")
    if new:
        print(f"\nNEW type errors not in baseline ({len(new)}):")
        for key in new:
            print(f"  {key}")
        print("\nfix them; baseline only shrinks (INV-1)")
        return 1
    if len(current) < len(baseline):
        print("progress: fewer errors than baseline — run `--update` to shrink it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
