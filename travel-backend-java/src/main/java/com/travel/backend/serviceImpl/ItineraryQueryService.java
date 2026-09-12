package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.travel.backend.common.BizException;
import com.travel.backend.entity.BudgetDetail;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.entity.PoiKnowledge;
import com.travel.backend.mapper.BudgetDetailMapper;
import com.travel.backend.mapper.ItineraryDayMapper;
import com.travel.backend.mapper.ItineraryItemMapper;
import com.travel.backend.mapper.ItineraryMainMapper;
import com.travel.backend.mapper.PoiKnowledgeMapper;
import com.travel.backend.vo.ItinerarySummaryVO;
import com.travel.backend.vo.ItineraryVO;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * 行程只读查询与展示模型组装。
 *
 * 将查询从写操作、Agent 调用和草稿应用中隔离，保证详情缓存和查询优化
 * 不需要触碰行程修改事务。
 */
@Service
public class ItineraryQueryService {

    private final ItineraryMainMapper mainMapper;
    private final ItineraryDayMapper dayMapper;
    private final ItineraryItemMapper itemMapper;
    private final BudgetDetailMapper budgetMapper;
    private final PoiKnowledgeMapper poiKnowledgeMapper;
    private final ObjectMapper objectMapper;

    public ItineraryQueryService(ItineraryMainMapper mainMapper, ItineraryDayMapper dayMapper,
                                 ItineraryItemMapper itemMapper, BudgetDetailMapper budgetMapper,
                                 PoiKnowledgeMapper poiKnowledgeMapper, ObjectMapper objectMapper) {
        this.mainMapper = mainMapper;
        this.dayMapper = dayMapper;
        this.itemMapper = itemMapper;
        this.budgetMapper = budgetMapper;
        this.poiKnowledgeMapper = poiKnowledgeMapper;
        this.objectMapper = objectMapper;
    }

    public List<ItinerarySummaryVO> list(Long userId) {
        List<ItineraryMain> mains = mainMapper.selectList(
                new LambdaQueryWrapper<ItineraryMain>()
                        .eq(ItineraryMain::getUserId, userId)
                        .orderByDesc(ItineraryMain::getId));
        Map<Long, BigDecimal> totals = mains.isEmpty() ? Map.of()
                : budgetMapper.selectList(new LambdaQueryWrapper<BudgetDetail>()
                                .in(BudgetDetail::getItineraryId,
                                        mains.stream().map(ItineraryMain::getId).toList()))
                        .stream().collect(Collectors.groupingBy(
                                BudgetDetail::getItineraryId,
                                Collectors.reducing(
                                        BigDecimal.ZERO,
                                        detail -> detail.getAmount() == null ? BigDecimal.ZERO : detail.getAmount(),
                                        BigDecimal::add)));

        List<ItinerarySummaryVO> result = new ArrayList<>();
        for (ItineraryMain main : mains) {
            ItinerarySummaryVO vo = new ItinerarySummaryVO();
            vo.setId(main.getId());
            vo.setTitle(main.getTitle());
            vo.setCity(main.getCity());
            vo.setStartDate(main.getStartDate());
            vo.setEndDate(main.getEndDate());
            vo.setDays(main.getDays());
            vo.setPersons(main.getPersons());
            vo.setBudget(main.getBudget());
            vo.setStatus(main.getStatus());
            vo.setTripTheme(main.getTripTheme());
            vo.setCreatedAt(main.getCreatedAt());
            vo.setTotalAmount(totals.getOrDefault(main.getId(), BigDecimal.ZERO));
            result.add(vo);
        }
        return result;
    }

    @Cacheable(cacheNames = "itinerary:detail", key = "#userId + ':' + #id")
    public ItineraryVO detail(Long userId, Long id) {
        ItineraryMain main = findOwnedMain(userId, id);
        List<ItineraryDay> days = dayMapper.selectList(
                new LambdaQueryWrapper<ItineraryDay>()
                        .eq(ItineraryDay::getItineraryId, id)
                        .orderByAsc(ItineraryDay::getDayNo));

        // 一次查询整条行程的项目，避免原实现按天查询产生 N+1 次数据库访问。
        List<ItineraryItem> allItems = itemMapper.selectList(
                new LambdaQueryWrapper<ItineraryItem>()
                        .eq(ItineraryItem::getItineraryId, id)
                        .orderByAsc(ItineraryItem::getDayId)
                        .orderByAsc(ItineraryItem::getSortNo));
        Map<Long, List<ItineraryItem>> itemsByDay = allItems.stream()
                .collect(Collectors.groupingBy(ItineraryItem::getDayId));

        List<ItineraryVO.DayVO> dayVOList = new ArrayList<>();
        for (ItineraryDay day : days) {
            ItineraryVO.DayVO dayVO = new ItineraryVO.DayVO();
            dayVO.setDayId(day.getId());
            dayVO.setDayNo(day.getDayNo());
            dayVO.setTravelDate(day.getTravelDate());
            dayVO.setNote(day.getNote());
            applyDayMetadata(dayVO, day.getMetadataJson());
            dayVO.setItems(itemsByDay.getOrDefault(day.getId(), List.of()).stream()
                    .map(this::toItemVO)
                    .collect(Collectors.toCollection(ArrayList::new)));
            dayVOList.add(dayVO);
        }

        List<BudgetDetail> budgets = findBudgetList(id);
        List<ItineraryVO.BudgetVO> budgetVOList = budgets.stream().map(this::toBudgetVO).toList();

        // 只查询当前行程实际涉及的 POI，避免加载整个城市的知识库。
        List<String> itemNames = allItems.stream()
                .map(ItineraryItem::getPoiName)
                .filter(name -> name != null && !name.isBlank())
                .distinct()
                .toList();
        Map<String, String> descMap = new HashMap<>();
        if (!itemNames.isEmpty()) {
            poiKnowledgeMapper.selectList(new LambdaQueryWrapper<PoiKnowledge>()
                            .eq(PoiKnowledge::getCity, main.getCity())
                            .in(PoiKnowledge::getName, itemNames))
                    .forEach(p -> descMap.put(p.getName(), p.getDescription()));
        }
        Map<String, ItineraryItem> introSource = allItems.stream()
                .filter(item -> item.getPoiName() != null)
                .collect(Collectors.toMap(ItineraryItem::getPoiName, item -> item, (first, ignored) -> first));
        for (ItineraryVO.DayVO dayVO : dayVOList) {
            for (ItineraryVO.TripItemVO itemVO : dayVO.getItems()) {
                itemVO.setDescription(descMap.get(itemVO.getPoiName()));
                ItineraryItem source = introSource.get(itemVO.getPoiName());
                itemVO.setIntro(source == null ? null : source.getIntro());
            }
        }

        ItineraryVO vo = toVO(main);
        vo.setSuggestions(parseSuggestions(main.getSuggestionsJson()));
        vo.setDayList(dayVOList);
        vo.setStayNights((int) dayVOList.stream()
                .filter(day -> day.getItems().stream().anyMatch(item -> "hotel".equals(item.getItemType())))
                .count());
        vo.setBudgetList(budgetVOList);
        vo.setTotalAmount(sumAmount(budgets));
        vo.setDestinationStatus(resolveDestinationStatus(allItems));
        vo.setSources(buildSourceRecords(allItems));
        int pendingFacts = (int) allItems.stream()
                .filter(item -> item.getReviewRequirement() == null
                        || !"none".equals(item.getReviewRequirement())
                        || "stale".equals(item.getFreshnessStatus()))
                .count();
        vo.setPendingFactCount(pendingFacts);
        boolean hasStaleFacts = allItems.stream()
                .anyMatch(item -> "stale".equals(item.getFreshnessStatus()));
        boolean hasIncompleteDay = days.stream()
                .anyMatch(day -> "PENDING".equals(day.getGenerationStatus())
                        || "RUNNING".equals(day.getGenerationStatus()));
        boolean hasFailedDay = days.stream()
                .anyMatch(day -> "FAILED".equals(day.getGenerationStatus())
                        || "TIMED_OUT_UNKNOWN".equals(day.getGenerationStatus()));
        String qualityStatus;
        if ((main.getStatus() != null && main.getStatus() == 3) || hasFailedDay) {
            qualityStatus = "BLOCKED";
        } else if (hasIncompleteDay || (main.getStatus() != null && main.getStatus() == 1)) {
            qualityStatus = "DRAFT";
        } else if (allItems.isEmpty()) {
            qualityStatus = "BLOCKED";
        } else if (hasStaleFacts) {
            qualityStatus = "STALE";
        } else {
            qualityStatus = pendingFacts > 0 ? "READY_WITH_WARNINGS" : "READY";
        }
        vo.setQualityStatus(qualityStatus);
        vo.setQualityRuleVersion("travel-quality-1.0");
        vo.setQualityReport(buildQualityReport(qualityStatus,
                qualityRuleIssues(qualityStatus, days, allItems, pendingFacts), pendingFacts));
        return vo;
    }

    private Map<String, Object> buildQualityReport(String status, List<Map<String, Object>> issues,
                                                    int pendingFacts) {
        List<Map<String, Object>> blocking = "BLOCKED".equals(status)
                ? issues : List.of();
        List<Map<String, Object>> warnings = "READY_WITH_WARNINGS".equals(status)
                || "STALE".equals(status) ? issues : List.of();
        Map<String, Object> report = new HashMap<>();
        report.put("qualityStatus", status);
        report.put("qualityRuleVersion", "travel-quality-1.0");
        report.put("blockingIssues", blocking);
        report.put("warnings", warnings);
        report.put("metrics", Map.of("pendingFactCount", pendingFacts));
        return report;
    }

    private List<Map<String, Object>> qualityRuleIssues(String status, List<ItineraryDay> days,
                                                         List<ItineraryItem> items, int pendingFacts) {
        List<Map<String, Object>> issues = new ArrayList<>();
        if ("BLOCKED".equals(status)) {
            if (items.isEmpty()) issues.add(issue("NO_ITINERARY_ITEMS", "没有可交付的行程地点"));
            if (days.stream().anyMatch(day -> "FAILED".equals(day.getGenerationStatus())
                    || "TIMED_OUT_UNKNOWN".equals(day.getGenerationStatus()))) {
                issues.add(issue("DAY_GENERATION_FAILED", "至少一天的行程生成失败"));
            }
        } else if (pendingFacts > 0) {
            issues.add(issue("FACT_REQUIRES_REVIEW", pendingFacts + " 项事实需要出发前复核"));
        }
        return issues;
    }

    private Map<String, Object> issue(String code, String message) {
        return Map.of("code", code, "message", message);
    }

    private List<Map<String, Object>> buildSourceRecords(List<ItineraryItem> items) {
        Map<String, Map<String, Object>> records = new java.util.LinkedHashMap<>();
        for (ItineraryItem item : items) {
            String source = item.getSource();
            if (source == null || source.isBlank()) continue;
            Map<String, Object> record = records.computeIfAbsent(source, key -> {
                Map<String, Object> value = new java.util.LinkedHashMap<>();
                value.put("sourceId", key);
                value.put("storageSource", key);
                value.put("provider", key);
                return value;
            });
            if (item.getSourceUpdatedAt() != null) {
                record.putIfAbsent("retrievedAt", item.getSourceUpdatedAt());
            }
        }
        return new ArrayList<>(records.values());
    }

    private String resolveDestinationStatus(List<ItineraryItem> items) {
        if (items.isEmpty()) return "draft_only";
        boolean hasOpenResearch = items.stream()
                .anyMatch(item -> "llm.open_day".equals(item.getSource()));
        if (hasOpenResearch) {
            boolean hasAuthoritativeFact = items.stream()
                    .anyMatch(item -> item.getSource() != null
                            && !"llm.open_day".equals(item.getSource()));
            return hasAuthoritativeFact ? "researched" : "draft_only";
        }
        return "knowledge_backed";
    }

    private void applyDayMetadata(ItineraryVO.DayVO dayVO, String metadataJson) {
        if (metadataJson == null || metadataJson.isBlank()) return;
        try {
            Map<String, Object> metadata = objectMapper.readValue(metadataJson,
                    new TypeReference<Map<String, Object>>() {});
            dayVO.setTheme(asString(metadata.get("theme")));
            dayVO.setMiniRoute(asMap(metadata.get("miniRoute")));
            dayVO.setBackupPlan(asMapList(metadata.get("backupPlan")));
            dayVO.setPhotoSpots(asMapList(metadata.get("photoSpots")));
            dayVO.setPracticalNotes(asStringList(metadata.get("practicalNotes")));
            // dayOptions（M3 叙事契约）：不透出即 V4 槽位空转——metadataJson 已落库但前端拿不到
            dayVO.setDayOptions(asMapList(metadata.get("dayOptions")));
        } catch (Exception ignored) {
            // 旧数据或损坏的可选元数据不应阻塞详情读取。
        }
    }

    private String asString(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> asMap(Object value) {
        return value instanceof Map<?, ?> map ? (Map<String, Object>) map : null;
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> asMapList(Object value) {
        return value instanceof List<?> list ? (List<Map<String, Object>>) (List<?>) list : null;
    }

    private List<String> asStringList(Object value) {
        if (!(value instanceof List<?> list)) return null;
        return list.stream().map(this::asString).filter(v -> v != null).toList();
    }

    public ItineraryMain findOwnedMain(Long userId, Long id) {
        ItineraryMain main = mainMapper.selectById(id);
        if (main == null || !main.getUserId().equals(userId)) {
            throw new BizException(404, "行程不存在");
        }
        return main;
    }

    public ItineraryItem findOwnedItem(Long userId, Long itemId) {
        ItineraryItem item = itemMapper.selectById(itemId);
        if (item == null) {
            throw new BizException(404, "行程项不存在");
        }
        findOwnedMain(userId, item.getItineraryId());
        return item;
    }

    public List<BudgetDetail> findBudgetList(Long itineraryId) {
        return budgetMapper.selectList(
                new LambdaQueryWrapper<BudgetDetail>()
                        .eq(BudgetDetail::getItineraryId, itineraryId));
    }

    public BigDecimal sumAmount(List<BudgetDetail> budgets) {
        return budgets.stream()
                .map(BudgetDetail::getAmount)
                .filter(amount -> amount != null)
                .reduce(BigDecimal.ZERO, BigDecimal::add);
    }

    private ItineraryVO.TripItemVO toItemVO(ItineraryItem item) {
        ItineraryVO.TripItemVO vo = new ItineraryVO.TripItemVO();
        vo.setId(item.getId());
        vo.setItemType(item.getItemType());
        vo.setPoiName(item.getPoiName());
        vo.setPoiId(item.getPoiId());
        vo.setAddress(item.getAddress());
        vo.setLatitude(item.getLatitude());
        vo.setLongitude(item.getLongitude());
        vo.setStartTime(item.getStartTime());
        vo.setEndTime(item.getEndTime());
        vo.setDurationMin(item.getDurationMin());
        vo.setCost(item.getCost());
        vo.setTag(item.getTag());
        vo.setRemark(item.getRemark());
        // 叙事理由（M3-③）：读 why_note 列，快照/前端随 VO 携带
        vo.setWhyThis(item.getWhyNote());
        vo.setOpenTime(item.getOpenTime());
        vo.setImage(item.getImageUrl());
        vo.setImageUrl(item.getImageUrl());
        vo.setSource(item.getSource());
        vo.setSourceUpdatedAt(item.getSourceUpdatedAt());
        vo.setVerificationStatus(item.getVerificationStatus());
        vo.setValueKind(item.getValueKind());
        vo.setFreshnessStatus(item.getFreshnessStatus());
        vo.setReviewRequirement(item.getReviewRequirement());
        vo.setFactEvidenceJson(item.getFactEvidenceJson());
        vo.setFactEvidence(parseFactEvidence(item.getFactEvidenceJson()));
        vo.setSortNo(item.getSortNo());
        return vo;
    }

    private Map<String, Object> parseFactEvidence(String json) {
        if (json == null || json.isBlank()) return null;
        try {
            return objectMapper.readValue(json, new TypeReference<Map<String, Object>>() {});
        } catch (Exception ignored) {
            return null;
        }
    }

    private List<Map<String, Object>> parseSuggestions(String json) {
        if (json == null || json.isBlank()) return List.of();
        try {
            return objectMapper.readValue(json, new TypeReference<List<Map<String, Object>>>() {});
        } catch (Exception ignored) {
            // 旧数据或损坏的可选备选池不应阻塞详情读取。
            return List.of();
        }
    }

    private ItineraryVO.BudgetVO toBudgetVO(BudgetDetail budget) {
        ItineraryVO.BudgetVO vo = new ItineraryVO.BudgetVO();
        vo.setCategory(budget.getCategory());
        vo.setAmount(budget.getAmount());
        vo.setItemCount(budget.getItemCount());
        return vo;
    }

    private ItineraryVO toVO(ItineraryMain main) {
        ItineraryVO vo = new ItineraryVO();
        vo.setSchemaVersion("1.0");
        vo.setId(main.getId());
        vo.setTitle(main.getTitle());
        vo.setCity(main.getCity());
        vo.setStartDate(main.getStartDate());
        vo.setEndDate(main.getEndDate());
        vo.setDays(main.getDays());
        vo.setPersons(main.getPersons());
        vo.setBudget(main.getBudget());
        vo.setPreferences(main.getPreferences());
        vo.setHotelTier(main.getHotelTier());
        vo.setStatus(main.getStatus());
        vo.setPlanNote(main.getPlanNote());
        // 整趟主题标题（M3-③）：生成阶段由编排层单列捕获
        vo.setTripTheme(main.getTripTheme());
        return vo;
    }
}
