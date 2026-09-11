package com.travel.backend.dto;

import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import lombok.Data;

import java.util.List;

/** 用户显式偏好、硬约束和负反馈信号。 */
@Data
public class PreferenceSignalRequest {
    private List<String> explicitPreferences;
    private List<String> hardConstraints;
    private List<String> negativePreferences;
    private String source = "explicit";
    @DecimalMin("0.0")
    @DecimalMax("1.0")
    private Double confidence = 1.0;
}
