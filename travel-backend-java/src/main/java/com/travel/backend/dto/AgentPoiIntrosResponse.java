package com.travel.backend.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Data;

import java.util.Map;

/**
 * 景点详细介绍批量生成响应：{intros: {景点名: 介绍文本}}。
 *
 * <p>Python 侧 intros 值均为字符串。</p>
 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class AgentPoiIntrosResponse {

    private Map<String, String> intros;
}
