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
}