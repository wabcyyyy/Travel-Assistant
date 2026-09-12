package com.travel.backend.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Data;

import java.util.List;

/** 城市引导对话响应：{kind, city, message, suggestions}。 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class AgentCityGuideResponse {

    /** province | city | unclear */
    private String kind;
    private String city;
    private String message;
    private List<AgentCityGuideSuggestion> suggestions;
}
