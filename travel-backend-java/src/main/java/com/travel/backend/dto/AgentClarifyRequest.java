package com.travel.backend.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.Data;

import java.util.Map;

/** 意图确认（槽位抽取）请求（POST /api/agent/v1/clarify），对齐 Python ClarifyRequest。 */
@Data
@JsonInclude(JsonInclude.Include.NON_NULL)
public class AgentClarifyRequest {

    private String message;
    private Map<String, Object> slots;
}
