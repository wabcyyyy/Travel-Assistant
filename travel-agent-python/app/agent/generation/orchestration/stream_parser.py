"""整段流式的 JSON 流解析器（G-2.6 自 trip_stream 拆出，蓝图归属）。

职责：把 LLM 的增量 delta 边收边解析，逐块产出已闭合的 day 对象，并收割
trip_theme / suggestions / parse_failures。字符级状态机（字符串/转义/嵌套），
因此必须能容忍切在 JSON 结构中间的块边界。

依赖：json_utils（首个对象截取复用同一容错口径）；无上层依赖。
"""

from __future__ import annotations

import json

from app.agent.core.json_utils import parse_llm_json


class DailyPlansStreamParser:
    """从 LLM 流式输出中增量提取 ``daily_plans`` 数组里的完整日计划对象。

    设计：字符级扫描器在累计缓冲上推进（``_pos`` 之前的已消费），
    字符串字面量内的引号/转义/花括号不参与结构判定：
    - SEEK：定位 ``"daily_plans"`` 键（后随 ``:``，字符串值内的同形
      子串因闭合定界符不符而不会误命中），再等 ``[`` 进入数组；
    - ARRAY：跟踪花括号深度（相对元素起点），深度归零即切出元素
      子串并 ``json.loads`` 成功后产出；
    - 截断（流中断）：已完整闭合的天照常产出，``complete=False``。
    """

    _KEY_PATTERN = '"daily_plans"'
    _STATE_SEEK = 0
    _STATE_AFTER_KEY = 1
    _STATE_ARRAY = 2
    _STATE_DONE = 3

    def __init__(self) -> None:
        self._text = ""
        self._pos = 0
        self._state = self._STATE_SEEK
        self._key_idx = 0
        self._in_string = False
        self._escape = False
        self._depth = 0
        self._elem_start = -1
        self.days: list[dict] = []
        self.parse_failures = 0

    def feed(self, delta: str) -> list[dict]:
        """喂入一段增量，返回本次新解析完成的 day 对象列表。"""
        self._text += delta
        out: list[dict] = []
        text = self._text
        n = len(text)
        i = self._pos
        while i < n:
            ch = text[i]
            if self._state == self._STATE_SEEK:
                if ch == self._KEY_PATTERN[self._key_idx]:
                    self._key_idx += 1
                    if self._key_idx == len(self._KEY_PATTERN):
                        self._key_idx = 0
                        self._state = self._STATE_AFTER_KEY
                else:
                    # 失配回退：从下一个字符重新找键起始（简化处理，键唯一且靠前）
                    self._key_idx = 1 if ch == self._KEY_PATTERN[0] else 0
                i += 1
            elif self._state == self._STATE_AFTER_KEY:
                if ch == ":":
                    self._state = self._STATE_ARRAY
                    self._in_string = False
                    self._escape = False
                    self._depth = 0
                    self._elem_start = -1
                elif ch == self._KEY_PATTERN[0]:
                    # 异常字符（如键后又出现同形串）：重置回 SEEK 重找
                    self._state = self._STATE_SEEK
                    self._key_idx = 1
                i += 1
            elif self._state == self._STATE_ARRAY:
                if self._in_string:
                    if self._escape:
                        self._escape = False
                    elif ch == "\\":
                        self._escape = True
                    elif ch == '"':
                        self._in_string = False
                elif ch == '"':
                    self._in_string = True
                elif ch == "{":
                    if self._depth == 0:
                        self._elem_start = i
                    self._depth += 1
                elif ch == "}":
                    self._depth -= 1
                    if self._depth <= 0:
                        self._depth = 0
                        elem = text[self._elem_start : i + 1]
                        try:
                            day = json.loads(elem)
                        except (json.JSONDecodeError, ValueError):
                            self.parse_failures += 1
                        else:
                            if isinstance(day, dict):
                                self.days.append(day)
                                out.append(day)
                elif ch == "]" and self._depth == 0:
                    self._state = self._STATE_DONE
                i += 1
            else:  # DONE
                break
        self._pos = i
        return out

    def finish(self) -> dict:
        """流结束后做整体收割：complete 标志、trip_theme、suggestions。

        complete 必须以完整文本成功解析为准——数组闭合但整体 JSON
        损坏（如畸形括号）时如实判截断，避免 Java 误判缺天范围。
        """
        complete = False
        trip_theme = None
        suggestions: list[dict] = []
        try:
            data = parse_llm_json(self._text)
        except Exception:
            data = None
        if isinstance(data, dict) and isinstance(data.get("daily_plans"), list):
            complete = True
            raw_theme = data.get("trip_theme")
            trip_theme = raw_theme.strip() if isinstance(raw_theme, str) else None
            raw_suggestions = data.get("suggestions")
            if isinstance(raw_suggestions, list):
                suggestions = [s for s in raw_suggestions if isinstance(s, dict)]
        return {
            "complete": complete,
            "trip_theme": trip_theme,
            "suggestions": suggestions,
        }
