package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.travel.backend.common.BizException;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.entity.ItineraryVersion;
import com.travel.backend.mapper.ItineraryDayMapper;
import com.travel.backend.mapper.ItineraryItemMapper;
import com.travel.backend.mapper.ItineraryMainMapper;
import com.travel.backend.mapper.ItineraryVersionMapper;
import com.travel.backend.service.BudgetEngine;
import com.travel.backend.vo.ItineraryVO;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** 行程快照、版本列表、结构化 Diff 和恢复。 */
@Service
public class ItineraryVersionService {
    private final ItineraryVersionMapper versionMapper;
    private final ItineraryMainMapper mainMapper;
    private final ItineraryDayMapper dayMapper;
    private final ItineraryItemMapper itemMapper;
    private final ItineraryQueryService queryService;
    private final BudgetEngine budgetEngine;
    private final ObjectMapper objectMapper;
    private final CacheManager cacheManager;

    public ItineraryVersionService(ItineraryVersionMapper versionMapper, ItineraryMainMapper mainMapper,
                                   ItineraryDayMapper dayMapper, ItineraryItemMapper itemMapper,
                                   ItineraryQueryService queryService, BudgetEngine budgetEngine,
                                   ObjectMapper objectMapper, CacheManager cacheManager) {
        this.versionMapper = versionMapper;
        this.mainMapper = mainMapper;
        this.dayMapper = dayMapper;
        this.itemMapper = itemMapper;
        this.queryService = queryService;
        this.budgetEngine = budgetEngine;
        this.objectMapper = objectMapper;
        this.cacheManager = cacheManager;
    }

    @Transactional
    public Map<String, Object> createSnapshot(Long userId, Long itineraryId, String operation, String summary) {
        ItineraryMain main = queryService.findOwnedMain(userId, itineraryId);
        ItineraryVersion latest = latest(itineraryId);
        evictDetailCache();
        ItineraryVO detail = queryService.detail(userId, itineraryId);
        ItineraryVersion version = new ItineraryVersion();
        version.setItineraryId(itineraryId);
        version.setUserId(userId);
        version.setParentVersionId(latest == null ? null : latest.getId());
        version.setVersionNo(latest == null ? 1 : latest.getVersionNo() + 1);
        version.setOperation(operation == null || operation.isBlank() ? "snapshot" : operation);
        version.setSummary(summary == null ? "行程快照" : summary.substring(0, Math.min(255, summary.length())));
        try {
            version.setSnapshotJson(objectMapper.writeValueAsString(detail));
        } catch (Exception exc) {
            throw new BizException(500, "保存行程版本失败");
        }
        versionMapper.insert(version);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("id", version.getId());
        result.put("itineraryId", main.getId());
        result.put("versionNo", version.getVersionNo());
        result.put("parentVersionId", version.getParentVersionId());
        result.put("operation", version.getOperation());
        result.put("summary", version.getSummary());
        result.put("createdAt", version.getCreatedAt());
        return result;
    }

    public List<Map<String, Object>> list(Long userId, Long itineraryId) {
        queryService.findOwnedMain(userId, itineraryId);
        return versionMapper.selectList(new LambdaQueryWrapper<ItineraryVersion>()
                        .eq(ItineraryVersion::getItineraryId, itineraryId)
                        .orderByDesc(ItineraryVersion::getVersionNo))
                .stream().map(version -> {
                    Map<String, Object> result = new LinkedHashMap<>();
                    result.put("id", version.getId());
                    result.put("versionNo", version.getVersionNo());
                    result.put("parentVersionId", version.getParentVersionId());
                    result.put("operation", version.getOperation());
                    result.put("summary", version.getSummary());
                    result.put("createdAt", version.getCreatedAt());
                    return result;
                }).toList();
    }

    public Map<String, Object> diff(Long userId, Long itineraryId, Long fromId, Long toId) {
        queryService.findOwnedMain(userId, itineraryId);
        ItineraryVersion from = require(itineraryId, fromId);
        ItineraryVersion to = require(itineraryId, toId);
        try {
            JsonNode before = objectMapper.readTree(from.getSnapshotJson());
            JsonNode after = objectMapper.readTree(to.getSnapshotJson());
            List<Map<String, Object>> changes = new ArrayList<>();
            compareField(changes, "city", before, after);
            compareField(changes, "days", before, after);
            compareField(changes, "budget", before, after);
            Map<String, JsonNode> beforeItems = itemIndex(before.path("dayList"));
            Map<String, JsonNode> afterItems = itemIndex(after.path("dayList"));
            for (String key : beforeItems.keySet()) {
                if (!afterItems.containsKey(key)) changes.add(change("removed", key, beforeItems.get(key), null));
            }
            for (String key : afterItems.keySet()) {
                if (!beforeItems.containsKey(key)) changes.add(change("added", key, null, afterItems.get(key)));
                else if (!beforeItems.get(key).equals(afterItems.get(key))) {
                    changes.add(change("updated", key, beforeItems.get(key), afterItems.get(key)));
                }
            }
            return Map.of("fromVersionId", fromId, "toVersionId", toId, "changes", changes);
        } catch (Exception exc) {
            throw new BizException(500, "行程版本 Diff 失败");
        }
    }

    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public ItineraryVO restore(Long userId, Long itineraryId, Long versionId) {
        ItineraryMain main = queryService.findOwnedMain(userId, itineraryId);
        ItineraryVersion version = require(itineraryId, versionId);
        final ItineraryVO snapshot;
        try {
            snapshot = objectMapper.readValue(version.getSnapshotJson(), ItineraryVO.class);
        } catch (Exception exc) {
            throw new BizException(500, "行程版本内容损坏");
        }
        itemMapper.delete(new LambdaQueryWrapper<ItineraryItem>().eq(ItineraryItem::getItineraryId, itineraryId));
        dayMapper.delete(new LambdaQueryWrapper<ItineraryDay>().eq(ItineraryDay::getItineraryId, itineraryId));
        main.setTitle(snapshot.getTitle());
        main.setCity(snapshot.getCity());
        main.setStartDate(snapshot.getStartDate());
        main.setEndDate(snapshot.getEndDate());
        main.setDays(snapshot.getDays());
        main.setPersons(snapshot.getPersons());
        main.setBudget(snapshot.getBudget());
        main.setPreferences(snapshot.getPreferences());
        main.setHotelTier(snapshot.getHotelTier());
        main.setStayNights(snapshot.getStayNights());
        mainMapper.updateById(main);
        for (ItineraryVO.DayVO daySnapshot : snapshot.getDayList() == null ? List.<ItineraryVO.DayVO>of() : snapshot.getDayList()) {
            ItineraryDay day = new ItineraryDay();
            day.setItineraryId(itineraryId);
            day.setDayNo(daySnapshot.getDayNo());
            day.setTravelDate(daySnapshot.getTravelDate());
            day.setCity(snapshot.getCity());
            day.setNote(daySnapshot.getNote());
            try {
                Map<String, Object> metadata = new LinkedHashMap<>();
                if (daySnapshot.getTheme() != null) metadata.put("theme", daySnapshot.getTheme());
                if (daySnapshot.getMiniRoute() != null && !daySnapshot.getMiniRoute().isEmpty()) metadata.put("miniRoute", daySnapshot.getMiniRoute());
                if (daySnapshot.getBackupPlan() != null && !daySnapshot.getBackupPlan().isEmpty()) metadata.put("backupPlan", daySnapshot.getBackupPlan());
                if (daySnapshot.getPhotoSpots() != null && !daySnapshot.getPhotoSpots().isEmpty()) metadata.put("photoSpots", daySnapshot.getPhotoSpots());
                if (daySnapshot.getPracticalNotes() != null && !daySnapshot.getPracticalNotes().isEmpty()) metadata.put("practicalNotes", daySnapshot.getPracticalNotes());
                day.setMetadataJson(metadata.isEmpty() ? null : objectMapper.writeValueAsString(metadata));
            } catch (Exception ignored) {
                day.setMetadataJson(null);
            }
            day.setGenerationStatus("SUCCEEDED");
            dayMapper.insert(day);
            int sort = 0;
            for (ItineraryVO.TripItemVO itemSnapshot : daySnapshot.getItems() == null
                    ? List.<ItineraryVO.TripItemVO>of() : daySnapshot.getItems()) {
                ItineraryItem item = new ItineraryItem();
                item.setItineraryId(itineraryId);
                item.setDayId(day.getId());
                item.setItemType(itemSnapshot.getItemType());
                item.setPoiName(itemSnapshot.getPoiName());
                item.setPoiId(itemSnapshot.getPoiId());
                item.setAddress(itemSnapshot.getAddress());
                item.setLatitude(itemSnapshot.getLatitude());
                item.setLongitude(itemSnapshot.getLongitude());
                item.setStartTime(itemSnapshot.getStartTime());
                item.setEndTime(itemSnapshot.getEndTime());
                item.setDurationMin(itemSnapshot.getDurationMin());
                item.setCost(itemSnapshot.getCost());
                item.setTag(itemSnapshot.getTag());
                item.setRemark(itemSnapshot.getRemark());
                item.setOpenTime(itemSnapshot.getOpenTime());
                item.setImageUrl(itemSnapshot.getImageUrl());
                item.setSource(itemSnapshot.getSource());
                item.setSourceUpdatedAt(itemSnapshot.getSourceUpdatedAt());
                item.setVerificationStatus(itemSnapshot.getVerificationStatus());
                item.setValueKind(itemSnapshot.getValueKind());
                item.setFreshnessStatus(itemSnapshot.getFreshnessStatus());
                item.setReviewRequirement(itemSnapshot.getReviewRequirement());
                item.setFactEvidenceJson(itemSnapshot.getFactEvidenceJson());
                item.setIntro(itemSnapshot.getIntro());
                item.setSortNo(sort++);
                itemMapper.insert(item);
            }
        }
        budgetEngine.recalculate(itineraryId);
        createSnapshot(userId, itineraryId, "restore", "恢复到版本 " + version.getVersionNo());
        return queryService.detail(userId, itineraryId);
    }

    private ItineraryVersion latest(Long itineraryId) {
        return versionMapper.selectOne(new LambdaQueryWrapper<ItineraryVersion>()
                .eq(ItineraryVersion::getItineraryId, itineraryId)
                .orderByDesc(ItineraryVersion::getVersionNo).last("LIMIT 1"));
    }

    private ItineraryVersion require(Long itineraryId, Long versionId) {
        ItineraryVersion version = versionMapper.selectById(versionId);
        if (version == null || !itineraryId.equals(version.getItineraryId())) {
            throw new BizException(404, "行程版本不存在");
        }
        return version;
    }

    private void compareField(List<Map<String, Object>> changes, String field, JsonNode before, JsonNode after) {
        if (!before.path(field).equals(after.path(field))) changes.add(change("updated", field,
                before.path(field), after.path(field)));
    }

    private Map<String, JsonNode> itemIndex(JsonNode days) {
        Map<String, JsonNode> index = new LinkedHashMap<>();
        if (!days.isArray()) return index;
        for (JsonNode day : days) {
            int dayNo = day.path("dayNo").asInt();
            JsonNode items = day.path("items");
            if (items.isArray()) for (JsonNode item : items) {
                String key = dayNo + ":" + item.path("id").asText(item.path("poiName").asText());
                index.put(key, item);
            }
        }
        return index;
    }

    private Map<String, Object> change(String type, String key, JsonNode before, JsonNode after) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("type", type);
        result.put("key", key);
        result.put("before", before == null ? null : before);
        result.put("after", after == null ? null : after);
        return result;
    }

    private void evictDetailCache() {
        var cache = cacheManager.getCache("itinerary:detail");
        if (cache != null) cache.clear();
    }
}
