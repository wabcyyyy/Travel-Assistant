package com.travel.backend.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 * 行程主表实体。
 *
 * <p>对应表 {@code itinerary_main}，存储行程的基本信息（城市/天数/人数/预算/偏好）和状态。</p>
 *
 * <p>状态流转：1=草稿(生成中) → 2=已生成 → 3=已取消</p>
 *
 * <p>异步生成时先建壳（status=1），逐日生成完成后设 status=2。
 * 不能加 @Transactional——异步线程必须在壳数据提交后才启动。</p>
 *
 * @see com.travel.backend.mapper.ItineraryMainMapper
 */
@Data
@TableName("itinerary_main")
public class ItineraryMain {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long userId;
    private String title;
    private String city;
    private LocalDate startDate;
    private LocalDate endDate;
    private Integer days;
    private Integer persons;
    private BigDecimal budget;
    private String preferences;
    private String hotelTier;
    private Integer status;
    private String planNote;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    @TableLogic
    private Integer deleted;
}
