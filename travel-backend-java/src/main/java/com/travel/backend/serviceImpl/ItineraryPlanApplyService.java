package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.travel.backend.common.BizException;
import com.travel.backend.common.SeasonPrice;
import com.travel.backend.dto.HotelOptionApplyRequest;
import com.travel.backend.entity.HotelRoomType;
import com.travel.backend.entity.ItineraryChatMessage;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.entity.PoiKnowledge;
import com.travel.backend.mapper.HotelRoomTypeMapper;
import com.travel.backend.mapper.ItineraryDayMapper;
import com.travel.backend.mapper.ItineraryItemMapper;
import com.travel.backend.mapper.ItineraryMainMapper;
import com.travel.backend.mapper.PoiKnowledgeMapper;
import com.travel.backend.service.BudgetEngine;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalTime;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/** 用户确认后的行程草稿和酒店房型应用。 */
@Service
public class ItineraryPlanApplyService {

    private final ItineraryMainMapper mainMapper;
    private final ItineraryDayMapper dayMapper;
    private final ItineraryItemMapper itemMapper;
    private final PoiKnowledgeMapper poiKnowledgeMapper;
    private final HotelRoomTypeMapper hotelRoomTypeMapper;
    private final BudgetEngine budgetEngine;
    private final ItineraryQueryService queryService;
    private final ItineraryChatService chatService;

    public ItineraryPlanApplyService(ItineraryMainMapper mainMapper, ItineraryDayMapper dayMapper,
                                     ItineraryItemMapper itemMapper, PoiKnowledgeMapper poiKnowledgeMapper,
                                     HotelRoomTypeMapper hotelRoomTypeMapper, BudgetEngine budgetEngine,
                                     ItineraryQueryService queryService, ItineraryChatService chatService) {
        this.mainMapper = mainMapper;
        this.dayMapper = dayMapper;
        this.itemMapper = itemMapper;
        this.poiKnowledgeMapper = poiKnowledgeMapper;
        this.hotelRoomTypeMapper = hotelRoomTypeMapper;
        this.budgetEngine = budgetEngine;
        this.queryService = queryService;
        this.chatService = chatService;
    }

    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public com.travel.backend.vo.ItineraryVO applyPlans(Long userId, Long itineraryId,
                                                        Long actionMessageId, String baseRevision) {
        ItineraryMain main = queryService.findOwnedMain(userId, itineraryId);
        ItineraryChatMessage actionMessage = chatService.requirePendingAction(
                userId, itineraryId, actionMessageId, baseRevision, false);
        List<Map<String, Object>> plans = chatService.readPlans(actionMessage);
        List<ItineraryDay> days = dayMapper.selectList(new LambdaQueryWrapper<ItineraryDay>()
                .eq(ItineraryDay::getItineraryId, itineraryId).orderByAsc(ItineraryDay::getDayNo));
        validatePlans(plans);
        Map<Long, ItineraryItem> existingItems = itemMapper.selectList(
                        new LambdaQueryWrapper<ItineraryItem>()
                                .eq(ItineraryItem::getItineraryId, itineraryId))
                .stream().collect(Collectors.toMap(ItineraryItem::getId, item -> item));
        Set<Long> retainedItemIds = new HashSet<>();
        Map<Integer, ItineraryDay> dayByNo = new HashMap<>();
        for (ItineraryDay day : days) {
            dayByNo.put(day.getDayNo(), day);
        }
        for (int dayNo = 1; dayNo <= plans.size(); dayNo++) {
            if (dayByNo.containsKey(dayNo)) {
                continue;
            }
            ItineraryDay day = new ItineraryDay();
            day.setItineraryId(itineraryId);
            day.setDayNo(dayNo);
            day.setCity(main.getCity());
            day.setTravelDate(main.getStartDate() == null ? null : main.getStartDate().plusDays(dayNo - 1L));
            day.setNote("宽松安排");
            dayMapper.insert(day);
            dayByNo.put(dayNo, day);
        }
        for (Map<String, Object> plan : plans) {
            int dayNo = ((Number) plan.getOrDefault("day_no", 0)).intValue();
            ItineraryDay day = dayByNo.get(dayNo);
            if (day == null) {
                continue;
            }
            Object note = plan.get("note");
            if (note instanceof String s && !s.isBlank()) {
                day.setNote(s);
                dayMapper.updateById(day);
            }
            int sortNo = 0;
            for (Object rawItem : (List<?>) plan.getOrDefault("items", List.of())) {
                if (!(rawItem instanceof Map<?, ?> item)) {
                    continue;
                }
                String name = String.valueOf(item.get("poi_name"));
                if (name.isBlank() || "null".equals(name)) {
                    continue;
                }
                PoiKnowledge poi = poiKnowledgeMapper.selectOne(new LambdaQueryWrapper<PoiKnowledge>()
                        .eq(PoiKnowledge::getCity, main.getCity())
                        .eq(PoiKnowledge::getName, name).last("LIMIT 1"));
                ItineraryItem existing = null;
                if (item.get("id") instanceof Number itemId) {
                    existing = existingItems.get(itemId.longValue());
                    if (existing == null || !name.equals(existing.getPoiName())) {
                        throw new BizException(400, "行程项身份校验失败，未应用任何修改");
                    }
                }
                String itemType = str(item.get("item_type"), poi != null ? poi.getCategory() : "attraction");
                if (poi == null && existing == null && !"transport".equals(itemType)) {
                    throw new BizException(400, "行程项不属于当前城市候选 POI，未应用任何修改");
                }
                ItineraryItem entity = existing == null ? new ItineraryItem() : existing;
                entity.setDayId(day.getId());
                entity.setItineraryId(itineraryId);
                entity.setItemType(itemType);
                entity.setPoiName(name);
                if (poi != null) {
                    entity.setPoiId(String.valueOf(poi.getId()));
                    entity.setAddress(poi.getAddress());
                    entity.setLatitude(poi.getLatitude());
                    entity.setLongitude(poi.getLongitude());
                    entity.setCost(poi.getTicketPrice());
                    entity.setDurationMin(poi.getDurationMin());
                    entity.setTag(poi.getTags());
                }
                if (existing != null) {
                    entity.setCost(existing.getCost());
                }
                entity.setStartTime(parseTime(item.get("start_time")));
                entity.setEndTime(parseTime(item.get("end_time")));
                if (item.get("duration_min") instanceof Number n) {
                    entity.setDurationMin(n.intValue());
                }
                entity.setTag(str(item.get("tag"), entity.getTag()));
                entity.setRemark(str(item.get("remark"), entity.getRemark()));
                entity.setSortNo(sortNo++);
                if (existing == null) {
                    itemMapper.insert(entity);
                } else {
                    retainedItemIds.add(existing.getId());
                    itemMapper.updateById(entity);
                }
            }
        }
        for (Long existingId : existingItems.keySet()) {
            if (!retainedItemIds.contains(existingId)) {
                itemMapper.deleteById(existingId);
            }
        }
        for (ItineraryDay day : days) {
            if (day.getDayNo() > plans.size()) {
                dayMapper.deleteById(day.getId());
            }
        }
        if (!java.util.Objects.equals(main.getDays(), plans.size())) {
            main.setDays(plans.size());
            main.setEndDate(main.getStartDate() == null ? null : main.getStartDate().plusDays(plans.size() - 1L));
            main.setTitle(main.getCity() + plans.size() + "日游");
            mainMapper.updateById(main);
        }
        budgetEngine.recalculate(itineraryId);
        chatService.consumePendingAction(actionMessage);
        return queryService.detail(userId, itineraryId);
    }

    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public com.travel.backend.vo.ItineraryVO applyHotelOption(Long userId, Long itineraryId,
                                                               HotelOptionApplyRequest request) {
        ItineraryMain main = queryService.findOwnedMain(userId, itineraryId);
        ItineraryChatMessage actionMessage = chatService.requirePendingAction(
                userId, itineraryId, request.getActionMessageId(), request.getBaseRevision(), true);
        if (request.getHotelName() == null || request.getHotelName().isBlank()
                || request.getHotelName().length() > 128) {
            throw new BizException(400, "酒店名称不合法");
        }
        PoiKnowledge hotel = poiKnowledgeMapper.selectOne(new LambdaQueryWrapper<PoiKnowledge>()
                .eq(PoiKnowledge::getCity, main.getCity())
                .eq(PoiKnowledge::getCategory, "hotel")
                .eq(PoiKnowledge::getName, request.getHotelName()).last("LIMIT 1"));
        // 省级目的地的酒店候选来自省内具体城市，按名称兜底解析。
        if (hotel == null) {
            hotel = poiKnowledgeMapper.selectOne(new LambdaQueryWrapper<PoiKnowledge>()
                    .eq(PoiKnowledge::getCategory, "hotel")
                    .eq(PoiKnowledge::getName, request.getHotelName()).last("LIMIT 1"));
        }
        if (hotel == null) {
            throw new BizException(404, "未找到该城市的酒店候选");
        }
        chatService.validateHotelChoice(actionMessage, request.getHotelName(), request.getRoomType());
        List<ItineraryItem> hotelItems = itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                .eq(ItineraryItem::getItineraryId, itineraryId)
                .eq(ItineraryItem::getItemType, "hotel"));
        List<ItineraryDay> itineraryDays = dayMapper.selectList(new LambdaQueryWrapper<ItineraryDay>()
                .eq(ItineraryDay::getItineraryId, itineraryId));
        Map<Long, ItineraryDay> dayById = itineraryDays.stream()
                .collect(Collectors.toMap(ItineraryDay::getId, day -> day));
        Map<Integer, ItineraryDay> dayByNo = itineraryDays.stream()
                .collect(Collectors.toMap(ItineraryDay::getDayNo, day -> day));
        Set<Integer> existingHotelDayNos = hotelItems.stream()
                .map(item -> dayById.get(item.getDayId())).filter(java.util.Objects::nonNull)
                .map(ItineraryDay::getDayNo).collect(Collectors.toSet());
        Set<Integer> selectedDayNos = new LinkedHashSet<>(request.getDayNos());
        if (selectedDayNos.isEmpty() || !dayByNo.keySet().containsAll(selectedDayNos)) {
            throw new BizException(400, "选择的入住晚次不在当前行程中");
        }

        HotelRoomType roomType = hotelRoomTypeMapper.selectOne(new LambdaQueryWrapper<HotelRoomType>()
                .eq(HotelRoomType::getPoiId, hotel.getId())
                .eq(HotelRoomType::getRoomName, request.getRoomType()).last("LIMIT 1"));
        BigDecimal roomBasePrice;
        String roomDescription;
        if (roomType != null) {
            roomBasePrice = roomType.getBasePrice();
            roomDescription = roomType.getDescription();
        } else if ("基础房型".equals(request.getRoomType())) {
            roomBasePrice = hotel.getTicketPrice();
            roomDescription = "知识库酒店基础房型参考价";
        } else {
            throw new BizException(400, "该酒店不存在所选房型");
        }
        if (roomBasePrice == null || roomBasePrice.signum() <= 0) {
            throw new BizException(400, "所选房型暂无有效参考价");
        }
        for (Integer dayNo : selectedDayNos) {
            ItineraryDay day = dayByNo.get(dayNo);
            ItineraryItem item = hotelItems.stream()
                    .filter(existing -> existing.getDayId().equals(day.getId())).findFirst().orElse(null);
            boolean newItem = item == null;
            if (newItem) {
                item = new ItineraryItem();
                item.setItineraryId(itineraryId);
                item.setDayId(day.getId());
                item.setItemType("hotel");
                item.setStartTime(LocalTime.of(20, 0));
                item.setSortNo(nextSort(day.getId()));
            }
            java.time.LocalDate stayDate = day.getTravelDate() == null ? main.getStartDate() : day.getTravelDate();
            BigDecimal adjustedPrice = SeasonPrice.apply(roomBasePrice, stayDate);
            String priceRemark = "房型：" + request.getRoomType() + "；基准价￥" + roomBasePrice + "；按" +
                    SeasonPrice.label(stayDate) + "系数×" + SeasonPrice.factor(stayDate) +
                    (roomDescription == null || roomDescription.isBlank() ? "" : "；" + roomDescription);
            item.setPoiId(String.valueOf(hotel.getId()));
            item.setPoiName(hotel.getName());
            item.setAddress(hotel.getAddress());
            item.setLatitude(hotel.getLatitude());
            item.setLongitude(hotel.getLongitude());
            item.setCost(adjustedPrice);
            item.setDurationMin(hotel.getDurationMin());
            item.setTag(hotel.getTags());
            item.setRemark(priceRemark);
            if (newItem) itemMapper.insert(item); else itemMapper.updateById(item);
        }
        if (selectedDayNos.containsAll(existingHotelDayNos)
                && request.getTier() != null && !request.getTier().isBlank()) {
            main.setHotelTier(request.getTier());
            mainMapper.updateById(main);
        }
        budgetEngine.recalculate(itineraryId);
        chatService.consumePendingAction(actionMessage);
        return queryService.detail(userId, itineraryId);
    }

    private Integer nextSort(Long dayId) {
        return itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                        .eq(ItineraryItem::getDayId, dayId)).stream()
                .map(ItineraryItem::getSortNo).filter(s -> s != null)
                .max(Integer::compareTo).orElse(-1) + 1;
    }

    private String str(Object value, String fallback) {
        if (value == null) return fallback;
        String text = String.valueOf(value);
        return text.isBlank() || "null".equals(text) ? fallback : text;
    }

    private LocalTime parseTime(Object value) {
        if (value == null) return null;
        try { return LocalTime.parse(String.valueOf(value)); }
        catch (Exception ignored) { return null; }
    }

    private void validatePlans(List<Map<String, Object>> plans) {
        if (plans == null || plans.isEmpty() || plans.size() > com.travel.backend.dto.GenerateRequest.MAX_TRIP_DAYS) {
            throw new BizException(400, "行程草稿必须包含 1 到 7 个完整日期，未应用任何修改");
        }
        Set<Integer> seenDays = new HashSet<>();
        Set<Integer> validDays = java.util.stream.IntStream.rangeClosed(1, plans.size()).boxed().collect(Collectors.toSet());
        for (Map<String, Object> plan : plans) {
            if (plan == null || !(plan.get("day_no") instanceof Number)) {
                throw new BizException(400, "行程草稿日期格式错误，未应用任何修改");
            }
            int dayNo = ((Number) plan.get("day_no")).intValue();
            if (!validDays.contains(dayNo) || !seenDays.add(dayNo)) {
                throw new BizException(400, "行程草稿日期重复或越界，未应用任何修改");
            }
            Object rawItems = plan.get("items");
            if (!(rawItems instanceof List<?> items) || items.size() > 20) {
                throw new BizException(400, "单日行程项数量或格式不合法，未应用任何修改");
            }
            for (Object rawItem : items) {
                if (!(rawItem instanceof Map<?, ?> item)) {
                    throw new BizException(400, "行程项格式错误，未应用任何修改");
                }
                String name = String.valueOf(item.get("poi_name"));
                String type = String.valueOf(item.get("item_type"));
                if (name.isBlank() || "null".equals(name) || name.length() > 128
                        || !List.of("attraction", "food", "hotel", "transport").contains(type)) {
                    throw new BizException(400, "行程项名称或类型不合法，未应用任何修改");
                }
                Object cost = item.get("cost");
                if (cost != null && (!(cost instanceof Number) || ((Number) cost).doubleValue() < 0
                        || ((Number) cost).doubleValue() > 1_000_000)) {
                    throw new BizException(400, "行程项费用不合法，未应用任何修改");
                }
                Object duration = item.get("duration_min");
                if (duration != null && (!(duration instanceof Number)
                        || ((Number) duration).intValue() < 0 || ((Number) duration).intValue() > 1440)) {
                    throw new BizException(400, "行程项时长不合法，未应用任何修改");
                }
                validateOptionalTime(item.get("start_time"));
                validateOptionalTime(item.get("end_time"));
            }
        }
    }

    private void validateOptionalTime(Object value) {
        if (value == null || String.valueOf(value).isBlank() || "null".equals(value)) return;
        try { LocalTime.parse(String.valueOf(value)); }
        catch (Exception e) { throw new BizException(400, "时间格式不合法，未应用任何修改"); }
    }
}
