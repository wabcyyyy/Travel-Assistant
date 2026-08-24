package com.travel.backend.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

@Data
public class AgentGenerateResponse {

    private String city;
    private Integer days;
    private String title;
    private List<DailyPlan> dailyPlans;
    private Map<String, BigDecimal> budgetEstimate;
    private String priceNote;

    @Data
    public static class DailyPlan {
        private Integer dayNo;
        private String note;
        private List<Item> items;
    }

    @Data
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
    }
}