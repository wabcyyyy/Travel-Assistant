package com.travel.backend.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

/**
 * 近邻 POI 条目。
 *
 * <p>wire 层距离键是 snake_case 带下划线的 {@code _distance_m}（Python 契约的唯一例外），
 * 用 {@code @JsonProperty} 显式映射到 {@code distanceM}。</p>
 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class AgentPoiNearbyItem {

    private String name;
    private String category;
    private Double rating;
    private String address;
    @JsonProperty("_distance_m")
    private Integer distanceM;
}
