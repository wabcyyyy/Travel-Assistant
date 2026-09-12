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
    /** 整趟主题标题（M3 叙事契约）；列表卡片主题摘要行数据源，空则前端渲染 muted 文案 */
    private String tripTheme;
    private LocalDateTime createdAt;
}