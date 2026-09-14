"""导出跨语言流事件契约 schema（供 Java 运行时校验与 CI 漂移比对）。

用法（travel-agent-python 目录下）：
    uv run python scripts/export_contracts.py

产物：仓库根 contracts/stream_events.schema.json（入库；CI 重跑导出并 git diff 防漂移）。
"""

import json
import sys
from pathlib import Path

# 允许脚本独立运行（sys.path[0] 是 scripts/，需补模块根）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.stream_events import export_schema  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = REPO_ROOT / "contracts" / "stream_events.schema.json"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(export_schema(), ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"exported {OUTPUT}")


if __name__ == "__main__":
    main()
