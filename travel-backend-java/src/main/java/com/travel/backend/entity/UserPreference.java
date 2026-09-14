package com.travel.backend.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 用户偏好统计表实体。
 *
 * <p>对应表 {@code user_preference}，记录每个用户选择各偏好标签的累计次数。</p>
 *
 * <p>用途：用户下次进入行程生成页面时，自动推荐历史高频偏好（top 5）。</p>
 *
 * <p>唯一键：(user_id, pref_label)，同一用户的同一偏好只有一条记录，count 递增。</p>
 *
 * @see com.travel.backend.service.impl.UserPreferenceService
 */
@Data
@TableName("user_preference")
public class UserPreference {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long userId;
    private String prefLabel;
    private Integer count;
    private String source;
    private java.math.BigDecimal confidence;
    private Integer negative;
    private Integer hardConstraint;
    private LocalDateTime lastSeenAt;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
