package com.travel.backend.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import tools.jackson.databind.JsonNode;
import com.travel.backend.vo.AdminItineraryVO;
import com.travel.backend.vo.AdminStatsVO;
import com.travel.backend.vo.AdminUserVO;

import java.util.Map;

/**
 * 后台管理服务：数据统计、用户管理与行程管理。
 */
public interface AdminService {

    AdminStatsVO stats();

    Page<AdminUserVO> pageUsers(int page, int size, String keyword);

    void updateStatus(Long id, Integer status, String operatorUsername);

    void deleteUser(Long id, String operatorUsername);

    Page<AdminItineraryVO> pageItineraries(int page, int size, String keyword, Integer status, Long userId);

    void deleteItinerary(Long id);

    /** Agent 运行指标（失败/指标不可用时降级，页面仍可展示）。 */
    Map<String, Object> agentMetrics();

    /** LLM 用量历史（透传 Agent，不可用时降级为零值结构）。 */
    JsonNode llmUsage(String range, int limit, int offset);
}
