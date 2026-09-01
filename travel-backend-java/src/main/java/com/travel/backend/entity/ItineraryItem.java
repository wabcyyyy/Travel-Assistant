package com.travel.backend.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.LocalTime;

/**
 * 行程项表实体。
 *
 * <p>对应表 {@code itinerary_item}，存储行程中的每个具体项（景点/餐饮/酒店/交通）。</p>
 *
 * <p>关键字段：</p>
 * <ul>
 *   <li>{@code itemType} — 类型：attraction(景点) / food(餐饮) / hotel(酒店) / transport(交通)</li>
 *   <li>{@code startTime/endTime} — 时间轴，用于地图展示和冲突检测</li>
 *   <li>{@code latitude/longitude} — 坐标，用于高德地图展示</li>
 *   <li>{@code cost} — 单人单价（景点/餐饮按人，酒店按间/晚）</li>
 *   <li>{@code sortNo} — 拖拽排序序号</li>
 *   <li>{@code intro} — AI 生成的景点详细介绍</li>
 * </ul>
 *
 * @see ItineraryDay
 */
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
    private String intro;
    private Integer sortNo;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    @TableLogic
    private Integer deleted;
}