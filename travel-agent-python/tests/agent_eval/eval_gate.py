"""真实 LLM 评测的防倒退门禁（SPEC v2.3 §8 A2）。

门禁语义是「防倒退」，**不是「已达标」**：degraded 是本项目如实呈现的状态
（开放模式 LLM-only 口径下结果通常被标 degraded，`docs/项目介绍.md` 已定性），
**不得**断言成失败——设成失败会逼出口径造假。只在三类硬信号上判红：

1. 出现 failed run（生成链路真的炸了）；
2. Prompt 口径漂移：报告里的 `prompt_version` / 两套开放 Prompt 版本与**本文件的
   期望常量**不一致——改 Prompt 必须同步改这里，逼作者有意识地认账（刻意不 import
   源码常量，否则「改了自动通过」等于没有门禁）；
3. 两遍一致率低于记录基线（现值 16.67% 记为基线，只准升不准降）。

用法（应与「刚跑出来的报告」配对使用；历史/过期报告不适用）：
    uv run python tests/agent_eval/eval_gate.py [报告 json 路径]
默认读 `report/llm_report.json`（nightly 的非主题化 `--limit 3` run 即写它）。
无 LLM_API_KEY 时直接跳过（与 `llm_eval.py` 同一 guard：不冒充、不误红）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.common.config import settings

REPORT_DIR = Path(__file__).with_name("report")
DEFAULT_REPORT = REPORT_DIR / "llm_report.json"

# —— 期望口径常量：改 Prompt 版本时必须同步这里（防静默漂移）——
EXPECTED_PROMPT_VERSION = "workflow-v2-authority-route-20260828"
EXPECTED_OPEN_DAY_PROMPT_VERSION = "v1.1.narrative"
EXPECTED_OPEN_TRIP_PROMPT_VERSION = "v1.1.narrative"

# 一致性基线：记录现值 16.67%（themed_report.md / themed_report.json）。语义 = 防倒退。
CONSISTENCY_BASELINE = 0.1667

# C3.2 深度指标下限（防倒退，非达标线；nightly 真实 LLM 样本仅 3 例，阈值从宽，
# 超过下限的现值也不代表"够好"，只代表不比记录时更差——作者按现值人工认账）。
COORD_VALID_BASELINE = 0.80
DEEPLINK_RESOLVABLE_BASELINE = 0.80
CATEGORY_REASONABLE_BASELINE = 0.95

_DEPTH_BASELINES = {
    "coord_valid_rate": COORD_VALID_BASELINE,
    "deeplink_resolvable_rate": DEEPLINK_RESOLVABLE_BASELINE,
    "category_reasonable_rate": CATEGORY_REASONABLE_BASELINE,
}


def check(report: dict) -> list[str]:
    """返回问题清单（空列表 = 通过）。纯函数，便于离线单测与变异验证。"""
    problems: list[str] = []

    failed = int((report.get("status_counts") or {}).get("failed") or 0)
    if failed:
        problems.append(f"存在 {failed} 个 failed run（硬失败）")

    expected_versions = {
        "prompt_version": EXPECTED_PROMPT_VERSION,
        "open_day_prompt_version": EXPECTED_OPEN_DAY_PROMPT_VERSION,
        "open_trip_prompt_version": EXPECTED_OPEN_TRIP_PROMPT_VERSION,
    }
    for field, expected in expected_versions.items():
        actual = report.get(field)
        if actual != expected:
            problems.append(f"{field} 漂移：期望 {expected!r}，报告 {actual!r}（改 Prompt 请同步门禁常量）")

    rate = report.get("consistency_rate")
    if not isinstance(rate, (int, float)):
        problems.append(f"consistency_rate 缺失或非数值：{rate!r}")
    elif rate < CONSISTENCY_BASELINE:
        problems.append(f"两遍一致率 {rate:.2%} < 基线 {CONSISTENCY_BASELINE:.2%}（防倒退）")

    depth_metrics = report.get("depth_metrics") or {}
    for key, baseline in _DEPTH_BASELINES.items():
        value = depth_metrics.get(key)
        if not isinstance(value, (int, float)):
            problems.append(f"depth_metrics.{key} 缺失或非数值：{value!r}（先重跑 llm_eval.py）")
        elif value < baseline:
            problems.append(f"depth_metrics.{key} {value:.2%} < 基线 {baseline:.2%}（防倒退）")

    # 刻意不检查 degraded：如实呈现是本项目纪律（见模块 docstring）
    return problems


def main(argv: list[str]) -> int:
    if not settings.llm_api_key:
        print("未配置 LLM_API_KEY：评测门禁跳过（不冒充、不误红）")
        return 0
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_REPORT
    if not path.is_file():
        print(f"未找到评测报告：{path}（先跑 llm_eval.py 生成）", file=sys.stderr)
        return 1

    report = json.loads(path.read_text(encoding="utf-8"))
    problems = check(report)
    print(
        f"[eval-gate] {path.name}: status_counts={report.get('status_counts')} "
        f"consistency_rate={report.get('consistency_rate')}"
        f"（degraded 如实呈现，不判失败）"
    )
    if problems:
        print("[eval-gate] 未通过：")
        for problem in problems:
            print("  -", problem)
        return 1
    print("[eval-gate] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
