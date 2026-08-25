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
                        : request.getStartDate().plusDays(dayNo - 1L).toString());
                payload.put("day_no", dayNo);
                payload.put("used_names", usedNames);
                payload.put("hotel_tier", request.getHotelTier());
                payload.put("chosen_hotel", chosenHotel);
                payload.put("needs_hotel", dayNo <= request.getStayNights());
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
            finish(userId, itineraryId);
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
            if ("hotel".equals(item.getItemType()) && dayNo > request.getStayNights()) {
                continue;
            }
            ItineraryItem entity = new ItineraryItem();
            entity.setDayId(day.getId());
            entity.setItineraryId(itineraryId);
            entity.setItemType(item.getItemType());
            entity.setPoiName(item.getPoiName());
            entity.setPoiId(item.getPoiId());
            entity.setAddress(item.getAddress());
            entity.setLatitude(item.getLatitude());
            entity.setLongitude(item.getLongitude());
            entity.setStartTime(parseTimeSafe(item.getStartTime()));
            entity.setEndTime(parseTimeSafe(item.getEndTime()));
            entity.setDurationMin(item.getDurationMin());
            entity.setCost(item.getCost());
            entity.setTag(item.getTag());
            entity.setRemark(item.getRemark());
            entity.setSortNo(sortNo++);
            itemMapper.insert(entity);
        }
        budgetEngine.recalculate(itineraryId);
    }

    private java.time.LocalTime parseTimeSafe(String t) {
        if (t == null || t.isBlank()) {
            return null;
        }
        String norm = t.trim();
        if (norm.startsWith("24:")) {
            norm = "00:" + norm.substring(3);
        }
        try {
            return java.time.LocalTime.parse(norm);
        } catch (Exception e) {
            return null;
        }
    }

    private void evictCache() {
        var cache = cacheManager.getCache("itinerary:detail");
        if (cache != null) {
            cache.clear();
        }
    }

    private void finish(Long userId, Long itineraryId) {
        ItineraryMain main = mainMapper.selectById(itineraryId);
        if (main == null) {
            evictCache();
            return;
        }
        main.setStatus(2);
        main.setTitle(main.getCity() + main.getDays() + "日游");

        // 管家讲解：基于最终行程生成安排思路
        try {
            List<Map<String, Object>> plans = new ArrayList<>();
            for (ItineraryDay day : dayMapper.selectList(new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<ItineraryDay>()
                    .eq(ItineraryDay::getItineraryId, itineraryId).orderByAsc(ItineraryDay::getDayNo))) {
                List<String> names = itemMapper.selectList(new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<ItineraryItem>()
                                .eq(ItineraryItem::getDayId, day.getId()).orderByAsc(ItineraryItem::getSortNo))
                        .stream().map(ItineraryItem::getPoiName).toList();
                plans.add(Map.of("day_no", day.getDayNo(), "items", names));
            }
            Map<String, Object> payload = Map.of(
                    "city", main.getCity(),
                    "days", main.getDays(),
                    "persons", main.getPersons() == null ? 1 : main.getPersons(),
                    "preferences", main.getPreferences() == null ? "" : main.getPreferences(),
                    "hotel_tier", main.getHotelTier() == null ? "" : main.getHotelTier(),
                    "budget", main.getBudget() == null ? "" : main.getBudget(),
                    "plans", plans);
            JsonNode noteNode = agentService.butlerNote(payload);
            String note = noteNode.path("note").asText("");
            if (!note.isBlank()) {
                main.setPlanNote(note);
            }
        } catch (Exception e) {
            log.warn("butler note failed for {}: {}", itineraryId, e.getMessage());
        }
        mainMapper.updateById(main);

        // 景点详细介绍：批量生成后逐条回填
        try {
            List<ItineraryItem> allItems = itemMapper.selectList(new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<ItineraryItem>()
                    .eq(ItineraryItem::getItineraryId, itineraryId));
            List<String> names = allItems.stream().map(ItineraryItem::getPoiName)
                    .filter(n -> n != null && !n.isBlank()).distinct().toList();
            if (!names.isEmpty()) {
                JsonNode introNode = agentService.poiIntros(
                        Map.of("city", main.getCity(), "names", names));
                JsonNode intros = introNode.get("intros");
                if (intros != null && intros.isObject()) {
                    for (ItineraryItem item : allItems) {
                        JsonNode intro = intros.get(item.getPoiName());
                        if (intro != null && !intro.asText().isBlank()) {
                            item.setIntro(intro.asText());
                            itemMapper.updateById(item);
                        }
                    }
                }
            }
        } catch (Exception e) {
            log.warn("poi intros failed for {}: {}", itineraryId, e.getMessage());
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
