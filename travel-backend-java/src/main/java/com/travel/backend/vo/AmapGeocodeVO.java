package com.travel.backend.vo;

import lombok.Data;

import java.math.BigDecimal;

@Data
public class AmapGeocodeVO {

    private String formattedAddress;
    private BigDecimal latitude;
    private BigDecimal longitude;
    private String level;
}