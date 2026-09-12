package com.travel.backend.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.Data;

/** 城市引导对话历史条目（Python 契约：{role, content}）。 */
@Data
@JsonInclude(JsonInclude.Include.NON_NULL)
public class AgentCityGuideMessage {

    private String role;
    private String content;
}
