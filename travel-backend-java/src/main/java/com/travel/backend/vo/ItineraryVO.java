package com.travel.backend.vo;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalTime;
import java.util.List;

@Data
public class ItineraryVO {

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
    private List<DayVO> dayList;
    private List<BudgetVO> budgetList;
    private BigDecimal totalAmount;

    @Data
    public static class DayVO {
        private Long dayId;
        private Integer dayNo;
        private LocalDate travelDate;
        private String note;
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
