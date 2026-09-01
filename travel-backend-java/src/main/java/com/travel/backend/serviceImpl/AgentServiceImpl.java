package com.travel.backend.serviceImpl;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.travel.backend.common.BizException;
import com.travel.backend.common.Result;
import com.travel.backend.dto.AgentGenerateRequest;
import com.travel.backend.dto.AgentGenerateResponse;
import com.travel.backend.service.AgentService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import java.util.List;
import java.util.Map;

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
 * <p>所有调用均为同步 HTTP POST，使用 Spring RestTemplate。</p>
 *
 * @see com.travel.backend.service.AgentService
 */
@Service
public class AgentServiceImpl implements AgentService {

    private static final Logger log = LoggerFactory.getLogger(AgentServiceImpl.class);

    private final RestTemplate restTemplate;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Value("${app.agent.base-url}")
    private String agentBaseUrl;

    @Value("${app.agent.internal-token:}")
    private String agentInternalToken;

    public AgentServiceImpl(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    /**
     * 调用 Agent 生成完整行程（首次生成，返回全部天数的计划）。
     *
     * @param request 包含 city/days/persons/preferences 等生成参数
     * @return 解析后的行程响应（含 daily_plans + budget_estimate）
     */
    @Override
    public AgentGenerateResponse generate(AgentGenerateRequest request) {
        JsonNode node = postForNode("/api/agent/v1/generate", request, "行程生成服务暂不可用，请稍后重试");
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
        return postForNode("/api/agent/v1/generate-day", payload, "当日行程生成失败");
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
        String url = agentBaseUrl + path;
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            if (agentInternalToken != null && !agentInternalToken.isBlank()) {
                headers.set("X-Agent-Token", agentInternalToken);
            }
            ResponseEntity<Result<JsonNode>> response = restTemplate.exchange(
                    url, HttpMethod.POST, new HttpEntity<>(body, headers),
                    new ParameterizedTypeReference<Result<JsonNode>>() {
                    });
            Result<JsonNode> result = response.getBody();
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
    }
}
