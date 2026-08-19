package com.travel.backend.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalTime;

@Data
public class ItemUpsertRequest {

    private Long dayId;
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
}