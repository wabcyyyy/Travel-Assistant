package com.travel.backend.controller;

import com.travel.backend.common.Result;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/test")
public class TestController {

    private static final Logger log = LoggerFactory.getLogger(TestController.class);

    private final RestTemplate restTemplate;

    @Value("${app.agent.base-url}")
    private String agentBaseUrl;

    public TestController(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    @GetMapping("/hello")
    public Result<String> hello() {
        return Result.ok("hello from travel-backend-java");
    }

    @GetMapping("/call-agent")
    public Result<Map<String, Object>> callAgent() {
        String url = agentBaseUrl + "/api/agent/hello";
        try {
            Map<String, Object> body = restTemplate.getForObject(url, Map.class);
            return Result.ok(body);
        } catch (RestClientException e) {
            log.error("call agent service failed: {}", e.getMessage());
            Map<String, Object> fallback = new LinkedHashMap<>();
            fallback.put("code", -1);
            fallback.put("message", "agent service unreachable: " + agentBaseUrl);
            return Result.fail(502, "Agent 服务不可用，请确认 travel-agent-python 已启动");
        }
    }
}