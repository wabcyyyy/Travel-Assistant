package com.travel.backend.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.LocalTime;

@Data
@TableName("itinerary_item")
public class ItineraryItem {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long dayId;
    private Long itineraryId;
    private String itemType;
    private String poiName;
    private String poiId;
    private String address;
    private BigDecimal latitude;
    private BigDecimal longitude;
    private LocalTime startTime;
    private LocalTime endTime;
    private Integer durationMin;
    private BigDecimal cost;
    private String tag;
    private String remark;
    private Integer sortNo;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    @TableLogic
    private Integer deleted;
}