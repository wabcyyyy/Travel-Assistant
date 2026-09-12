package com.travel.backend.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.Data;

import java.util.List;

/** 城市引导对话请求（POST /api/agent/v1/city-guide）。 */
@Data
@JsonInclude(JsonInclude.Include.NON_NULL)
public class AgentCityGuideRequest {

    private String input;
    /** 支持的目的地城市列表（服务端注入，供 Agent 判定 kind）。 */
    private List<String> supported;
    private List<AgentCityGuideMessage> history;
}
