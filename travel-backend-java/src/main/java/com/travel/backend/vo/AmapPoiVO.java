package com.travel.backend.vo;

import lombok.Data;

import java.math.BigDecimal;

@Data
public class AmapPoiVO {

    private String id;
    private String name;
    private String address;
    private BigDecimal latitude;
    private BigDecimal longitude;
    private String type;
    /** 高德评分（biz_ext.rating），可能为空 */
    private String rating;
    /** 人均消费（biz_ext.cost，元），可能为空 */
    private String cost;
}