package com.travel.backend.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

@Data
public class GenerateRequest {

    public static final int MAX_TRIP_DAYS = 7;

    @NotBlank(message = "目的地不能为空")
    private String city;

    @NotNull(message = "出行天数不能为空")
    @Min(value = 1, message = "天数至少为 1 天")
    @Max(value = MAX_TRIP_DAYS, message = "天数最多为 7 天")
    private Integer days;

    @Min(value = 1, message = "人数至少为 1 人")
    @Max(value = 20, message = "人数最多为 20 人")
    private Integer persons = 1;

    @Min(value = 0, message = "住宿晚数不能为负数")
    @Max(value = MAX_TRIP_DAYS, message = "住宿晚数最多为 7 晚")
    private Integer stayNights;

    private LocalDate startDate;
    private LocalDate endDate;

    @Min(value = 0, message = "预算不能为负数")
    private BigDecimal budget;

    private List<String> preferences;

    private String hotelTier;

    private String regionHint;

    /** 客户额外要求（自然语言，生成时并入 Agent 规划提示） */
    private String requirements;

    /** 旅行意图（用户一句话，最高优先级生成信号；为空时服务端以 requirements 兜底） */
    @Size(max = 800, message = "旅行意图最多 800 字")
    private String intent;
}
