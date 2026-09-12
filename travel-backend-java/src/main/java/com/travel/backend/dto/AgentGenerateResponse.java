package com.travel.backend.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class AgentGenerateResponse {

    private String schemaVersion;
    private String city;
    private Integer days;
    private String title;
    private List<DailyPlan> dailyPlans;
    private Map<String, BigDecimal> budgetEstimate;
    private List<String> validationLog;
    private String priceNote;
    private String destinationStatus;
    private Map<String, Object> scheduleReport;
    private Map<String, Object> criticReport;
    private Map<String, Object> qualityReport;
    /** Python 生成状态：success | degraded | failed（LLM-only 口径下如实降级）。 */
    private String status;
    /** 降级/失败原因，用于把"部分成功"语义透传到前端，不被静默吞掉。 */
    private String statusReason;
    private List<Map<String, Object>> sources;
    private List<Suggestion> suggestions;

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Suggestion {
        private String poiId;
        private String name;
        private String category;
        private String address;
        private BigDecimal latitude;
        private BigDecimal longitude;
        private String intro;
        private Boolean needReservation;
        private BigDecimal estimatedCost;
        private Boolean used;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class DailyPlan {
        private Integer dayNo;
        private String note;
        private String theme;
        /** 整趟主题标题（M3-③ 契约）：仅 day_no=1 的 generate-day 响应携带，≤40 字。 */
        private String tripTheme;
        /** 整趟主题的备选日方案（M3-③ 契约）：仅 day_no=1 携带，随 metadataJson 落库。 */
        private List<DayOption> dayOptions;
        private Map<String, Object> miniRoute;
        private List<Map<String, Object>> backupPlan;
        private List<Map<String, Object>> photoSpots;
        private List<String> practicalNotes;
        private List<Item> items;
        private List<Suggestion> suggestions;
    }

    /** 备选日方案（M3-③ 契约）：wire 键 label/summary/tradeoff；items 为 Python 侧可选回显，反序列化忽略。 */
    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class DayOption {
        private String label;
        private String summary;
        private String tradeoff;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Item {
        private String itemType;
        private String poiName;
        private String poiId;
        private String address;
        private BigDecimal latitude;
        private BigDecimal longitude;
        private String startTime;
        private String endTime;
        private Integer durationMin;
        private BigDecimal cost;
        private String tag;
        private String remark;
        /** 叙事理由（M3-③ 契约）：attraction 必填，≤120 字，落库到 itinerary_item.why_note。 */
        private String whyThis;
        private String openTime;
        private String image;
        private String source;
        private String sourceUpdatedAt;
        private String verificationStatus;
        private String valueKind;
        private String freshnessStatus;
        private String reviewRequirement;
        private Map<String, Object> factEvidence;
    }
}
