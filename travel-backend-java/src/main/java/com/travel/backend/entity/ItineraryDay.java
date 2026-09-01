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
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    @TableLogic
    private Integer deleted;
}