package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.travel.backend.common.DistributedStateService;
import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.mapper.ItineraryDayMapper;
import com.travel.backend.mapper.ItineraryItemMapper;
import com.travel.backend.mapper.ItineraryMainMapper;
import com.travel.backend.service.AgentService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.cache.CacheManager;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.List;

/** 修复因进程中断遗留的生成中行程，避免页面永久轮询。 */
@Slf4j
@Service
public class ItineraryStatusRecovery {

    private final ItineraryMainMapper mainMapper;
    private final ItineraryDayMapper dayMapper;
    private final ItineraryItemMapper itemMapper;
    private final CacheManager cacheManager;
    private final AgentService agentService;
    private final ItineraryAsyncPlanner planner;
    private final DistributedStateService state;
    /** 续跑去重 TTL：大于单次生成最坏耗时（Python 读超时 180s + 落库）。 */
    private static final Duration RESUME_TTL = Duration.ofMinutes(10);

    public ItineraryStatusRecovery(ItineraryMainMapper mainMapper, ItineraryDayMapper dayMapper,
                                   ItineraryItemMapper itemMapper, CacheManager cacheManager,
                                   AgentService agentService, ItineraryAsyncPlanner planner,
                                   DistributedStateService state) {
        this.mainMapper = mainMapper;
        this.dayMapper = dayMapper;
        this.itemMapper = itemMapper;
        this.cacheManager = cacheManager;
        this.agentService = agentService;
        this.planner = planner;
        this.state = state;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void recoverOnStartup() {
        recover();
    }

    @Scheduled(fixedDelay = 60_000L, initialDelay = 60_000L)
    public void recover() {
        LocalDateTime activeAfter = LocalDateTime.now().minusMinutes(5);
        List<ItineraryMain> pending = mainMapper.selectList(
                new LambdaQueryWrapper<ItineraryMain>().eq(ItineraryMain::getStatus, 1));
        List<ItineraryMain> failedTrips = mainMapper.selectList(
                new LambdaQueryWrapper<ItineraryMain>()
                        .eq(ItineraryMain::getStatus, 3)
                        .lt(ItineraryMain::getUpdatedAt, activeAfter));
        boolean changed = false;
        for (ItineraryMain main : pending) {
            if (main.getUpdatedAt() != null && main.getUpdatedAt().isAfter(activeAfter)) {
                continue;
            }
            changed |= recoverOne(main, activeAfter, false);
        }
        for (ItineraryMain main : failedTrips) {
            changed |= recoverOne(main, activeAfter, true);
        }
        if (changed) {
            var cache = cacheManager.getCache("itinerary:detail");
            if (cache != null) cache.clear();
        }
    }

    private boolean recoverOne(ItineraryMain main, LocalDateTime activeAfter, boolean failedResume) {
        List<ItineraryDay> days = dayMapper.selectList(
                new LambdaQueryWrapper<ItineraryDay>()
                        .eq(ItineraryDay::getItineraryId, main.getId()));
        long completedDays = days.stream().filter(day -> "SUCCEEDED".equals(day.getGenerationStatus())
                || (day.getGenerationStatus() == null && itemMapper.selectCount(
                new LambdaQueryWrapper<ItineraryItem>().eq(ItineraryItem::getDayId, day.getId())) > 0)).count();
        if (!days.isEmpty() && completedDays == days.size() && days.size() == main.getDays()) {
            main.setStatus(2);
            main.setTitle(main.getCity() + main.getDays() + "日游");
            mainMapper.updateById(main);
            log.info("recovered completed itinerary {}", main.getId());
            return true;
        }
        if (hasActiveDay(days, activeAfter)) {
            // 进程内原任务仍在运行；避免定时恢复与原任务并发生成同一天。
            return false;
        }
        if (failedResume && !resumableFailedTrip(days, main)) {
            return false;
        }
        String resumeKey = "gen:resume:" + main.getId();
        if (!state.tryMark(resumeKey, RESUME_TTL)) {
            // 已有实例在续跑该行程
            return false;
        }
        try {
            GenerateRequest request = rebuildRequest(main);
            if (failedResume) {
                main.setPlanNote(ItineraryAsyncPlanner.RESUME_MARKER);
                main.setStatus(1);
                mainMapper.updateById(main);
            }
            planner.planDays(main.getUserId(), main.getId(), request, null);
            log.info("resumed interrupted itinerary {}", main.getId());
        } catch (Exception e) {
            state.unmark(resumeKey);
            log.warn("could not resume itinerary {}: {}", main.getId(), e.getMessage());
        }
        return failedResume;
    }

    /**
     * #19：判定 status=3 的行程是否可自动续跑：所有未成功天均为 FAILED 且有
     * 错误信息（即落库阶段失败、planDays 可幂等重跑补天）；planNote 已含续跑
     * 标记说明已自动重试过一次，不再重拉，防止失败-重生成死循环。
     */
    private boolean resumableFailedTrip(List<ItineraryDay> days, ItineraryMain main) {
        if (days.isEmpty() || main.getPlanNote() != null
                && main.getPlanNote().contains(ItineraryAsyncPlanner.RESUME_MARKER)) {
            return false;
        }
        for (ItineraryDay day : days) {
            if ("SUCCEEDED".equals(day.getGenerationStatus())) {
                continue;
            }
            if (!"FAILED".equals(day.getGenerationStatus())
                    || day.getGenerationError() == null || day.getGenerationError().isBlank()) {
                return false;
            }
        }
        return true;
    }

    private boolean hasActiveDay(List<ItineraryDay> days, LocalDateTime activeAfter) {
        return days.stream().anyMatch(day -> "RUNNING".equals(day.getGenerationStatus())
                && day.getUpdatedAt() != null && day.getUpdatedAt().isAfter(activeAfter));
    }

    private GenerateRequest rebuildRequest(ItineraryMain main) {
        GenerateRequest request = new GenerateRequest();
        request.setCity(main.getCity());
        request.setDays(main.getDays());
        request.setPersons(main.getPersons() == null ? 1 : main.getPersons());
        request.setStartDate(main.getStartDate());
        request.setEndDate(main.getEndDate());
        request.setBudget(main.getBudget());
        request.setHotelTier(main.getHotelTier());
        request.setStayNights(main.getStayNights() == null
                ? Math.max(main.getDays() - 1, 0) : main.getStayNights());
        request.setPreferences(main.getPreferences() == null || main.getPreferences().isBlank()
                ? List.of() : List.of(main.getPreferences().split(",")));
        return request;
    }
}
