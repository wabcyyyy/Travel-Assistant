package com.travel.backend.service;

import tools.jackson.databind.JsonNode;
import com.travel.backend.dto.AgentButlerNoteRequest;
import com.travel.backend.dto.AgentButlerNoteResponse;
import com.travel.backend.dto.AgentCityGuideRequest;
import com.travel.backend.dto.AgentCityGuideResponse;
import com.travel.backend.dto.AgentClarifyRequest;
import com.travel.backend.dto.AgentClarifyResponse;
import com.travel.backend.dto.AgentGenerateResponse;
import com.travel.backend.dto.AgentPoiIntrosRequest;
import com.travel.backend.dto.AgentPoiIntrosResponse;
import com.travel.backend.dto.AgentPoiNearbyRequest;
import com.travel.backend.dto.AgentPoiNearbyResponse;

import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

/**
 * Python Agent 服务调用接口。
 *
 * <p>定义了对 Python FastAPI Agent 的所有远程调用方法，实现类为 {@link com.travel.backend.service.impl.AgentServiceImpl}。</p>
 *
 * <p>所有方法均为同步 HTTP 调用；强类型端点直接收发 DTO（wire 层键名与 Python
 * 契约一致），其余端点返回 Jackson JsonNode（由调用方按需转换）。</p>
 *
 * @see com.travel.backend.service.impl.AgentServiceImpl
 */
public interface AgentService {

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

    /**
     * 整段流式生成（POST /api/agent/v1/generate-stream）：响应为 JSON Lines，
     * 每行一个事件（start / day / day_patch / suggestions / done / error），
     * 逐行回调 {@code onLine}；调用方据事件逐天落库。HTTP/解析失败抛 BizException。
     */
    void generateTripStream(Map<String, Object> payload, Consumer<JsonNode> onLine);

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