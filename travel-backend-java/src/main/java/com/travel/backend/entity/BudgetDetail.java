package com.travel.backend.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 预算明细表实体。
 *
 * <p>对应表 {@code budget_detail}，按分类（门票/餐饮/酒店/交通）汇总预算。</p>
 *
 * <p>每次行程项变更后由 {@link com.travel.backend.service.BudgetEngine} 重新计算。</p>
 *
 * @see com.travel.backend.service.BudgetEngine
 */
@Data
@TableName("budget_detail")
public class BudgetDetail {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long itineraryId;
    private Long dayId;
    private String category;
    private BigDecimal amount;
    private Integer itemCount;
    private String remark;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    @TableLogic
    private Integer deleted;
}