package com.travel.backend.vo;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

@Data
public class ItinerarySummaryVO {

    private Long id;
    private String title;
    private String city;
    private LocalDate startDate;
    private LocalDate endDate;
    private Integer days;
    private Integer persons;
    private BigDecimal budget;
    private BigDecimal totalAmount;
    private Integer status;
    private LocalDateTime createdAt;
}