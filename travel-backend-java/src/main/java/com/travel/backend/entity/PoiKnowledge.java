package com.travel.backend.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;

/**
 * 景点知识库实体。
 *
 * <p>对应表 {@code poi_knowledge}，存储景点/餐饮/酒店的基础数据（种子数据）。</p>
 *
 * <p>用于 Agent 生成行程时的候选检索（RAG 混合检索：向量召回 + MySQL 关键词兜底）。</p>
 *
 * <p>关键字段：</p>
 * <ul>
 *   <li>{@code category} — 类型：attraction(景点) / food(餐饮) / hotel(酒店)</li>
 *   <li>{@code ticketPrice} — 门票参考价（NULL 表示免费或未知）</li>
 *   <li>{@code durationMin} — 建议游玩时长（分钟）</li>
 *   <li>{@code openTime} — 开放时间文本（如 "09:00-17:00"）</li>
 *   <li>{@code tags} — 偏好标签（逗号分隔，用于 RAG 检索匹配）</li>
 * </ul>
 *
 * @see com.travel.backend.mapper.PoiKnowledgeMapper
 */
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