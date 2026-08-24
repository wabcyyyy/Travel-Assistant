package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.travel.backend.common.BizException;
import com.travel.backend.dto.AgentGenerateRequest;
import com.travel.backend.dto.AgentGenerateResponse;
import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.dto.ItemUpsertRequest;
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
import com.travel.backend.service.AgentService;
import com.travel.backend.service.BudgetEngine;

import java.util.List;
import java.util.Map;
import com.travel.backend.service.ItineraryService;
import com.travel.backend.vo.ItinerarySummaryVO;
import com.travel.backend.vo.ItineraryVO;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.List;

@Service
public class ItineraryServiceImpl implements ItineraryService {

    private final ItineraryMainMapper mainMapper;
    private final ItineraryDayMapper dayMapper;
    private final ItineraryItemMapper itemMapper;
    private final BudgetDetailMapper budgetMapper;
    private final AgentService agentService;
    private final BudgetEngine budgetEngine;
    private final com.travel.backend.mapper.PoiKnowledgeMapper poiKnowledgeMapper;
    private final ItineraryAsyncPlanner planner;

    public ItineraryServiceImpl(ItineraryMainMapper mainMapper, ItineraryDayMapper dayMapper,
                                ItineraryItemMapper itemMapper, BudgetDetailMapper budgetMapper,
                                AgentService agentService, BudgetEngine budgetEngine,
                                com.travel.backend.mapper.PoiKnowledgeMapper poiKnowledgeMapper,
                                ItineraryAsyncPlanner planner) {
        this.mainMapper = mainMapper;
        this.dayMapper = dayMapper;
        this.itemMapper = itemMapper;
        this.budgetMapper = budgetMapper;
        this.agentService = agentService;
        this.budgetEngine = budgetEngine;
        this.poiKnowledgeMapper = poiKnowledgeMapper;
        this.planner = planner;
    }

    @Override
    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public ItineraryVO generate(Long userId, GenerateRequest request) {
        // 立即建单：主表 status=1(生成中)，预创建 N 个空日，逐日由异步规划器填充
        ItineraryMain main = new ItineraryMain();
        main.setUserId(userId);
        main.setTitle(request.getCity() + request.getDays() + "日游（生成中）");
        main.setCity(request.getCity());
        main.setStartDate(request.getStartDate());
        main.setEndDate(request.getEndDate());
        main.setDays(request.getDays());
        main.setPersons(request.getPersons());
        main.setBudget(request.getBudget());
        main.setPreferences(request.getPreferences() == null ? null : String.join(",", request.getPreferences()));
        main.setStatus(1);
        mainMapper.insert(main);

        for (int dayNo = 1; dayNo <= request.getDays(); dayNo++) {
            ItineraryDay day = new ItineraryDay();
            day.setItineraryId(main.getId());
            day.setDayNo(dayNo);
            day.setCity(request.getCity());
            day.setTravelDate(request.getStartDate() == null ? null
                    : request.getStartDate().plusDays(dayNo - 1));
            dayMapper.insert(day);
        }

        planner.planDays(userId, main.getId(), request);
        return detail(userId, main.getId());
    }

    @Override
    public List<ItinerarySummaryVO> list(Long userId) {
        List<ItineraryMain> mains = mainMapper.selectList(
                new LambdaQueryWrapper<ItineraryMain>()
                        .eq(ItineraryMain::getUserId, userId)
                        .orderByDesc(ItineraryMain::getId));
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
            vo.setCreatedAt(main.getCreatedAt());
            vo.setTotalAmount(sumAmount(findBudgetList(main.getId())));
            result.add(vo);
        }
        return result;
    }

    @Override
    @Cacheable(cacheNames = "itinerary:detail", key = "#id")
    public ItineraryVO detail(Long userId, Long id) {
        ItineraryMain main = findOwnedMain(userId, id);

        List<ItineraryDay> days = dayMapper.selectList(
                new LambdaQueryWrapper<ItineraryDay>()
                        .eq(ItineraryDay::getItineraryId, id)
                        .orderByAsc(ItineraryDay::getDayNo));
        List<ItineraryVO.DayVO> dayVOList = new ArrayList<>();
        for (ItineraryDay day : days) {
            ItineraryVO.DayVO dayVO = new ItineraryVO.DayVO();
            dayVO.setDayId(day.getId());
            dayVO.setDayNo(day.getDayNo());
            dayVO.setTravelDate(day.getTravelDate());
            dayVO.setNote(day.getNote());
            dayVO.setItems(new ArrayList<>());
            List<ItineraryItem> items = itemMapper.selectList(
                    new LambdaQueryWrapper<ItineraryItem>()
                            .eq(ItineraryItem::getDayId, day.getId())
                            .orderByAsc(ItineraryItem::getSortNo));
            for (ItineraryItem item : items) {
                dayVO.getItems().add(toItemVO(item));
            }
            dayVOList.add(dayVO);
        }

        List<BudgetDetail> budgets = findBudgetList(id);
        List<ItineraryVO.BudgetVO> budgetVOList = budgets.stream().map(this::toBudgetVO).toList();

        ItineraryVO vo = toVO(main);
        vo.setDayList(dayVOList);
        vo.setBudgetList(budgetVOList);
        vo.setTotalAmount(sumAmount(budgets));
        return vo;
    }

    @Override
    @Transactional
    public void delete(Long userId, Long id) {
        findOwnedMain(userId, id);
        dayMapper.delete(new LambdaQueryWrapper<ItineraryDay>().eq(ItineraryDay::getItineraryId, id));
        itemMapper.delete(new LambdaQueryWrapper<ItineraryItem>().eq(ItineraryItem::getItineraryId, id));
        budgetMapper.delete(new LambdaQueryWrapper<BudgetDetail>().eq(BudgetDetail::getItineraryId, id));
        mainMapper.deleteById(id);
    }

    @Override
    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public ItineraryVO addItem(Long userId, Long itineraryId, ItemUpsertRequest request) {
        findOwnedMain(userId, itineraryId);
        if (request.getDayId() == null || request.getItemType() == null
                || request.getPoiName() == null || request.getPoiName().isBlank()) {
            throw new BizException(400, "dayId、itemType、poiName 必填");
        }
        ItineraryDay day = dayMapper.selectOne(new LambdaQueryWrapper<ItineraryDay>()
                .eq(ItineraryDay::getId, request.getDayId())
                .eq(ItineraryDay::getItineraryId, itineraryId));
        if (day == null) {
            throw new BizException(404, "日期不存在");
        }
        Integer maxSort = itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                        .eq(ItineraryItem::getDayId, request.getDayId()))
                .stream().map(ItineraryItem::getSortNo)
                .filter(sort -> sort != null)
                .max(Integer::compareTo).orElse(-1);

        ItineraryItem entity = new ItineraryItem();
        entity.setDayId(request.getDayId());
        entity.setItineraryId(itineraryId);
        entity.setItemType(request.getItemType());
        entity.setPoiName(request.getPoiName());
        entity.setPoiId(request.getPoiId());
        entity.setAddress(request.getAddress());
        entity.setLatitude(request.getLatitude());
        entity.setLongitude(request.getLongitude());
        entity.setStartTime(request.getStartTime());
        entity.setEndTime(request.getEndTime());
        entity.setDurationMin(request.getDurationMin());
        entity.setCost(request.getCost());
        entity.setTag(request.getTag());
        entity.setRemark(request.getRemark());
        entity.setSortNo(maxSort + 1);
        itemMapper.insert(entity);

        budgetEngine.recalculate(itineraryId);
        return detail(userId, itineraryId);
    }

    @Override
    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public ItineraryVO updateItem(Long userId, Long itemId, ItemUpsertRequest request) {
        ItineraryItem item = findOwnedItem(userId, itemId);
        if (request.getItemType() != null) {
            item.setItemType(request.getItemType());
        }
        if (request.getPoiName() != null && !request.getPoiName().isBlank()) {
            item.setPoiName(request.getPoiName());
        }
        item.setPoiId(request.getPoiId());
        item.setAddress(request.getAddress());
        item.setLatitude(request.getLatitude());
        item.setLongitude(request.getLongitude());
        item.setStartTime(request.getStartTime());
        item.setEndTime(request.getEndTime());
        item.setDurationMin(request.getDurationMin());
        item.setCost(request.getCost());
        item.setTag(request.getTag());
        item.setRemark(request.getRemark());
        itemMapper.updateById(item);

        budgetEngine.recalculate(item.getItineraryId());
        return detail(userId, item.getItineraryId());
    }

    @Override
    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public ItineraryVO deleteItem(Long userId, Long itemId) {
        ItineraryItem item = findOwnedItem(userId, itemId);
        itemMapper.deleteById(itemId);
        budgetEngine.recalculate(item.getItineraryId());
        return detail(userId, item.getItineraryId());
    }

    @Override
    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public ItineraryVO reorderItems(Long userId, Long itineraryId, Long dayId, List<Long> itemIds) {
        findOwnedMain(userId, itineraryId);
        List<ItineraryItem> items = itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                .eq(ItineraryItem::getDayId, dayId)
                .eq(ItineraryItem::getItineraryId, itineraryId));
        for (int index = 0; index < itemIds.size(); index++) {
            for (ItineraryItem item : items) {
                if (item.getId().equals(itemIds.get(index))) {
                    item.setSortNo(index);
                    itemMapper.updateById(item);
                    break;
                }
            }
        }
        budgetEngine.recalculate(itineraryId);
        return detail(userId, itineraryId);
    }

    private ItineraryItem findOwnedItem(Long userId, Long itemId) {
        ItineraryItem item = itemMapper.selectById(itemId);
        if (item == null) {
            throw new BizException(404, "行程项不存在");
        }
        findOwnedMain(userId, item.getItineraryId());
        return item;
    }

    private ItineraryMain findOwnedMain(Long userId, Long id) {
        ItineraryMain main = mainMapper.selectById(id);
        if (main == null || !main.getUserId().equals(userId)) {
            throw new BizException(404, "行程不存在");
        }
        return main;
    }

    private List<BudgetDetail> findBudgetList(Long itineraryId) {
        return budgetMapper.selectList(
                new LambdaQueryWrapper<BudgetDetail>()
                        .eq(BudgetDetail::getItineraryId, itineraryId));
    }

    private BigDecimal sumAmount(List<BudgetDetail> budgets) {
        return budgets.stream()
                .map(BudgetDetail::getAmount)
                .filter(amount -> amount != null)
                .reduce(BigDecimal.ZERO, BigDecimal::add);
    }

    private AgentGenerateRequest toAgentRequest(GenerateRequest request) {
        AgentGenerateRequest agentRequest = new AgentGenerateRequest();
        agentRequest.setCity(request.getCity());
        agentRequest.setDays(request.getDays());
        agentRequest.setPersons(request.getPersons());
        agentRequest.setBudget(request.getBudget());
        agentRequest.setStartDate(request.getStartDate());
        agentRequest.setPreferences(request.getPreferences());
        agentRequest.setHotelTier(request.getHotelTier());
        return agentRequest;
    }

    private ItineraryItem toEntity(Long dayId, Long itineraryId, AgentGenerateResponse.Item item, int sortNo) {
        ItineraryItem entity = new ItineraryItem();
        entity.setDayId(dayId);
        entity.setItineraryId(itineraryId);
        entity.setItemType(item.getItemType() == null ? "attraction" : item.getItemType());
        entity.setPoiName(item.getPoiName());
        entity.setPoiId(item.getPoiId());
        entity.setAddress(item.getAddress());
        entity.setLatitude(item.getLatitude());
        entity.setLongitude(item.getLongitude());
        entity.setStartTime(parseTime(item.getStartTime()));
        entity.setEndTime(parseTime(item.getEndTime()));
        entity.setDurationMin(item.getDurationMin());
        entity.setCost(item.getCost());
        entity.setTag(item.getTag());
        entity.setRemark(item.getRemark());
        entity.setSortNo(sortNo);
        return entity;
    }

    private LocalTime parseTime(String time) {
        if (time == null || time.isBlank()) {
            return null;
        }
        try {
            return LocalTime.parse(time);
        } catch (Exception e) {
            return null;
        }
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
        vo.setSortNo(item.getSortNo());
        return vo;
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
        vo.setId(main.getId());
        vo.setTitle(main.getTitle());
        vo.setCity(main.getCity());
        vo.setStartDate(main.getStartDate());
        vo.setEndDate(main.getEndDate());
        vo.setDays(main.getDays());
        vo.setPersons(main.getPersons());
        vo.setBudget(main.getBudget());
        vo.setPreferences(main.getPreferences());
        vo.setStatus(main.getStatus());
        return vo;
    }

    @Override
    public Map<String, Object> clarify(String message, Map<String, Object> slots) {
        JsonNode node = agentService.clarify(message, slots);
        Map<String, Object> out = new java.util.HashMap<>();
        out.put("slots", node.get("slots"));
        out.put("missing", node.get("missing"));
        out.put("question", node.path("question").asText(null));
        out.put("ready", node.path("ready").asBoolean(false));
        return out;
    }

    @Override
    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public Map<String, Object> nlEdit(Long userId, Long itineraryId, String instruction) {
        ItineraryMain main = findOwnedMain(userId, itineraryId);
        List<ItineraryDay> days = dayMapper.selectList(new LambdaQueryWrapper<ItineraryDay>()
                .eq(ItineraryDay::getItineraryId, itineraryId).orderByAsc(ItineraryDay::getDayNo));
        Map<Long, ItineraryDay> dayById = new java.util.HashMap<>();
        Map<Integer, ItineraryDay> dayByNo = new java.util.HashMap<>();
        List<Map<String, Object>> plans = new java.util.ArrayList<>();
        for (ItineraryDay day : days) {
            dayById.put(day.getId(), day);
            dayByNo.put(day.getDayNo(), day);
            List<ItineraryItem> items = itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                    .eq(ItineraryItem::getDayId, day.getId()).orderByAsc(ItineraryItem::getSortNo));
            List<Map<String, Object>> compact = new java.util.ArrayList<>();
            for (ItineraryItem item : items) {
                compact.add(new java.util.LinkedHashMap<>(Map.of(
                        "item_type", item.getItemType() == null ? "" : item.getItemType(),
                        "poi_name", item.getPoiName() == null ? "" : item.getPoiName(),
                        "start_time", item.getStartTime() == null ? "" : item.getStartTime())));
            }
            plans.add(new java.util.LinkedHashMap<>(Map.of("day_no", day.getDayNo(), "items", compact)));
        }

        JsonNode opsNode = agentService.editOps(main.getCity(), main.getDays(), plans, instruction);
        List<String> applied = new java.util.ArrayList<>();
        int dayCount = days.size();
        for (JsonNode op : opsNode) {
            String action = op.path("action").asText("");
            Integer dayNo = op.hasNonNull("day_no") ? op.get("day_no").asInt() : null;
            String poiName = op.path("poi_name").asText(null);
            String startTime = op.hasNonNull("start_time") ? op.get("start_time").asText() : null;

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
                    List<ItineraryItem> scope = targetDay != null
                            ? itemsOfDay(targetDay)
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
                        item.setStartTime(java.time.LocalTime.parse(startTime));
                        item.setEndTime(null);
                        itemMapper.updateById(item);
                        applied.add("第" + dayNo + "天「" + poiName + "」改为 " + startTime);
                    }
                }
                case "move_day" -> {
                    ItineraryItem item = findItemByName(itemsOfDay(targetDay), poiName);
                    if (item != null && dayNo != null && targetDay != null) {
                        Integer destNo = Math.min(dayNo + 1, dayCount);
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
                    if (dayNo == null || poiName == null || dayByNo.get(dayNo) == null) continue;
                    ItineraryDay day = dayByNo.get(dayNo);
                    PoiKnowledge poi = poiKnowledgeMapper.selectOne(
                            new LambdaQueryWrapper<PoiKnowledge>()
                                    .eq(PoiKnowledge::getCity, main.getCity())
                                    .eq(PoiKnowledge::getName, poiName)
                                    .last("LIMIT 1"));
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
                        entity.setTag(poi.getTags());
                    }
                    if (startTime != null) {
                        entity.setStartTime(java.time.LocalTime.parse(startTime));
                    }
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
        budgetEngine.recalculate(itineraryId);
        ItineraryVO vo = detail(userId, itineraryId);
        return Map.of("applied", applied, "detail", vo);
    }

    private List<ItineraryItem> itemsOfDay(ItineraryDay day) {
        if (day == null) {
            return List.of();
        }
        return itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                .eq(ItineraryItem::getDayId, day.getId()));
    }

    private ItineraryItem findItemByName(List<ItineraryItem> items, String name) {
        return items.stream()
                .filter(i -> name.equals(i.getPoiName()))
                .findFirst().orElse(null);
    }

    private Integer nextSort(Long dayId) {
        return itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                        .eq(ItineraryItem::getDayId, dayId)).stream()
                .map(ItineraryItem::getSortNo).filter(s -> s != null)
                .max(Integer::compareTo).orElse(-1) + 1;
    }
}