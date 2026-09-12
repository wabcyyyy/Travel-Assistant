package com.travel.backend.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Data;

/** 城市引导推荐建议（Python 契约：{name, reason}）。 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class AgentCityGuideSuggestion {

    private String name;
    private String reason;
}
