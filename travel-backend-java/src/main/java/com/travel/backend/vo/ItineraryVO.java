package com.travel.backend.vo;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalTime;
import java.util.List;
import java.util.Map;

@Data
public class ItineraryVO {

    private String schemaVersion = "1.0";
    private Long id;
    private String title;
    private String city;
    private LocalDate startDate;
    private LocalDate endDate;
    private Integer days;
    private Integer stayNights;
    private Integer persons;
    private BigDecimal budget;
    private String preferences;
    private String hotelTier;
    private Integer status;
    private String planNote;
    private String destinationStatus;
    private String qualityStatus;
    private String qualityRuleVersion;
    private java.time.LocalDateTime validatedAt;
    private Integer pendingFactCount;
    private Map<String, Object> qualityReport;
    private List<Map<String, Object>> sources;
    private List<Map<String, Object>> suggestions;
    private List<DayVO> dayList;
    private List<BudgetVO> budgetList;
    private BigDecimal totalAmount;

    @Data
    public static class DayVO {
        private Long dayId;
        private Integer dayNo;
        private LocalDate travelDate;
        private String note;
        private String theme;
        private Map<String, Object> miniRoute;
        private List<Map<String, Object>> backupPlan;
        private List<Map<String, Object>> photoSpots;
        private List<String> practicalNotes;
        private List<TripItemVO> items;
    }

    @Data
    public static class TripItemVO {
        private Long id;
        private String itemType;
        private String poiName;
        private String poiId;
        private String address;
        private BigDecimal latitude;
        private BigDecimal longitude;
        private LocalTime startTime;
        private LocalTime endTime;
        private Integer durationMin;
        private BigDecimal cost;
        private String tag;
        private String remark;
        private String openTime;
        private String image;
        private String imageUrl;
        private String source;
        private java.time.LocalDateTime sourceUpdatedAt;
        private String verificationStatus;
        private String valueKind;
        private String freshnessStatus;
        private String reviewRequirement;
        private String factEvidenceJson;
        private Map<String, Object> factEvidence;
        private String intro;
        private String description;
        private Integer sortNo;
    }

    @Data
    public static class BudgetVO {
        private String category;
        private BigDecimal amount;
        private Integer itemCount;
    }
}
