package com.travel.backend.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

@Data
public class GenerateRequest {

    @NotBlank(message = "目的地不能为空")
    private String city;

    @NotNull(message = "出行天数不能为空")
    @Min(value = 1, message = "天数至少为 1 天")
    @Max(value = 14, message = "天数最多为 14 天")
    private Integer days;

    @Min(value = 1, message = "人数至少为 1 人")
    @Max(value = 20, message = "人数最多为 20 人")
    private Integer persons = 1;

    @Min(value = 0, message = "住宿晚数不能为负数")
    @Max(value = 14, message = "住宿晚数最多为 14 晚")
    private Integer stayNights;

    private LocalDate startDate;
    private LocalDate endDate;

    @Min(value = 0, message = "预算不能为负数")
    private BigDecimal budget;

    private List<String> preferences;

    private String hotelTier;

    private String regionHint;
}
