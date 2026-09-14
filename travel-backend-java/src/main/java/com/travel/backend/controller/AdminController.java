package com.travel.backend.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.travel.backend.common.Result;
import com.travel.backend.common.SecurityUtils;
import tools.jackson.databind.JsonNode;
import com.travel.backend.service.AdminService;
import com.travel.backend.vo.AdminItineraryVO;
import com.travel.backend.vo.AdminStatsVO;
import com.travel.backend.vo.AdminUserVO;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 后台管理接口，全部要求 ADMIN 角色（见 SecurityConfig）。
 */
@RestController
@RequestMapping("/api/admin")
public class AdminController {

    private final AdminService adminService;

    public AdminController(AdminService adminService) {
        this.adminService = adminService;
    }

    @GetMapping("/stats")
    public Result<AdminStatsVO> stats() {
        return Result.ok(adminService.stats());
    }

    @GetMapping("/users")
    public Result<Page<AdminUserVO>> users(@RequestParam(defaultValue = "1") int page,
                                           @RequestParam(defaultValue = "10") int size,
                                           @RequestParam(required = false) String keyword) {
        return Result.ok(adminService.pageUsers(page, size, keyword));
    }

    @PutMapping("/users/{id}/status/{status}")
    public Result<Void> updateStatus(@PathVariable Long id, @PathVariable Integer status) {
        adminService.updateStatus(id, status, SecurityUtils.currentUsername());
        return Result.ok();
    }

    @DeleteMapping("/users/{id}")
    public Result<Void> deleteUser(@PathVariable Long id) {
        adminService.deleteUser(id, SecurityUtils.currentUsername());
        return Result.ok();
    }

    @GetMapping("/itineraries")
    public Result<Page<AdminItineraryVO>> itineraries(@RequestParam(defaultValue = "1") int page,
                                                      @RequestParam(defaultValue = "10") int size,
                                                      @RequestParam(required = false) String keyword,
                                                      @RequestParam(required = false) Integer status,
                                                      @RequestParam(required = false) Long userId) {
        return Result.ok(adminService.pageItineraries(page, size, keyword, status, userId));
    }

    @DeleteMapping("/itineraries/{id}")
    public Result<Void> deleteItinerary(@PathVariable Long id) {
        adminService.deleteItinerary(id);
        return Result.ok();
    }

    @GetMapping("/agent-metrics")
    public Result<Map<String, Object>> agentMetrics() {
        return Result.ok(adminService.agentMetrics());
    }

    @GetMapping("/llm-usage")
    public Result<JsonNode> llmUsage(@RequestParam(defaultValue = "24h") String range,
                                     @RequestParam(defaultValue = "200") int limit,
                                     @RequestParam(defaultValue = "0") int offset) {
        return Result.ok(adminService.llmUsage(range, limit, offset));
    }
}
