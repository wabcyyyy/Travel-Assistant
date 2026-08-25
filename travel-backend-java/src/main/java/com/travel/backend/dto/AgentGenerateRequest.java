package com.travel.backend.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

@Data
public class AgentGenerateRequest {

    private String city;
    private Integer days;
    private Integer persons;
    private BigDecimal budget;
    private LocalDate startDate;
    private List<String> preferences;
    private String hotelTier;
    private String regionHint;
}