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
import org.springframework.http.HttpMethod;
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

    private JsonNode postForNode(String path, Object body, String unavailableMsg) {
        String url = agentBaseUrl + path;
        try {
            ResponseEntity<Result<JsonNode>> response = restTemplate.exchange(
                    url, HttpMethod.POST, new HttpEntity<>(body),
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