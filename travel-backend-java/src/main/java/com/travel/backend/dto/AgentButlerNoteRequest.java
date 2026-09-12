package com.travel.backend.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.Data;

import java.util.List;
import java.util.Map;

/**
 * AI 管家讲解生成请求（POST /api/agent/v1/butler-note）。
 *
 * <p>对应 Python 侧 ButlerNoteRequest（WireModel：camelCase 与 snake_case 均可收）。
 * 字段名使用 camelCase，Jackson 序列化后 wire 键为 hotelTier/regionHint 等，
 * Python 侧按 alias 兼容。</p>
 *
 * <p>{@code budget} 使用 Object：非空时为实体原值 {@link java.math.BigDecimal}
 * （序列化为 JSON 数字，保证 Python f-string 渲染与改造前一致），为空时由调用方
 * 塞入空字符串（与改造前 Map.of 的兜底行为一致）。</p>
 *
 * <p>NON_NULL：不传即无键，与 Python 侧 Optional 字段默认值语义对齐。</p>
 */
@Data
@JsonInclude(JsonInclude.Include.NON_NULL)
public class AgentButlerNoteRequest {

    private String city;
    private Integer days;
    private Integer persons;
    /** 偏好（字符串或列表均可，与 Python 契约一致；Java 侧传原始字符串）。 */
    private String preferences;
    private String hotelTier;
    private String regionHint;
    private Object budget;
    private String requirements;
    /** 旅行意图（兜底后的 intent，camel 同名，Python 侧 WireModel alias 可收）。 */
    private String intent;
    /** [{day_no, items:[景点名]}]，键名沿用 Python 契约的 snake_case。 */
    private List<Map<String, Object>> plans;
    private List<Object> validationLog;
}
