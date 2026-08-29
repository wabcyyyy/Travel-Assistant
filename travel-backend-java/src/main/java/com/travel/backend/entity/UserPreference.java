package com.travel.backend.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("user_preference")
public class UserPreference {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long userId;
    private String prefLabel;
    private Integer count;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
