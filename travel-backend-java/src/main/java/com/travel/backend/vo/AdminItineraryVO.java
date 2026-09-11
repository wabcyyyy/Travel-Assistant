package com.travel.backend.vo;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 * 后台管理-行程列表条目。
 */
@Data
public class AdminItineraryVO {

    private Long id;
    private Long userId;
    private String title;
    private String city;
    private LocalDate startDate;
    private LocalDate endDate;
    private Integer days;
    private Integer persons;
    private BigDecimal budget;
    /** 1-草稿(生成中) 2-已生成 3-已取消 */
    private Integer status;
    private LocalDateTime createdAt;
}
