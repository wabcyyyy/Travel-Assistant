package com.travel.backend.serviceImpl;

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

@Service
public class AgentServiceImpl implements AgentService {

    private static final Logger log = LoggerFactory.getLogger(AgentServiceImpl.class);

    private final RestTemplate restTemplate;

    @Value("${app.agent.base-url}")
    private String agentBaseUrl;

    public AgentServiceImpl(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    @Override
    public AgentGenerateResponse generate(AgentGenerateRequest request) {
        String url = agentBaseUrl + "/api/agent/v1/generate";
        try {
            ResponseEntity<Result<AgentGenerateResponse>> response = restTemplate.exchange(
                    url, HttpMethod.POST, new HttpEntity<>(request),
                    new ParameterizedTypeReference<Result<AgentGenerateResponse>>() {
                    });
            Result<AgentGenerateResponse> body = response.getBody();
            if (body == null || body.getCode() == null || body.getCode() != Result.CODE_SUCCESS
                    || body.getData() == null) {
                log.error("agent generate returned abnormal result: {}", body);
                throw new BizException(502, "行程生成失败：" + (body == null ? "无响应" : body.getMessage()));
            }
            return body.getData();
        } catch (RestClientException e) {
            log.error("call agent generate failed: {}", e.getMessage());
            throw new BizException(502, "行程生成服务暂不可用，请稍后重试");
        }
    }
}