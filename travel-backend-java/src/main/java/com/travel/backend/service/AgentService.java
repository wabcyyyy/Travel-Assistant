package com.travel.backend.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.travel.backend.dto.AgentGenerateRequest;
import com.travel.backend.dto.AgentGenerateResponse;

import java.util.List;
import java.util.Map;

/**
 * Python Agent 服务调用接口。
 *
 * <p>定义了对 Python FastAPI Agent 的所有远程调用方法，实现类为 {@link com.travel.backend.serviceImpl.AgentServiceImpl}。</p>
 *
 * <p>所有方法均为同步 HTTP 调用，返回值统一为 Jackson JsonNode（由调用方按需转换）。</p>
 *
 * @see com.travel.backend.serviceImpl.AgentServiceImpl
 */
public interface AgentService {

    /** 行程生成（首次）。 */
    AgentGenerateResponse generate(AgentGenerateRequest request);

    /** 意图确认（槽位抽取 + 缺失字段追问）。 */
    JsonNode clarify(String message, Map<String, Object> slots);

    /** 自然语言指令解析为操作列表。 */
    JsonNode editOps(String city, int days, List<Map<String, Object>> plans, String instruction);

    /** 对话编辑（封闭动作集决策）。 */
    JsonNode chatTurn(Map<String, Object> payload);

    /** 城市引导对话。 */
    JsonNode cityGuide(Map<String, Object> payload);

    /** 行程上下文构建（一次性检索候选）。 */
    JsonNode planContext(String city, List<String> preferences);

    /** 单日生成（逐日流式）。 */
    JsonNode generateDay(Map<String, Object> payload);

    /** AI 管家讲解生成。 */
    JsonNode butlerNote(Map<String, Object> payload);

    /** 景点详细介绍批量生成。 */
    JsonNode poiIntros(Map<String, Object> payload);
}