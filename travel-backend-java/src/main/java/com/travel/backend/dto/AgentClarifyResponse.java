package com.travel.backend.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Data;

import java.util.List;
import java.util.Map;

/** 意图确认响应，对齐 Python ClarifyResponse：{slots, missing, question, ready}。 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class AgentClarifyResponse {

    private Map<String, Object> slots;
    private List<String> missing;
    private String question;
    /** Boolean 而非 boolean：Python 侧缺省 false，Java 侧用 TRUE.equals 兜底。 */
    private Boolean ready;
}
