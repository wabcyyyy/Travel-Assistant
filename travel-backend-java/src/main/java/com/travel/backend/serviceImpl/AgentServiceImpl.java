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

    @Override
    public AgentGenerateResponse generate(AgentGenerateRequest request) {
        JsonNode node = postForNode("/api/agent/v1/generate", request, "行程生成服务暂不可用，请稍后重试");
        return objectMapper.convertValue(node, AgentGenerateResponse.class);
    }

    @Override
    public JsonNode clarify(String message, Map<String, Object> slots) {
        Map<String, Object> body = Map.of("message", message, "slots", slots == null ? Map.of() : slots);
        JsonNode node = postForNode("/api/agent/v1/clarify", body, "意图解析服务暂不可用");
        return node;
    }

    @Override
    public JsonNode editOps(String city, int days, List<Map<String, Object>> plans, String instruction) {
        Map<String, Object> body = Map.of("city", city, "days", days,
                "plans", plans == null ? List.of() : plans, "instruction", instruction);
        return postForNode("/api/agent/v1/edit-ops", body, "指令解析服务暂不可用");
    }

    public JsonNode chatTurn(Map<String, Object> payload) {
        return postForNode("/api/agent/v1/chat-turn", payload, "行程助手暂不可用");
    }

    public JsonNode butlerNote(Map<String, Object> payload) {
        return postForNode("/api/agent/v1/butler-note", payload, "管家讲解生成失败");
    }

    public JsonNode poiIntros(Map<String, Object> payload) {
        return postForNode("/api/agent/v1/poi-intros", payload, "景点介绍生成失败");
    }

    public JsonNode cityGuide(Map<String, Object> payload) {
        return postForNode("/api/agent/v1/city-guide", payload, "城市引导服务暂不可用");
    }

    public JsonNode planContext(String city, List<String> preferences) {
        Map<String, Object> body = Map.of("city", city,
                "preferences", preferences == null ? List.of() : preferences);
        return postForNode("/api/agent/v1/plan-context", body, "行程上下文构建失败");
    }

    public JsonNode generateDay(Map<String, Object> payload) {
        return postForNode("/api/agent/v1/generate-day", payload, "当日行程生成失败");
    }

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
