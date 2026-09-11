package com.travel.backend.serviceImpl;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.travel.backend.common.BizException;
import com.travel.backend.common.Result;
import com.travel.backend.common.SimpleCircuitBreaker;
import com.travel.backend.dto.AgentGenerateRequest;
import com.travel.backend.dto.AgentGenerateResponse;
import com.travel.backend.service.AgentService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Python Agent 服务调用层。
 *
 * <p>职责：封装对 Python FastAPI Agent（:8000）的所有 HTTP 调用，统一处理
 * 鉴权（X-Agent-Token）、响应解包（Result&lt;JsonNode&gt;）和异常转换（RestClientException → BizException(502)）。</p>
 *
 * <p>调用的 Agent 端点一览：</p>
 * <ul>
 *   <li>{@code /api/agent/v1/generate} — 行程生成（首次）</li>
 *   <li>{@code /api/agent/v1/generate-day} — 单日生成（逐日流式）</li>
 *   <li>{@code /api/agent/v1/clarify} — 意图确认（槽位抽取）</li>
 *   <li>{@code /api/agent/v1/chat-turn} — 对话编辑（封闭动作集决策）</li>
 *   <li>{@code /api/agent/v1/plan-context} — 行程上下文构建（一次性检索候选）</li>
 *   <li>{@code /api/agent/v1/butler-note} — AI 管家讲解生成</li>
 *   <li>{@code /api/agent/v1/poi-intros} — 景点详细介绍批量生成</li>
 *   <li>{@code /api/agent/v1/city-guide} — 城市引导对话</li>
 *   <li>{@code /api/agent/v1/edit-ops} — 自然语言指令解析为操作列表</li>
 * </ul>
 *
 * <p>所有调用均为同步 HTTP，使用 Spring {@code RestClient}。</p>
 *
 * @see com.travel.backend.service.AgentService
 */
@Service
public class AgentServiceImpl implements AgentService {

    private static final Logger log = LoggerFactory.getLogger(AgentServiceImpl.class);

    private final RestClient restClient;
    private final SimpleCircuitBreaker circuitBreaker;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Value("${app.agent.base-url}")
    private String agentBaseUrl;

    @Value("${app.agent.internal-token:}")
    private String agentInternalToken;

    public AgentServiceImpl(RestClient restClient, SimpleCircuitBreaker circuitBreaker) {
        this.restClient = restClient;
        this.circuitBreaker = circuitBreaker;
    }

    /**
     * 调用 Agent 生成完整行程（首次生成，返回全部天数的计划）。
     *
     * @param request 包含 city/days/persons/preferences 等生成参数
     * @return 解析后的行程响应（含 daily_plans + budget_estimate）
     */
    @Override
    public AgentGenerateResponse generate(AgentGenerateRequest request) {
        // 整段生成会烧 LLM token，瞬时失败不重试，避免双倍计费
        JsonNode node = postForNode("/api/agent/v1/generate", request,
                "行程生成服务暂不可用，请稍后重试", false);
        return objectMapper.convertValue(node, AgentGenerateResponse.class);
    }

    /**
     * 意图确认：从用户自然语言中抽取槽位（city/days/persons 等），返回缺失字段和追问。
     *
     * @param message 用户最新输入
     * @param slots   已有槽位（前端/Java 逐轮累积）
     * @return 包含 slots/missing/question/ready 的 JSON 节点
     */
    @Override
    public JsonNode clarify(String message, Map<String, Object> slots) {
        Map<String, Object> body = Map.of("message", message, "slots", slots == null ? Map.of() : slots);
        JsonNode node = postForNode("/api/agent/v1/clarify", body, "意图解析服务暂不可用");
        return node;
    }

    /**
     * 自然语言指令解析：将用户的自然语言编辑指令转换为结构化的操作列表（ops）。
     *
     * @param city        行程城市
     * @param days        行程天数
     * @param plans       当前行程计划
     * @param instruction 用户的自然语言编辑指令
     * @return 操作列表 JSON（delete/add/move_day/update_time 等 op）
     */
    @Override
    public JsonNode editOps(String city, int days, List<Map<String, Object>> plans, String instruction) {
        Map<String, Object> body = Map.of("city", city, "days", days,
                "plans", plans == null ? List.of() : plans, "instruction", instruction);
        return postForNode("/api/agent/v1/edit-ops", body, "指令解析服务暂不可用");
    }

    /**
     * 对话编辑：基于当前行程 + 用户消息，由 Agent 返回封闭动作决策（plan_update/rewrite_plan/hotel_proposal 等）。
     *
     * @param payload 包含 city/days/plans/history/message/baseRevision 等完整上下文
     * @return Agent 决策结果（含 reply/plans/hotelOptions/operations/baseRevision）
     */
    public JsonNode chatTurn(Map<String, Object> payload) {
        return postForNode("/api/agent/v1/chat-turn", payload, "行程助手暂不可用");
    }

    /**
     * 生成 AI 管家讲解：基于最终行程生成整体规划思路的自然语言讲解。
     *
     * @param payload 包含 city/days/persons/preferences/plans 等
     * @return 包含 note 字段的 JSON 节点
     */
    public JsonNode butlerNote(Map<String, Object> payload) {
        return postForNode("/api/agent/v1/butler-note", payload, "管家讲解生成失败");
    }

    /**
     * 批量生成景点详细介绍：为行程中的每个景点生成一段介绍文本。
     *
     * @param payload 包含 city 和 names（景点名称列表）
     * @return 包含 intros（景点名 → 介绍文本）的 JSON 节点
     */
    public JsonNode poiIntros(Map<String, Object> payload) {
        return postForNode("/api/agent/v1/poi-intros", payload, "景点介绍生成失败");
    }

    /**
     * 同城权威 POI 近邻：按名称解析坐标或直接传坐标，返回知识库中的真实近邻。
     *
     * @param payload 包含 city，及 name 或 latitude/longitude，可选 limit/radius_m/category
     * @return 包含 items（近邻 POI 列表，含 _distance_m）的 JSON 节点
     */
    @Override
    public JsonNode poiNearby(Map<String, Object> payload) {
        return postForNode("/api/agent/v1/poi-nearby", payload, "附近推荐服务暂不可用");
    }

    /**
     * 城市引导对话：用户不确定去哪时，AI 根据偏好推荐城市。
     *
     * @param payload 包含 input（用户输入）和 history（对话历史）
     * @return 包含 kind/city/message/suggestions 的 JSON 节点
     */
    public JsonNode cityGuide(Map<String, Object> payload) {
        return postForNode("/api/agent/v1/city-guide", payload, "城市引导服务暂不可用");
    }

    /**
     * 构建行程上下文：一次性检索候选景点/餐饮/酒店/消费系数，供后续逐日生成复用。
     *
     * @param city        目的地城市
     * @param preferences 偏好标签列表
     * @return 包含 candidates/foods/hotels/consumption 的上下文 JSON
     */
    public JsonNode planContext(String city, List<String> preferences) {
        Map<String, Object> body = Map.of("city", city,
                "preferences", preferences == null ? List.of() : preferences);
        return postForNode("/api/agent/v1/plan-context", body, "行程上下文构建失败");
    }

    /**
     * 单日生成：逐日流式生成时，为指定天数生成当日行程。
     *
     * @param payload 包含 city/day_no/persons/used_names/chosen_hotel/context 等
     * @return 单日行程 JSON（含 day_no/note/items）
     */
    public JsonNode generateDay(Map<String, Object> payload) {
        // 逐日生成同样烧 LLM token，不自动重试
        return postForNode("/api/agent/v1/generate-day", payload, "当日行程生成失败", false);
    }

    /**
     * 查询 Agent 运行指标（llm_calls、prompt/completion tokens 等，进程内聚合）。
     *
     * @return 指标 JSON 节点，Agent 不可用时抛出 BizException(502)
     */
    @Override
    public JsonNode metrics() {
        return getForNode("/api/agent/v1/metrics", "Agent 指标服务暂不可用");
    }

    @Override
    public JsonNode usage(String range, int limit, int offset) {
        return getForNode("/api/agent/v1/usage?range=" + range + "&limit=" + limit
                + "&offset=" + offset, "Agent 用量服务暂不可用");
    }

    /** GET 请求 Agent 并解包 Result.data；失败抛 BizException(502)。读请求可瞬时重试。 */
    private JsonNode getForNode(String pathWithQuery, String errorMsg) {
        String url = agentBaseUrl + pathWithQuery;
        return circuitBreaker.execute("agent.get:" + pathWithQuery, () -> {
            try {
                Result<JsonNode> result = restClient.get()
                        .uri(url)
                        .headers(h -> {
                            h.setContentType(MediaType.APPLICATION_JSON);
                            if (agentInternalToken != null && !agentInternalToken.isBlank()) {
                                h.set("X-Agent-Token", agentInternalToken);
                            }
                        })
                        .retrieve()
                        .body(new ParameterizedTypeReference<Result<JsonNode>>() {
                        });
                if (result == null || result.getCode() == null || result.getCode() != Result.CODE_SUCCESS
                        || result.getData() == null) {
                    throw new BizException(502, "请求失败：" + (result == null ? "无响应" : result.getMessage()));
                }
                return result.getData();
            } catch (RestClientException e) {
                log.error("call agent {} failed: {}", pathWithQuery, e.getMessage());
                throw new BizException(502, errorMsg);
            }
        }, 2, true);
    }

    /**
     * 统一的 Agent HTTP 调用方法。
     *
     * <p>所有 Agent 端点调用都经过此方法，统一处理：</p>
     * <ol>
     *   <li>拼接完整 URL（agentBaseUrl + path）</li>
     *   <li>设置内部鉴权头（X-Agent-Token）</li>
     *   <li>POST JSON 并解析 Result&lt;JsonNode&gt; 响应</li>
     *   <li>校验响应码，失败时抛出 BizException(502)</li>
     * </ol>
     *
     * @param path           Agent 端点路径（如 /api/agent/v1/generate）
     * @param body           请求体（会被 Jackson 序列化为 JSON）
     * @param unavailableMsg 调用失败时的用户友好提示
     * @return 响应中的 data 字段（JsonNode）
     * @throws BizException 当 Agent 不可用或返回异常响应时
     */
    private JsonNode postForNode(String path, Object body, String unavailableMsg) {
        return postForNode(path, body, unavailableMsg, true);
    }

    /**
     * @param retryOnTransient 瞬时失败是否重试。generate / generate-day 必须 false，
     *                         避免 LLM 重复计费与状态机双写。
     */
    private JsonNode postForNode(String path, Object body, String unavailableMsg, boolean retryOnTransient) {
        String url = agentBaseUrl + path;
        int maxAttempts = retryOnTransient ? 2 : 1;
        return circuitBreaker.execute("agent.post:" + path, () -> {
            try {
                Result<JsonNode> result = restClient.post()
                        .uri(url)
                        .headers(h -> {
                            h.setContentType(MediaType.APPLICATION_JSON);
                            h.set("X-Request-ID", resolveRequestId(body));
                            if (agentInternalToken != null && !agentInternalToken.isBlank()) {
                                h.set("X-Agent-Token", agentInternalToken);
                            }
                        })
                        .body(body)
                        .retrieve()
                        .body(new ParameterizedTypeReference<Result<JsonNode>>() {
                        });
                if (result == null || result.getCode() == null || result.getCode() != Result.CODE_SUCCESS
                        || result.getData() == null) {
                    log.error("agent call {} returned abnormal result: {}", path, result);
                    throw new BizException(502, "请求失败：" + (result == null ? "无响应" : result.getMessage()));
                }
                return result.getData();
            } catch (RestClientException e) {
                log.error("call agent {} failed: {}", path, e.getMessage());
                throw new BizException(502, unavailableMsg);
            }
        }, maxAttempts, retryOnTransient);
    }

    /**
     * 透传入口请求的关联 ID；异步逐日任务没有 Servlet 上下文时优先使用
     * payload 中稳定的 itinerary request_id，保证同一行程的 Trace 可串联。
     */
    private String resolveRequestId(Object body) {
        ServletRequestAttributes attributes =
                (ServletRequestAttributes) RequestContextHolder.getRequestAttributes();
        if (attributes != null) {
            String inbound = attributes.getRequest().getHeader("X-Request-ID");
            if (inbound != null && !inbound.isBlank()) {
                return inbound.length() > 128 ? inbound.substring(0, 128) : inbound;
            }
        }
        if (body instanceof Map<?, ?> map) {
            Object requestId = map.get("request_id");
            if (requestId == null) requestId = map.get("requestId");
            if (requestId != null && !requestId.toString().isBlank()) {
                String value = requestId.toString();
                return value.length() > 128 ? value.substring(0, 128) : value;
            }
        }
        return UUID.randomUUID().toString();
    }
}
