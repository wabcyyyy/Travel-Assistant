package com.travel.backend.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Data;

/** AI 管家讲解生成响应：{note}。 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class AgentButlerNoteResponse {

    private String note;
}
