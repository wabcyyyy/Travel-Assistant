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
    private Integer stayNights;
    private Integer status;
    private String planNote;
    private String suggestionsJson;
    /** 整趟主题标题（M3-③）：来自生成契约 trip_theme，仅 day_no=1 的 generate-day 响应携带。 */
    private String tripTheme;
    /** 显式生成状态机（J3）：GENERATING/PARTIAL/COMPLETED/FAILED。status 1/2/3 面向用户可见语义，
     *  gen_state 面向恢复任务与运维——两者并行承载，避免继续用 planNote 文案 + updatedAt 启发式猜状态。 */
    private String genState;
    /** 本次生成开始时间：由 planDays 启动（含恢复续跑）刷新，配合 updatedAt 判断僵尸任务。 */
    private LocalDateTime genStartedAt;
    /** 本次生成结束时间：finish/fail 落终态时写入，便于排查耗时与卡死。 */
    private LocalDateTime genFinishedAt;
    /** 已自动续跑过一次：恢复任务续跑前置 1、续跑成功后 finish 清 0，防止失败-重生成死循环
     *  （替代旧实现写入 planNote 的 "[已自动续跑一次]" 标记文案）。 */
    private Boolean genResumed;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    @TableLogic
    private Integer deleted;
}
