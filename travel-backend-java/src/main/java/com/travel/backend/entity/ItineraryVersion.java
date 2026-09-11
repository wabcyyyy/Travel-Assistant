package com.travel.backend.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/** 行程可恢复版本的脱敏业务快照。 */
@Data
@TableName("itinerary_version")
public class ItineraryVersion {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long itineraryId;
    private Long userId;
    private Long parentVersionId;
    private Integer versionNo;
    private String operation;
    private String summary;
    private String snapshotJson;
    private LocalDateTime createdAt;
}
