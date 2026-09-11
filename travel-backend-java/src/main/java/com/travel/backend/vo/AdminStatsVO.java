package com.travel.backend.vo;

import lombok.Data;

/**
 * 后台管理-数据概览统计（纯业务维度；Token/LLM 指标见 /api/admin/agent-metrics）。
 */
@Data
public class AdminStatsVO {

    /** 用户总数（自增 ID 最大值，包含被物理删除的账号） */
    private Long totalUsers;
    /** 正常状态用户数 */
    private Long activeUsers;
    /** 禁用状态用户数 */
    private Long disabledUsers;
    /** 行程总数（未删除） */
    private Long totalItineraries;
    /** 今日新增用户数 */
    private Long todayNewUsers;
    /** 今日新增行程数 */
    private Long todayNewItineraries;
    /** 生成中（草稿）行程数 */
    private Long generatingItineraries;
}
