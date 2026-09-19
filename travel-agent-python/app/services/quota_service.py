"""按用户的 LLM 花费闸门（R1-9，业务轨：超限抛 ApiError(429)）。

为什么现有的 `app/agent/run_limits.py` 挡不住：那份预算是**按次**的
（一次生成最多 32 次 LLM 调用 / 8 万 token / 120 秒），一个登录用户循环 POST
`/api/itinerary/generate` 就能拿到 N 份"每次都不超预算"的额度 → 无上限烧钱。
全局有界线程池只保证不把进程拖死，不保证单个用户花掉多少。

两个窗口都用 `state_and_sessions.sliding_hit`（与登录/分享限速同一套实现，
Redis 不可用时退进程内窗口）：
- 每分钟：挡脚本式连点；
- 每天：挡"慢慢磨"的滥用，也是给自托管部署的一个可配硬顶。

未做（明确登记）：按用户的**并发**在跑任务数。它需要一个租约/信号量原语
（获取—释放—超时回收），本仓现在只有全局有界池；等那个原语出现再补，
不在这里用「记两次窗口」糊一个假并发闸。
"""

from __future__ import annotations

from app.common.config import settings
from app.common.envelope import ApiError
from app.services import state_and_sessions

_MINUTE_WINDOW_SECONDS = 60
_DAY_WINDOW_SECONDS = 86400


def enforce_llm_budget(user_id: int) -> None:
    """消耗 LLM 的入口在动手之前调它：先记一次，再判分钟窗与日窗。"""
    minute_key = f"quota:llm:min:{user_id}"
    day_key = f"quota:llm:day:{user_id}"
    per_minute = state_and_sessions.sliding_hit(minute_key, _MINUTE_WINDOW_SECONDS)
    if per_minute > settings.user_llm_runs_per_minute:
        raise ApiError(429, "操作过于频繁，请稍后再试")
    per_day = state_and_sessions.sliding_hit(day_key, _DAY_WINDOW_SECONDS)
    if per_day > settings.user_daily_llm_runs:
        raise ApiError(429, "今日 AI 生成次数已用完，请明天再试")
