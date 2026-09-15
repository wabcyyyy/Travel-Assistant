"""Agent 上下文记忆：请求内 WorkingMemory + 会话对话滑窗。

定位（见 docs/compose/spec/agent-capability-audit.md）：
- WorkingMemory：一次生成内的 used_names / chosen_hotel / feedback；
- DialogueWindow：chat 路径对 history 的截断与消息格式化；
- **不**做长期向量记忆；行程级状态以 Java DB 为真相源。
"""

from app.agent.memory.dialogue import dialogue_messages, recent_turns
from app.agent.memory.working import WorkingMemory

__all__ = ["WorkingMemory", "dialogue_messages", "recent_turns"]
