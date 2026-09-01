package com.travel.backend.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;

/**
 * 城市消费系数表实体。
 *
 * <p>对应表 {@code city_consumption}，存储各城市的人均消费参考数据。</p>
 *
 * <p>用于预算估算和 LLM 生成时的价格参考：</p>
 * <ul>
 *   <li>{@code mealPrice} — 人均每餐参考（元）</li>
 *   <li>{@code transportPrice} — 日均市内交通（元）</li>
 *   <li>{@code hotelPrice} — 单间/晚参考（元）</li>
 * </ul>
 *
 * @see com.travel.backend.service.BudgetEngine
 */
@Data
@TableName("city_consumption")
public class CityConsumption {

    @TableId(type = IdType.AUTO)
    private Long id;
    private String city;
    private String level;
    private BigDecimal mealPrice;
    private BigDecimal transportPrice;
    private BigDecimal hotelPrice;
}