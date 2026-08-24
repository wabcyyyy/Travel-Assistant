package com.travel.backend.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import lombok.Data;

import java.util.List;

@Data
public class HotelOptionApplyRequest {

    @NotBlank(message = "酒店名称不能为空")
    private String hotelName;

    private String tier;

    @NotBlank(message = "请选择房型")
    private String roomType;

    @NotEmpty(message = "请选择具体入住晚次")
    private List<Integer> dayNos;

    private Long actionMessageId;

    private String baseRevision;
}
