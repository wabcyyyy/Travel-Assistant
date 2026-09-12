package com.travel.backend.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.Data;

import java.util.List;

/** 景点详细介绍批量生成请求（POST /api/agent/v1/poi-intros）。 */
@Data
@JsonInclude(JsonInclude.Include.NON_NULL)
public class AgentPoiIntrosRequest {

    private String city;
    private List<String> names;
    /** 生成意图（M3-③）：与 butlerNote/generate 的 intent 口径一致，未填时由 resolveIntent 以 requirements 兜底。 */
    private String intent;
}
