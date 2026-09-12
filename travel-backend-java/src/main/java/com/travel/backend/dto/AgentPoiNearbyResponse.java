package com.travel.backend.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Data;

import java.util.List;

/** 同城权威 POI 近邻响应：{items: [...]}。 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class AgentPoiNearbyResponse {

    private List<AgentPoiNearbyItem> items;
}
