"""LLM JSON 输出解析的唯一实现（G-1.3 ①，合并原四处重复的最强容错）。

职责：
- parse_llm_json：LLM 输出 → dict。失败抛 LlmJsonError（ValueError 子类，
  存量 `except ValueError` 兜底链不变）；用于失败必须显式处理的调用方
  （如 chat_draft 的「解析失败 → 修复重试」流）。
- parse_llm_json_or_none：同解析，失败返回 None；用于「解析失败即降级」
  的调用方（intent 提炼、research 规划）。

容错策略（原 generators.parse_json / chat_draft.validate._parse_json_object /
intent._parse_json_object / research.reasoning._parse_json 四实现的并集，
只增不减）：
1. 输入任意对象 str 化，空串快速失败（原 intent 独有）；
2. markdown 栅栏剥离：```json 换行头（generators/chat_draft/reasoning）与
   无换行 ```{...}```（两式合并）；
3. 首个 `{` 到末个 `}` 截取（generators/chat_draft；等价于 reasoning 的
   DOTALL 贪婪正则）——比 intent 的整段 loads 更宽容，文本周围混入叙事
   也能救回；
4. json.loads 失败 → LlmJsonError；
5. 结果必须是 dict（intent/chat_draft/reasoning 独有，generators 缺此检查）。

边界归并说明：原 chat_draft 对「缺大括号」「非 dict」与「解码失败」抛不同
异常/文案（分别落入不同降级路径），统一后归并为 LlmJsonError，由
chat_draft 的包装器统一映射为 DecisionJsonError 走修复重试——两条路径的
终点都是降级回复，输出口径不变（INV-2 判据：离线测试 + eval）。

依赖：json；无内部依赖（保持叶子模块，任何层都可安全 import）。
"""

import json


class LlmJsonError(ValueError):
    """LLM 输出不是可用的 JSON 对象（空输出/无大括号/解码失败/非 dict）。"""


def parse_llm_json(raw: object) -> dict:
    text = str(raw or "").strip()
    if not text:
        raise LlmJsonError("LLM 输出为空，无法解析 JSON")

    # markdown 栅栏剥离：先掉「```json」头行（无换行时只掉反引号），再掉收尾栅栏
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text.lstrip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
        if "```" in text:
            text = text.rsplit("```", 1)[0].strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise LlmJsonError("LLM 输出中未找到 JSON 对象")

    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LlmJsonError("LLM 输出 JSON 解码失败") from exc
    if not isinstance(data, dict):
        raise LlmJsonError("LLM 输出不是 JSON 对象")
    return data


def parse_llm_json_or_none(raw: object) -> dict | None:
    try:
        return parse_llm_json(raw)
    except LlmJsonError:
        return None
