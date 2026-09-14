package com.travel.backend.service.impl;

import tools.jackson.databind.json.JsonMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;
import com.travel.backend.common.BizException;
import com.travel.backend.common.SimpleCircuitBreaker;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.entity.SysUser;
import com.travel.backend.mapper.ItineraryMainMapper;
import com.travel.backend.mapper.SysUserMapper;
import com.travel.backend.service.AdminService;
import com.travel.backend.service.AgentService;
import com.travel.backend.vo.AdminItineraryVO;
import com.travel.backend.vo.AdminStatsVO;
import com.travel.backend.vo.AdminUserVO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
public class AdminServiceImpl implements AdminService {

    private static final Logger log = LoggerFactory.getLogger(AdminServiceImpl.class);

    private final ObjectMapper objectMapper = JsonMapper.builder().build();

    private final SysUserMapper sysUserMapper;
    private final ItineraryMainMapper itineraryMainMapper;
    private final AgentService agentService;
    private final ItineraryCommandService commandService;
    private final SimpleCircuitBreaker circuitBreaker;

    public AdminServiceImpl(SysUserMapper sysUserMapper, ItineraryMainMapper itineraryMainMapper,
                            AgentService agentService, ItineraryCommandService commandService,
                            SimpleCircuitBreaker circuitBreaker) {
        this.sysUserMapper = sysUserMapper;
        this.itineraryMainMapper = itineraryMainMapper;
        this.agentService = agentService;
        this.commandService = commandService;
        this.circuitBreaker = circuitBreaker;
    }

    @Override
    public AdminStatsVO stats() {
        AdminStatsVO vo = new AdminStatsVO();
        // 用户总数取自增 ID 最大值：包含被物理删除的账号，反映真实注册规模
        List<Object> maxIds = sysUserMapper.selectObjs(
                new QueryWrapper<SysUser>().select("IFNULL(MAX(id), 0)"));
        vo.setTotalUsers(maxIds.isEmpty() || maxIds.get(0) == null
                ? 0L : ((Number) maxIds.get(0)).longValue());
        vo.setActiveUsers(sysUserMapper.selectCount(
                new LambdaQueryWrapper<SysUser>().eq(SysUser::getStatus, 1)));
        vo.setDisabledUsers(sysUserMapper.selectCount(
                new LambdaQueryWrapper<SysUser>().eq(SysUser::getStatus, 0)));
        vo.setTotalItineraries(itineraryMainMapper.selectCount(null));
        LocalDateTime todayStart = LocalDate.now().atStartOfDay();
        vo.setTodayNewUsers(sysUserMapper.selectCount(
                new LambdaQueryWrapper<SysUser>().ge(SysUser::getCreatedAt, todayStart)));
        vo.setTodayNewItineraries(itineraryMainMapper.selectCount(
                new LambdaQueryWrapper<ItineraryMain>().ge(ItineraryMain::getCreatedAt, todayStart)));
        vo.setGeneratingItineraries(itineraryMainMapper.selectCount(
                new LambdaQueryWrapper<ItineraryMain>().eq(ItineraryMain::getStatus, 1)));
        return vo;
    }

    @Override
    public Page<AdminUserVO> pageUsers(int page, int size, String keyword) {
        Page<SysUser> result = sysUserMapper.selectPage(new Page<>(page, size),
                new LambdaQueryWrapper<SysUser>()
                        .and(keyword != null && !keyword.isBlank(), w -> w
                                .like(SysUser::getUsername, keyword)
                                .or()
                                .like(SysUser::getNickname, keyword))
                        .orderByDesc(SysUser::getCreatedAt));
        List<AdminUserVO> records = result.getRecords().stream().map(this::toVO).toList();
        fillItineraryCounts(records);
        Page<AdminUserVO> voPage = new Page<>(result.getCurrent(), result.getSize(), result.getTotal());
        voPage.setRecords(records);
        return voPage;
    }

    /**
     * 批量填充每个用户的行程数（一次 group by 查询，避免逐行 N+1）。
     */
    private void fillItineraryCounts(List<AdminUserVO> records) {
        if (records.isEmpty()) {
            return;
        }
        List<Long> userIds = records.stream().map(AdminUserVO::getId).toList();
        Map<Long, Long> countByUser = new LinkedHashMap<>();
        for (Map<String, Object> row : itineraryMainMapper.selectMaps(
                new QueryWrapper<ItineraryMain>()
                        .select("user_id", "COUNT(*) AS cnt")
                        .in("user_id", userIds)
                        .groupBy("user_id"))) {
            Object userId = row.get("user_id");
            Object cnt = row.get("cnt");
            if (userId != null && cnt != null) {
                countByUser.put(((Number) userId).longValue(), ((Number) cnt).longValue());
            }
        }
        for (AdminUserVO vo : records) {
            vo.setItineraryCount(countByUser.getOrDefault(vo.getId(), 0L));
        }
    }

    @Override
    public void updateStatus(Long id, Integer status, String operatorUsername) {
        if (status == null || (status != 0 && status != 1)) {
            throw new BizException(400, "非法的状态值");
        }
        SysUser user = requireUser(id);
        if (user.getUsername().equals(operatorUsername)) {
            throw new BizException(400, "不能操作自己的账号");
        }
        user.setStatus(status);
        sysUserMapper.updateById(user);
    }

    @Override
    public void deleteUser(Long id, String operatorUsername) {
        SysUser user = requireUser(id);
        if (user.getUsername().equals(operatorUsername)) {
            throw new BizException(400, "不能删除自己的账号");
        }
        sysUserMapper.deleteById(id);
    }

    private SysUser requireUser(Long id) {
        SysUser user = sysUserMapper.selectById(id);
        if (user == null) {
            throw new BizException(404, "用户不存在");
        }
        return user;
    }

    @Override
    public Page<AdminItineraryVO> pageItineraries(int page, int size, String keyword, Integer status, Long userId) {
        Page<ItineraryMain> result = itineraryMainMapper.selectPage(new Page<>(page, size),
                new LambdaQueryWrapper<ItineraryMain>()
                        .eq(userId != null, ItineraryMain::getUserId, userId)
                        .and(keyword != null && !keyword.isBlank(), w -> w
                                .like(ItineraryMain::getTitle, keyword)
                                .or()
                                .like(ItineraryMain::getCity, keyword))
                        .eq(status != null, ItineraryMain::getStatus, status)
                        .orderByDesc(ItineraryMain::getCreatedAt));
        List<AdminItineraryVO> records = result.getRecords().stream().map(this::toItineraryVO).toList();
        Page<AdminItineraryVO> voPage = new Page<>(result.getCurrent(), result.getSize(), result.getTotal());
        voPage.setRecords(records);
        return voPage;
    }

    @Override
    public void deleteItinerary(Long id) {
        ItineraryMain itinerary = itineraryMainMapper.selectById(id);
        if (itinerary == null) {
            throw new BizException(404, "行程不存在");
        }
        // #11：复用用户侧级联删除（日/项/预算/聊天记录），避免只删主表遗留孤儿数据。
        // 不做版本快照：createSnapshot 依赖 findOwnedMain 的归属校验，管理员非属主。
        commandService.deleteCascade(id);
    }

    @Override
    public Map<String, Object> agentMetrics() {
        try {
            JsonNode metrics = agentService.metrics();
            Map<String, Object> data = objectMapper.convertValue(metrics,
                    new TypeReference<Map<String, Object>>() {
                    });
            data.put("agentAvailable", true);
            data.put("circuitBreaker", circuitBreaker.snapshot());
            return data;
        } catch (Exception e) {
            log.warn("fetch agent metrics failed: {}", e.getMessage());
            Map<String, Object> data = new LinkedHashMap<>();
            data.put("agentAvailable", false);
            data.put("circuitBreaker", circuitBreaker.snapshot());
            data.put("runs", 0);
            data.put("successes", 0);
            data.put("failures", 0);
            data.put("degraded_runs", 0);
            data.put("llm_calls", 0);
            data.put("tool_calls", 0);
            data.put("prompt_tokens", 0);
            data.put("completion_tokens", 0);
            data.put("success_rate", 0.0);
            data.put("failure_rate", 0.0);
            data.put("degraded_rate", 0.0);
            data.put("avg_event_latency_ms", 0.0);
            data.put("recent_failures", List.of());
            return data;
        }
    }

    @Override
    public JsonNode llmUsage(String range, int limit, int offset) {
        try {
            JsonNode usage = agentService.usage(range, limit, offset);
            ((ObjectNode) usage).put("agentAvailable", true);
            return usage;
        } catch (Exception e) {
            log.warn("fetch llm usage failed: {}", e.getMessage());
            Map<String, Object> data = new LinkedHashMap<>();
            data.put("agentAvailable", false);
            data.put("range", range == null ? "24h" : range);
            data.put("bucket", 3600);
            data.put("summary", Map.of("calls", 0, "successes", 0, "failures", 0,
                    "success_rate", 0.0, "prompt_tokens", 0, "completion_tokens", 0,
                    "total_tokens", 0, "avg_duration_ms", 0.0));
            data.put("by_scene", List.of());
            data.put("by_model", List.of());
            data.put("timeline", List.of());
            data.put("calls", Map.of("total", 0, "records", List.of()));
            return objectMapper.valueToTree(data);
        }
    }

    private AdminItineraryVO toItineraryVO(ItineraryMain itinerary) {
        AdminItineraryVO vo = new AdminItineraryVO();
        vo.setId(itinerary.getId());
        vo.setUserId(itinerary.getUserId());
        vo.setTitle(itinerary.getTitle());
        vo.setCity(itinerary.getCity());
        vo.setStartDate(itinerary.getStartDate());
        vo.setEndDate(itinerary.getEndDate());
        vo.setDays(itinerary.getDays());
        vo.setPersons(itinerary.getPersons());
        vo.setBudget(itinerary.getBudget());
        vo.setStatus(itinerary.getStatus());
        vo.setCreatedAt(itinerary.getCreatedAt());
        return vo;
    }

    private AdminUserVO toVO(SysUser user) {
        AdminUserVO vo = new AdminUserVO();
        vo.setId(user.getId());
        vo.setUsername(user.getUsername());
        vo.setNickname(user.getNickname());
        vo.setPhone(user.getPhone());
        vo.setStatus(user.getStatus());
        vo.setRole(user.getRole());
        vo.setCreatedAt(user.getCreatedAt());
        return vo;
    }
}
