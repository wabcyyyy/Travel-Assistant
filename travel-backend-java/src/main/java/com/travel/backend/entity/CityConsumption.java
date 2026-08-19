package com.travel.backend.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;

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