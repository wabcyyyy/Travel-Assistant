package com.travel.backend.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import com.travel.backend.common.BizException;
import com.travel.backend.dto.ItemUpsertRequest;
import com.travel.backend.entity.BudgetDetail;
import com.travel.backend.entity.ItineraryChatMessage;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.entity.PoiKnowledge;
import com.travel.backend.mapper.BudgetDetailMapper;
import com.travel.backend.mapper.ItineraryChatMessageMapper;
import com.travel.backend.mapper.ItineraryDayMapper;
import com.travel.backend.mapper.ItineraryItemMapper;
import com.travel.backend.mapper.ItineraryMainMapper;
import com.travel.backend.mapper.PoiKnowledgeMapper;
import com.travel.backend.service.AgentService;
import com.travel.backend.service.BudgetEngine;
import com.travel.backend.vo.ItineraryVO;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/** 行程生命周期、行程项增删改、排序以及自然语言修改命令。 */
@Service
public class ItineraryCommandService {

    private static final Logger log = LoggerFactory.getLogger(ItineraryCommandService.class);

    private final ItineraryMainMapper mainMapper;
    private final ItineraryDayMapper dayMapper;
    private final ItineraryItemMapper itemMapper;
    private final BudgetDetailMapper budgetMapper;
    private final ItineraryChatMessageMapper chatMessageMapper;
    private final PoiKnowledgeMapper poiKnowledgeMapper;
    private final AgentService agentService;
    private final BudgetEngine budgetEngine;
    private final ItineraryQueryService queryService;
    private final ItineraryChatService chatService;
    private final ItineraryVersionService versionService;
    private final ObjectMapper objectMapper;

    public ItineraryCommandService(ItineraryMainMapper mainMapper, ItineraryDayMapper dayMapper,
                                   ItineraryItemMapper itemMapper, BudgetDetailMapper budgetMapper,
                                   ItineraryChatMessageMapper chatMessageMapper,
                                   PoiKnowledgeMapper poiKnowledgeMapper, AgentService agentService,
                                   BudgetEngine budgetEngine, ItineraryQueryService queryService,
                                   ItineraryChatService chatService,
                                   ItineraryVersionService versionService,
                                   ObjectMapper objectMapper) {
        this.mainMapper = mainMapper;
        this.dayMapper = dayMapper;
        this.itemMapper = itemMapper;
        this.budgetMapper = budgetMapper;
        this.chatMessageMapper = chatMessageMapper;
        this.poiKnowledgeMapper = poiKnowledgeMapper;
        this.agentService = agentService;
        this.budgetEngine = budgetEngine;
        this.queryService = queryService;
        this.chatService = chatService;
        this.versionService = versionService;
        this.objectMapper = objectMapper;
    }

    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public void delete(Long userId, Long itineraryId) {
        queryService.findOwnedMain(userId, itineraryId);
        versionService.createSnapshot(userId, itineraryId, "delete", "删除行程前快照");
        deleteCascade(itineraryId);
    }

    /**
     * #11：级联删除行程明细（日/项/预算/聊天记录）并删除主表。
     * 用户侧与 Admin 侧共用，避免 Admin 只删主表遗留孤儿数据。
     */
    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public void deleteCascade(Long itineraryId) {
        dayMapper.delete(new LambdaQueryWrapper<ItineraryDay>().eq(ItineraryDay::getItineraryId, itineraryId));
        itemMapper.delete(new LambdaQueryWrapper<ItineraryItem>().eq(ItineraryItem::getItineraryId, itineraryId));
        budgetMapper.delete(new LambdaQueryWrapper<BudgetDetail>().eq(BudgetDetail::getItineraryId, itineraryId));
        chatMessageMapper.delete(new LambdaQueryWrapper<ItineraryChatMessage>()
                .eq(ItineraryChatMessage::getItineraryId, itineraryId));
        mainMapper.deleteById(itineraryId);
    }

    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public ItineraryVO addItem(Long userId, Long itineraryId, ItemUpsertRequest request) {
        queryService.findOwnedMain(userId, itineraryId);
        if (request == null || request.getDayId() == null || request.getItemType() == null
                || request.getPoiName() == null || request.getPoiName().isBlank()) {
            throw new BizException(400, "dayId、itemType、poiName 必填");
        }
        validateItemRequest(request);
        ItineraryDay day = dayMapper.selectOne(new LambdaQueryWrapper<ItineraryDay>()
                .eq(ItineraryDay::getId, request.getDayId())
                .eq(ItineraryDay::getItineraryId, itineraryId));
        if (day == null) {
            throw new BizException(404, "日期不存在");
        }
        versionService.createSnapshot(userId, itineraryId, "add_item", "新增行程项前快照");
        ItineraryItem entity = new ItineraryItem();
        entity.setDayId(request.getDayId());
        entity.setItineraryId(itineraryId);
        copyRequest(entity, request);
        entity.setSortNo(nextSort(request.getDayId()));
        itemMapper.insert(entity);

        chatService.invalidatePendingActions(userId, itineraryId);
        budgetEngine.recalculate(itineraryId);
        // 备选池：加入后标记 used，并按需在 AI 管家说中追加预约提醒
        applySuggestionUsed(itineraryId, request.getPoiId(), request.getPoiName(), true);
        versionService.createSnapshot(userId, itineraryId, "add_item", "新增行程项完成");
        return queryService.detail(userId, itineraryId);
    }

    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public ItineraryVO updateItem(Long userId, Long itemId, ItemUpsertRequest request) {
        ItineraryItem item = queryService.findOwnedItem(userId, itemId);
        if (request == null) {
            throw new BizException(400, "请求不能为空");
        }
        validateItemRequest(request);
        versionService.createSnapshot(userId, item.getItineraryId(), "update_item", "更新行程项前快照");
        if (request.getItemType() != null) {
            item.setItemType(request.getItemType());
        }
        if (request.getPoiName() != null && !request.getPoiName().isBlank()) {
            item.setPoiName(request.getPoiName());
        }
        copyOptionalFields(item, request);
        itemMapper.updateById(item);

        chatService.invalidatePendingActions(userId, item.getItineraryId());
        budgetEngine.recalculate(item.getItineraryId());
        versionService.createSnapshot(userId, item.getItineraryId(), "update_item", "更新行程项完成");
        return queryService.detail(userId, item.getItineraryId());
    }

    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public ItineraryVO deleteItem(Long userId, Long itemId) {
        ItineraryItem item = queryService.findOwnedItem(userId, itemId);
        versionService.createSnapshot(userId, item.getItineraryId(), "delete_item", "删除行程项前快照");
        itemMapper.deleteById(itemId);
        chatService.invalidatePendingActions(userId, item.getItineraryId());
        budgetEngine.recalculate(item.getItineraryId());
        // 备选池：删除后归还备选池（used=false），并移除对应的预约提醒
        applySuggestionUsed(item.getItineraryId(), item.getPoiId(), item.getPoiName(), false);
        versionService.createSnapshot(userId, item.getItineraryId(), "delete_item", "删除行程项完成");
        return queryService.detail(userId, item.getItineraryId());
    }

    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public ItineraryVO reorderItems(Long userId, Long itineraryId, Long dayId, List<Long> itemIds) {
        queryService.findOwnedMain(userId, itineraryId);
        if (dayId == null || itemIds == null) {
            throw new BizException(400, "日期和行程项顺序不能为空");
        }
        List<ItineraryItem> items = itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                .eq(ItineraryItem::getDayId, dayId)
                .eq(ItineraryItem::getItineraryId, itineraryId));
        Map<Long, ItineraryItem> itemsById = items.stream()
                .collect(java.util.stream.Collectors.toMap(ItineraryItem::getId, item -> item));
        if (itemIds.size() != items.size() || !itemsById.keySet().equals(new java.util.HashSet<>(itemIds))) {
            throw new BizException(400, "行程项顺序必须包含该日期的全部行程项");
        }
        versionService.createSnapshot(userId, itineraryId, "reorder", "调整行程顺序前快照");
        for (int index = 0; index < itemIds.size(); index++) {
            ItineraryItem item = itemsById.get(itemIds.get(index));
            item.setSortNo(index);
            itemMapper.updateById(item);
        }
        chatService.invalidatePendingActions(userId, itineraryId);
        budgetEngine.recalculate(itineraryId);
        versionService.createSnapshot(userId, itineraryId, "reorder", "调整行程顺序完成");
        return queryService.detail(userId, itineraryId);
    }

    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public Map<String, Object> nlEdit(Long userId, Long itineraryId, String instruction) {
        ItineraryMain main = queryService.findOwnedMain(userId, itineraryId);
        versionService.createSnapshot(userId, itineraryId, "nl_edit", "自然语言编辑前快照");
        List<ItineraryDay> days = dayMapper.selectList(new LambdaQueryWrapper<ItineraryDay>()
                .eq(ItineraryDay::getItineraryId, itineraryId).orderByAsc(ItineraryDay::getDayNo));
        Map<Integer, ItineraryDay> dayByNo = new HashMap<>();
        List<Map<String, Object>> plans = new ArrayList<>();
        for (ItineraryDay day : days) {
            dayByNo.put(day.getDayNo(), day);
            List<Map<String, Object>> compact = new ArrayList<>();
            for (ItineraryItem item : itemsOfDay(day)) {
                compact.add(new java.util.LinkedHashMap<>(Map.of(
                        "item_type", item.getItemType() == null ? "" : item.getItemType(),
                        "poi_name", item.getPoiName() == null ? "" : item.getPoiName(),
                        "start_time", item.getStartTime() == null ? "" : item.getStartTime())));
            }
            plans.add(new java.util.LinkedHashMap<>(Map.of("day_no", day.getDayNo(), "items", compact)));
        }

        JsonNode opsNode = agentService.editOps(main.getCity(), main.getDays(), plans, instruction);
        List<String> applied = new ArrayList<>();
        for (JsonNode op : opsNode) {
            String action = op.path("action").asText("");
            Integer dayNo = op.hasNonNull("day_no") ? op.get("day_no").asInt() : null;
            String poiName = op.path("poi_name").asText(null);
            String startTime = op.hasNonNull("start_time") ? op.get("start_time").asText() : null;
            String tier = op.hasNonNull("tier") ? op.get("tier").asText(null) : null;

            if ("upgrade_hotel".equals(action)) {
                if (upgradeHotel(itineraryId, main.getCity(), dayNo, tier)) {
                    applied.add("酒店已调整为" + (tier == null || tier.isBlank() ? "推荐档次" : tier));
                }
                continue;
            }
            if (("update_time".equals(action) || "move_day".equals(action))
                    && (dayNo == null || poiName == null)) {
                continue;
            }
            if (("delete".equals(action) || "add".equals(action)) && poiName == null) {
                continue;
            }
            ItineraryDay targetDay = dayNo == null ? null : dayByNo.get(dayNo);
            if (targetDay == null && !"delete".equals(action)) {
                continue;
            }

            switch (action) {
                case "delete" -> {
                    List<ItineraryItem> scope = targetDay != null ? itemsOfDay(targetDay)
                            : itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                                    .eq(ItineraryItem::getItineraryId, itineraryId));
                    ItineraryItem item = findItemByName(scope, poiName);
                    if (item != null) {
                        itemMapper.deleteById(item.getId());
                        applied.add("删除「" + poiName + "」");
                    }
                }
                case "update_time" -> {
                    if (startTime == null) continue;
                    ItineraryItem item = findItemByName(itemsOfDay(targetDay), poiName);
                    if (item != null) {
                        item.setStartTime(parseRequiredTime(startTime));
                        item.setEndTime(null);
                        itemMapper.updateById(item);
                        applied.add("第" + dayNo + "天「" + poiName + "」改为 " + startTime);
                    }
                }
                case "move_day" -> {
                    ItineraryItem item = findItemByName(itemsOfDay(targetDay), poiName);
                    if (item != null && targetDay != null) {
                        int destNo = Math.min(dayNo + 1, days.size());
                        ItineraryDay dest = dayByNo.get(destNo);
                        if (dest != null && !dest.getId().equals(targetDay.getId())) {
                            item.setDayId(dest.getId());
                            item.setSortNo(nextSort(dest.getId()));
                            itemMapper.updateById(item);
                            applied.add("「" + poiName + "」移到第" + destNo + "天");
                        }
                    }
                }
                case "add" -> {
                    ItineraryDay day = dayByNo.get(dayNo);
                    if (day == null) continue;
                    PoiKnowledge poi = poiKnowledgeMapper.selectOne(new LambdaQueryWrapper<PoiKnowledge>()
                            .eq(PoiKnowledge::getCity, main.getCity())
                            .eq(PoiKnowledge::getName, poiName).last("LIMIT 1"));
                    ItineraryItem entity = new ItineraryItem();
                    entity.setDayId(day.getId());
                    entity.setItineraryId(itineraryId);
                    entity.setItemType(poi != null ? poi.getCategory() : "attraction");
                    entity.setPoiName(poiName);
                    if (poi != null) {
                        entity.setPoiId(String.valueOf(poi.getId()));
                        entity.setAddress(poi.getAddress());
                        entity.setLatitude(poi.getLatitude());
                        entity.setLongitude(poi.getLongitude());
                        entity.setCost(poi.getTicketPrice());
                        entity.setDurationMin(poi.getDurationMin());
                        entity.setOpenTime(poi.getOpenTime());
                        entity.setSource(poi.getSource());
                        entity.setSourceUpdatedAt(poi.getSourceUpdatedAt());
                        entity.setVerificationStatus(poi.getSourceUpdatedAt() == null ? "unverified" : "partially_verified");
                        entity.setValueKind("observed");
                        entity.setFreshnessStatus(poi.getSourceUpdatedAt() == null ? "unknown" : "fresh");
                        entity.setReviewRequirement(poi.getSourceUpdatedAt() == null ? "before_departure" : "none");
                        entity.setTag(poi.getTags());
                    }
                    if (startTime != null) entity.setStartTime(parseRequiredTime(startTime));
                    entity.setSortNo(nextSort(day.getId()));
                    itemMapper.insert(entity);
                    applied.add("第" + dayNo + "天新增「" + poiName + "」");
                }
                default -> { }
            }
        }
        if (applied.isEmpty()) {
            throw new BizException(400, "未能从指令中解析出可执行的修改，请换个说法");
        }
        chatService.invalidatePendingActions(userId, itineraryId);
        budgetEngine.recalculate(itineraryId);
        versionService.createSnapshot(userId, itineraryId, "nl_edit", "自然语言编辑完成");
        return Map.of("applied", applied, "detail", queryService.detail(userId, itineraryId));
    }

    private static final String RESERVATION_REMINDER_PREFIX = "【预约提醒】";

    /**
     * 维护行程级备选池的 used 标记，并同步增删 AI 管家说（planNote）中的预约提醒。
     * 加入行程时：used=true；needReservation=true 的点位在 planNote 末尾追加提醒行。
     * 删除行程项时：used=false 归还备选池，并按名称移除对应提醒行。
     */
    private void applySuggestionUsed(Long itineraryId, String poiId, String poiName, boolean used) {
        ItineraryMain main = mainMapper.selectById(itineraryId);
        if (main == null) {
            return;
        }
        List<Map<String, Object>> suggestions = parseSuggestions(main.getSuggestionsJson());
        if (suggestions.isEmpty()) {
            return;
        }
        boolean changed = false;
        for (Map<String, Object> suggestion : suggestions) {
            String sugId = suggestion.get("poiId") == null ? "" : String.valueOf(suggestion.get("poiId"));
            String sugName = suggestion.get("name") == null ? "" : String.valueOf(suggestion.get("name"));
            boolean hit = (poiId != null && !poiId.isBlank() && poiId.equals(sugId))
                    || (poiName != null && !poiName.isBlank() && poiName.equals(sugName));
            if (!hit) {
                continue;
            }
            boolean currentUsed = Boolean.TRUE.equals(suggestion.get("used"));
            if (currentUsed != used) {
                suggestion.put("used", used);
                changed = true;
            }
            String note = main.getPlanNote() == null ? "" : main.getPlanNote();
            String marker = RESERVATION_REMINDER_PREFIX + "「" + sugName + "」";
            boolean needReservation = Boolean.TRUE.equals(suggestion.get("needReservation"));
            if (used && needReservation && !note.contains(marker)) {
                String line = marker + "通常需要提前预约或取票，建议出发前通过官方渠道/小程序确认。";
                main.setPlanNote(note.isBlank() ? line : note + "\n" + line);
                changed = true;
            } else if (!used && note.contains(marker)) {
                String cleaned = note.lines()
                        .filter(line -> !line.contains(marker))
                        .collect(java.util.stream.Collectors.joining("\n"));
                main.setPlanNote(cleaned.isBlank() ? null : cleaned);
                changed = true;
            }
        }
        if (!changed) {
            return;
        }
        try {
            main.setSuggestionsJson(objectMapper.writeValueAsString(suggestions));
        } catch (Exception ignored) {
            // 序列化失败时保留原 JSON，只影响 used 标记的持久化
        }
        mainMapper.updateById(main);
    }

    private List<Map<String, Object>> parseSuggestions(String json) {
        if (json == null || json.isBlank()) {
            return new ArrayList<>();
        }
        try {
            return objectMapper.readValue(json, new TypeReference<List<Map<String, Object>>>() {});
        } catch (Exception e) {
            log.warn("json column parse failed, returned empty list instead", e);
            return new ArrayList<>();
        }
    }

    private void copyRequest(ItineraryItem target, ItemUpsertRequest request) {
        target.setItemType(request.getItemType());
        target.setPoiName(request.getPoiName());
        copyOptionalFields(target, request);
    }

    private void copyOptionalFields(ItineraryItem target, ItemUpsertRequest request) {
        // 部分更新：null 表示「不改」，禁止把已有事实字段清空（旧编辑表单/局部 PUT）。
        if (request.getPoiId() != null) target.setPoiId(request.getPoiId());
        if (request.getAddress() != null) target.setAddress(request.getAddress());
        if (request.getLatitude() != null) target.setLatitude(request.getLatitude());
        if (request.getLongitude() != null) target.setLongitude(request.getLongitude());
        if (request.getStartTime() != null) target.setStartTime(request.getStartTime());
        if (request.getEndTime() != null) target.setEndTime(request.getEndTime());
        if (request.getDurationMin() != null) target.setDurationMin(request.getDurationMin());
        if (request.getCost() != null) target.setCost(request.getCost());
        if (request.getTag() != null) target.setTag(request.getTag());
        if (request.getRemark() != null) target.setRemark(request.getRemark());
        // 证据字段属于地点事实；旧版编辑表单不会回传这些字段，不能因
        // 更新时间/备注而把已有来源和核验状态清空。
        if (request.getOpenTime() != null) target.setOpenTime(request.getOpenTime());
        if (request.getImageUrl() != null) target.setImageUrl(request.getImageUrl());
        if (request.getSource() != null) target.setSource(request.getSource());
        if (request.getSourceUpdatedAt() != null) target.setSourceUpdatedAt(request.getSourceUpdatedAt());
        if (request.getVerificationStatus() != null) target.setVerificationStatus(request.getVerificationStatus());
        if (request.getValueKind() != null) target.setValueKind(request.getValueKind());
        if (request.getFreshnessStatus() != null) target.setFreshnessStatus(request.getFreshnessStatus());
        if (request.getReviewRequirement() != null) target.setReviewRequirement(request.getReviewRequirement());
        if (request.getFactEvidenceJson() != null) target.setFactEvidenceJson(request.getFactEvidenceJson());
    }

    private void validateItemRequest(ItemUpsertRequest request) {
        if (request.getItemType() != null
                && !List.of("attraction", "food", "hotel", "transport").contains(request.getItemType())) {
            throw new BizException(400, "行程项类型不合法");
        }
        if (request.getPoiName() != null && request.getPoiName().length() > 128) {
            throw new BizException(400, "地点名称过长");
        }
        if (request.getCost() != null && (request.getCost().signum() < 0
                || request.getCost().compareTo(new BigDecimal("1000000")) > 0)) {
            throw new BizException(400, "费用必须在 0 到 1000000 之间");
        }
        if (request.getDurationMin() != null
                && (request.getDurationMin() < 0 || request.getDurationMin() > 1440)) {
            throw new BizException(400, "时长必须在 0 到 1440 分钟之间");
        }
    }

    private List<ItineraryItem> itemsOfDay(ItineraryDay day) {
        if (day == null) return List.of();
        return itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                .eq(ItineraryItem::getDayId, day.getId()));
    }

    private ItineraryItem findItemByName(List<ItineraryItem> items, String name) {
        return items.stream().filter(item -> name != null && name.equals(item.getPoiName())).findFirst().orElse(null);
    }

    private LocalTime parseRequiredTime(String value) {
        try {
            return LocalTime.parse(value);
        } catch (Exception e) {
            throw new BizException(400, "时间格式必须为 HH:mm");
        }
    }

    private boolean upgradeHotel(Long itineraryId, String city, Integer dayNo, String tier) {
        List<ItineraryItem> scope;
        if (dayNo != null) {
            ItineraryDay day = dayMapper.selectOne(new LambdaQueryWrapper<ItineraryDay>()
                    .eq(ItineraryDay::getItineraryId, itineraryId)
                    .eq(ItineraryDay::getDayNo, dayNo));
            scope = itemsOfDay(day);
        } else {
            scope = itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                    .eq(ItineraryItem::getItineraryId, itineraryId));
        }
        ItineraryItem current = scope.stream().filter(item -> "hotel".equals(item.getItemType())).findFirst().orElse(null);
        if (current == null) return false;
        List<PoiKnowledge> hotels = poiKnowledgeMapper.selectList(new LambdaQueryWrapper<PoiKnowledge>()
                .eq(PoiKnowledge::getCity, city).eq(PoiKnowledge::getCategory, "hotel"));
        if (hotels.isEmpty()) return false;
        String[] keywords = hotelKeywords(tier);
        PoiKnowledge selected = hotels.stream()
                .filter(hotel -> !String.valueOf(hotel.getId()).equals(current.getPoiId()))
                .filter(hotel -> containsAny((hotel.getDescription() == null ? "" : hotel.getDescription())
                        + (hotel.getTags() == null ? "" : hotel.getTags()), keywords))
                .findFirst()
                .orElseGet(() -> hotels.stream()
                        .filter(hotel -> !String.valueOf(hotel.getId()).equals(current.getPoiId()))
                        .findFirst().orElse(hotels.get(0)));
        current.setPoiId(String.valueOf(selected.getId()));
        current.setPoiName(selected.getName());
        current.setAddress(selected.getAddress());
        current.setLatitude(selected.getLatitude());
        current.setLongitude(selected.getLongitude());
        current.setCost(selected.getTicketPrice());
        current.setDurationMin(selected.getDurationMin());
        current.setTag(selected.getTags());
        current.setRemark(selected.getDescription());
        itemMapper.updateById(current);
        return true;
    }

    private String[] hotelKeywords(String tier) {
        if (tier == null || tier.isBlank()) return new String[0];
        return switch (tier) {
            case "经济型" -> new String[]{"经济"};
            case "舒适型" -> new String[]{"舒适", "中端"};
            case "高档型" -> new String[]{"高端", "高档"};
            case "豪华型" -> new String[]{"高端", "五星", "国宾", "地标"};
            case "奢华型" -> new String[]{"国宾", "地标", "五星", "百年"};
            default -> new String[]{tier};
        };
    }

    private boolean containsAny(String text, String[] keywords) {
        if (keywords.length == 0) return true;
        for (String keyword : keywords) if (text.contains(keyword)) return true;
        return false;
    }

    private Integer nextSort(Long dayId) {
        return itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                        .eq(ItineraryItem::getDayId, dayId)).stream()
                .map(ItineraryItem::getSortNo).filter(sort -> sort != null)
                .max(Integer::compareTo).orElse(-1) + 1;
    }
}
