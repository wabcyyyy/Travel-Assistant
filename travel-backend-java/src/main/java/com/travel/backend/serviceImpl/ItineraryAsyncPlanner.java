package com.travel.backend.serviceImpl;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.travel.backend.common.BizException;
import com.travel.backend.dto.AgentGenerateResponse;
import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.mapper.ItineraryDayMapper;
import com.travel.backend.mapper.ItineraryItemMapper;
import com.travel.backend.mapper.ItineraryMainMapper;
import com.travel.backend.service.BudgetEngine;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.CacheManager;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 逐日流式生成编排：每天完成即落库并清缓存，前端轮询可见渐进结果。
 */
@Slf4j
@Service
public class ItineraryAsyncPlanner {

    private final AgentServiceImpl agentService;
    private final ItineraryDayMapper dayMapper;
    private final ItineraryItemMapper itemMapper;
    private final ItineraryMainMapper mainMapper;
    private final BudgetEngine budgetEngine;
    private final CacheManager cacheManager;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public ItineraryAsyncPlanner(AgentServiceImpl agentService, ItineraryDayMapper dayMapper,
                                 ItineraryItemMapper itemMapper, ItineraryMainMapper mainMapper,
                                 BudgetEngine budgetEngine, CacheManager cacheManager) {
        this.agentService = agentService;
        this.dayMapper = dayMapper;
        this.itemMapper = itemMapper;
        this.mainMapper = mainMapper;
        this.budgetEngine = budgetEngine;
        this.cacheManager = cacheManager;
    }

    @Async
    public void planDays(Long userId, Long itineraryId, GenerateRequest request) {
        try {
            // 等待壳数据可见（generate 无事务，正常已提交；兜底重试）
            for (int i = 0; i < 10; i++) {
                if (mainMapper.selectById(itineraryId) != null) break;
                Thread.sleep(500);
            }
            JsonNode context = agentService.planContext(request.getCity(), request.getPreferences());
            List<String> usedNames = new ArrayList<>();
            String chosenHotel = null;

            for (int dayNo = 1; dayNo <= request.getDays(); dayNo++) {
                Map<String, Object> payload = new java.util.HashMap<>();
                payload.put("city", request.getCity());
                payload.put("persons", request.getPersons());
                payload.put("budget", request.getBudget() == null ? null
                        : request.getBudget().doubleValue());
                payload.put("start_date", request.getStartDate() == null ? null
                        : request.getStartDate().toString());
                payload.put("day_no", dayNo);
                payload.put("used_names", usedNames);
                payload.put("hotel_tier", request.getHotelTier());
                payload.put("chosen_hotel", chosenHotel);
                payload.put("context", context);

                JsonNode node = agentService.generateDay(payload);
                AgentGenerateResponse.DailyPlan plan =
                        objectMapper.convertValue(node, AgentGenerateResponse.DailyPlan.class);
                persistDay(itineraryId, request, dayNo, plan);
                plan.getItems().forEach(i -> usedNames.add(i.getPoiName()));
                if (chosenHotel == null) {
                    chosenHotel = plan.getItems().stream()
                            .filter(i -> "hotel".equals(i.getItemType()))
                            .map(AgentGenerateResponse.Item::getPoiName)
                            .findFirst().orElse(null);
                }
                evictCache();
            }
            finish(itineraryId);
        } catch (Exception e) {
            log.error("async planning failed for itinerary {}", itineraryId, e);
            fail(itineraryId, e.getMessage());
        }
    }

    private void persistDay(Long itineraryId, GenerateRequest request, int dayNo,
                            AgentGenerateResponse.DailyPlan plan) {
        ItineraryDay day = dayMapper.selectOne(new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<ItineraryDay>()
                .eq(ItineraryDay::getItineraryId, itineraryId)
                .eq(ItineraryDay::getDayNo, dayNo));
        if (day == null) {
            throw new BizException(500, "行程日不存在");
        }
        if (plan.getNote() != null) {
            day.setNote(plan.getNote());
        }
        dayMapper.updateById(day);

        int sortNo = 0;
        for (AgentGenerateResponse.Item item : plan.getItems()) {
            ItineraryItem entity = new ItineraryItem();
            entity.setDayId(day.getId());
            entity.setItineraryId(itineraryId);
            entity.setItemType(item.getItemType());
            entity.setPoiName(item.getPoiName());
            entity.setPoiId(item.getPoiId());
            entity.setAddress(item.getAddress());
            entity.setLatitude(item.getLatitude());
            entity.setLongitude(item.getLongitude());
            entity.setStartTime(item.getStartTime() == null ? null
                    : java.time.LocalTime.parse(item.getStartTime()));
            entity.setEndTime(item.getEndTime() == null ? null
                    : java.time.LocalTime.parse(item.getEndTime()));
            entity.setDurationMin(item.getDurationMin());
            entity.setCost(item.getCost());
            entity.setTag(item.getTag());
            entity.setRemark(item.getRemark());
            entity.setSortNo(sortNo++);
            itemMapper.insert(entity);
        }
        budgetEngine.recalculate(itineraryId);
    }

    private void evictCache() {
        var cache = cacheManager.getCache("itinerary:detail");
        if (cache != null) {
            cache.clear();
        }
    }

    private void finish(Long itineraryId) {
        ItineraryMain main = mainMapper.selectById(itineraryId);
        if (main != null) {
            main.setStatus(2);
            main.setTitle(main.getCity() + main.getDays() + "日游");
            mainMapper.updateById(main);
        }
        evictCache();
    }

    private void fail(Long itineraryId, String message) {
        ItineraryMain main = mainMapper.selectById(itineraryId);
        if (main != null) {
            main.setStatus(3);
            mainMapper.updateById(main);
        }
        evictCache();
    }
}
