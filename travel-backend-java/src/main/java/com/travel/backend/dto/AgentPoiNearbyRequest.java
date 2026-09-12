package com.travel.backend.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.Data;

/**
 * 同城权威 POI 近邻请求（POST /api/agent/v1/poi-nearby）。
 *
 * <p>city + name 或 latitude/longitude 二选一；limit/radiusM/category 可选。</p>
 *
 * <p>NON_NULL：不传即无键，与改造前前端 payload 透传（未传键不出现）语义一致。</p>
 */
@Data
@JsonInclude(JsonInclude.Include.NON_NULL)
public class AgentPoiNearbyRequest {

    private String city;
    private String name;
    private Double latitude;
    private Double longitude;
    private Integer limit;
    /** 半径（米），对应 Python 侧 radius_m / radiusM 别名。 */
    private Integer radiusM;
    private String category;
}
