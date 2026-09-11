package com.travel.backend.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 * 日行程表实体。
 *
 * <p>对应表 {@code itinerary_day}，每个行程包含 N 个日行程（N = 天数）。</p>
 *
 * <p>在行程生成时预创建空壳（只有 day_no 和 city），
 * 异步生成完成后由 {@link ItineraryAsyncPlanner} 逐日填充 note。</p>
 *
 * @see ItineraryItem
 */
@Data
@TableName("itinerary_day")
public class ItineraryDay {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long itineraryId;
    private Integer dayNo;
    private LocalDate travelDate;
    private String city;
    private String note;
    /** 每日手册元数据（主题、微路线、备选方案、拍照点和实用提醒）。 */
    private String metadataJson;
    /** 稳定的每日生成动作 ID，格式为 day-{itineraryId}-{dayNo}。 */
    private String generationActionId;
    /** 生成参数指纹；同一 actionId 携带不同参数时拒绝执行。 */
    private String generationFingerprint;
    /** PENDING/RUNNING/SUCCEEDED/FAILED/TIMED_OUT_UNKNOWN。 */
    private String generationStatus;
    private String generationError;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    @TableLogic
    private Integer deleted;
}
