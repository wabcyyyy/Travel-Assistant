package com.travel.backend.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.travel.backend.dto.AgentButlerNoteRequest;
import com.travel.backend.dto.AgentButlerNoteResponse;
import com.travel.backend.dto.AgentCityGuideRequest;
import com.travel.backend.dto.AgentCityGuideResponse;
import com.travel.backend.dto.AgentClarifyRequest;
import com.travel.backend.dto.AgentClarifyResponse;
import com.travel.backend.dto.AgentGenerateRequest;
import com.travel.backend.dto.AgentGenerateResponse;
import com.travel.backend.dto.AgentPoiIntrosRequest;
import com.travel.backend.dto.AgentPoiIntrosResponse;
import com.travel.backend.dto.AgentPoiNearbyRequest;
import com.travel.backend.dto.AgentPoiNearbyResponse;

import java.util.List;
import java.util.Map;

/**
 * Python Agent 服务调用接口。
 *
 * <p>定义了对 Python FastAPI Agent 的所有远程调用方法，实现类为 {@link com.travel.backend.serviceImpl.AgentServiceImpl}。</p>
 *
 * <p>所有方法均为同步 HTTP 调用；强类型端点直接收发 DTO（wire 层键名与 Python
 * 契约一致），其余端点返回 Jackson JsonNode（由调用方按需转换）。</p>
 *
 * @see com.travel.backend.serviceImpl.AgentServiceImpl
 */
public interface AgentService {

    /** 行程生成（首次）。 */
    AgentGenerateResponse generate(AgentGenerateRequest request);

    /** 意图确认（槽位抽取 + 缺失字段追问）。 */
    AgentClarifyResponse clarify(AgentClarifyRequest request);

    /** 自然语言指令解析为操作列表。 */
    JsonNode editOps(String city, int days, List<Map<String, Object>> plans, String instruction);

    /** 对话编辑（封闭动作集决策）。 */
    JsonNode chatTurn(Map<String, Object> payload);

    /** 城市引导对话。 */
    AgentCityGuideResponse cityGuide(AgentCityGuideRequest request);

    /** 行程上下文构建（一次性检索候选）。 */
    JsonNode planContext(String city, List<String> preferences);

    /**
     * 行程上下文构建（带 itineraryId）：itinerary_id 透传给 Python，使其能在
     * gen:events:{itineraryId} 上发布 research_start/research_done/degraded 事件，
     * 与 Java 端共用同一事件协议（M2-③ AD2）。
     */
    JsonNode planContext(String city, List<String> preferences, Long itineraryId);

    /** 单日生成（逐日流式）。 */
    JsonNode generateDay(Map<String, Object> payload);

    /** AI 管家讲解生成。 */
    AgentButlerNoteResponse butlerNote(AgentButlerNoteRequest request);

    /** 景点详细介绍批量生成。 */
    AgentPoiIntrosResponse poiIntros(AgentPoiIntrosRequest request);

    /** 同城权威 POI 近邻（轻量 GraphRAG 附近推荐）。 */
    AgentPoiNearbyResponse poiNearby(AgentPoiNearbyRequest request);

    /** Agent 运行指标（llm_calls、prompt/completion tokens 等进程内聚合）。 */
    JsonNode metrics();

    /** LLM 用量历史（SQLite 落库）：汇总/场景/模型/趋势/明细。range: 1h|24h|7d|30d */
    JsonNode usage(String range, int limit, int offset);
}