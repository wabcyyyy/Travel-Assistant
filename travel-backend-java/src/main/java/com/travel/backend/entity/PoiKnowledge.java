package com.travel.backend.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;

@Data
@TableName("poi_knowledge")
public class PoiKnowledge {

    @TableId(type = IdType.AUTO)
    private Long id;
    private String city;
    private String name;
    private String category;
    private String address;
    private BigDecimal latitude;
    private BigDecimal longitude;
    private BigDecimal ticketPrice;
    private Integer durationMin;
    private String openTime;
    private String tags;
    private BigDecimal rating;
    private String description;
}