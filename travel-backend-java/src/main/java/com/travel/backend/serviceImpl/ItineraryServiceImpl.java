package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.travel.backend.common.BizException;
import com.travel.backend.dto.AgentGenerateRequest;
import com.travel.backend.dto.AgentGenerateResponse;
import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.dto.HotelOptionApplyRequest;
import com.travel.backend.dto.ItemUpsertRequest;
import com.travel.backend.entity.BudgetDetail;
import com.travel.backend.entity.HotelRoomType;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryChatMessage;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.entity.PoiKnowledge;
import com.travel.backend.mapper.BudgetDetailMapper;
import com.travel.backend.mapper.HotelRoomTypeMapper;
import com.travel.backend.mapper.ItineraryDayMapper;
import com.travel.backend.mapper.ItineraryChatMessageMapper;
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
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
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
    private final HotelRoomTypeMapper hotelRoomTypeMapper;
    private final ItineraryChatMessageMapper chatMessageMapper;
    private final ItineraryAsyncPlanner planner;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public ItineraryServiceImpl(ItineraryMainMapper mainMapper, ItineraryDayMapper dayMapper,
                                ItineraryItemMapper itemMapper, BudgetDetailMapper budgetMapper,
                                AgentService agentService, BudgetEngine budgetEngine,
                                com.travel.backend.mapper.PoiKnowledgeMapper poiKnowledgeMapper,
                                HotelRoomTypeMapper hotelRoomTypeMapper,
                                ItineraryChatMessageMapper chatMessageMapper,
                                ItineraryAsyncPlanner planner) {
        this.mainMapper = mainMapper;
        this.dayMapper = dayMapper;
        this.itemMapper = itemMapper;
        this.budgetMapper = budgetMapper;
        this.agentService = agentService;
        this.budgetEngine = budgetEngine;
        this.poiKnowledgeMapper = poiKnowledgeMapper;
        this.hotelRoomTypeMapper = hotelRoomTypeMapper;
        this.chatMessageMapper = chatMessageMapper;
        this.planner = planner;
    }

    @Override
    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    public ItineraryVO generate(Long userId, GenerateRequest request) {
        if (request.getPersons() == null || request.getPersons() < 1 || request.getPersons() > 20) {
            throw new BizException(400, "出行人数必须在 1 到 20 人之间");
        }
        if (request.getStartDate() != null && request.getEndDate() != null) {
            if (request.getEndDate().isBefore(request.getStartDate())) {
                throw new BizException(400, "结束日期不能早于开始日期");
            }
            long dateDays = java.time.temporal.ChronoUnit.DAYS.between(
                    request.getStartDate(), request.getEndDate()) + 1;
            if (dateDays != request.getDays()) {
                throw new BizException(400, "日期范围与行程天数不一致");
            }
        }
        int stayNights = request.getStayNights() == null
                ? Math.max(request.getDays() - 1, 0) : request.getStayNights();
        if (stayNights < 0 || stayNights > request.getDays()) {
            throw new BizException(400, "住宿晚数必须在 0 到行程天数之间");
        }
        request.setStayNights(stayNights);
        // 立即建单：主表 status=1(生成中)，预创建 N 个空日，逐日由异步规划器填充。
        // 注意：不能加 @Transactional——异步任务必须在壳数据提交后才启动，否则查不到单。
        ItineraryMain main = new ItineraryMain();
        main.setUserId(userId);
        main.setTitle(request.getCity() + request.getDays() + "日游");
        main.setCity(request.getCity());
        main.setStartDate(request.getStartDate());
        main.setEndDate(request.getEndDate());
        main.setDays(request.getDays());
        main.setPersons(request.getPersons());
        main.setBudget(request.getBudget());
        main.setPreferences(request.getPreferences() == null ? null : String.join(",", request.getPreferences()));
        main.setHotelTier(request.getHotelTier());
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

        // 上下文一次构建（知识库城市有候选；未知城市走开放模式由 LLM 安排）
        JsonNode context = agentService.planContext(request.getCity(), request.getPreferences());

        planner.planDays(userId, main.getId(), request, context);
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
    @Cacheable(cacheNames = "itinerary:detail", key = "#userId + ':' + #id")
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

        // 知识库简介回填（按城市一次查询，名称匹配）
        Map<String, String> descMap = new java.util.HashMap<>();
        poiKnowledgeMapper.selectList(new LambdaQueryWrapper<PoiKnowledge>()
                        .eq(PoiKnowledge::getCity, main.getCity()))
                .forEach(p -> descMap.put(p.getName(), p.getDescription()));
        Map<String, ItineraryItem> introSource = new java.util.HashMap<>();
        itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                        .eq(ItineraryItem::getItineraryId, id))
                .forEach(i -> introSource.put(i.getPoiName(), i));
        for (ItineraryVO.DayVO dayVO : dayVOList) {
            for (ItineraryVO.TripItemVO itemVO : dayVO.getItems()) {
                itemVO.setDescription(descMap.get(itemVO.getPoiName()));
                ItineraryItem src = introSource.get(itemVO.getPoiName());
                itemVO.setIntro(src != null ? src.getIntro() : null);
            }
        }

        ItineraryVO vo = toVO(main);
        vo.setDayList(dayVOList);
        vo.setStayNights((int) dayVOList.stream()
                .filter(day -> day.getItems().stream().anyMatch(item -> "hotel".equals(item.getItemType())))
                .count());
        vo.setBudgetList(budgetVOList);
        vo.setTotalAmount(sumAmount(budgets));
        return vo;
    }

    @Override
    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public void delete(Long userId, Long id) {
        findOwnedMain(userId, id);
        dayMapper.delete(new LambdaQueryWrapper<ItineraryDay>().eq(ItineraryDay::getItineraryId, id));
        itemMapper.delete(new LambdaQueryWrapper<ItineraryItem>().eq(ItineraryItem::getItineraryId, id));
        budgetMapper.delete(new LambdaQueryWrapper<BudgetDetail>().eq(BudgetDetail::getItineraryId, id));
        chatMessageMapper.delete(new LambdaQueryWrapper<ItineraryChatMessage>()
                .eq(ItineraryChatMessage::getItineraryId, id));
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
        validateItemRequest(request);
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

        invalidatePendingActions(userId, itineraryId);
        budgetEngine.recalculate(itineraryId);
        return detail(userId, itineraryId);
    }

    @Override
    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public ItineraryVO updateItem(Long userId, Long itemId, ItemUpsertRequest request) {
        ItineraryItem item = findOwnedItem(userId, itemId);
        validateItemRequest(request);
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

        invalidatePendingActions(userId, item.getItineraryId());
        budgetEngine.recalculate(item.getItineraryId());
        return detail(userId, item.getItineraryId());
    }

    @Override
    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public ItineraryVO deleteItem(Long userId, Long itemId) {
        ItineraryItem item = findOwnedItem(userId, itemId);
        itemMapper.deleteById(itemId);
        invalidatePendingActions(userId, item.getItineraryId());
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
        invalidatePendingActions(userId, itineraryId);
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
        vo.setHotelTier(main.getHotelTier());
        vo.setStatus(main.getStatus());
        vo.setPlanNote(main.getPlanNote());
        return vo;
    }

    @Override
    public List<String> supportedCities() {
        return poiKnowledgeMapper.selectList(new LambdaQueryWrapper<PoiKnowledge>()
                        .select(true, PoiKnowledge::getCity))
                .stream().map(PoiKnowledge::getCity).distinct().sorted().toList();
    }

    @Override
    public Map<String, Object> cityGuide(String input, List<Map<String, Object>> history) {
        JsonNode node = agentService.cityGuide(Map.of(
                "input", input == null ? "" : input,
                "supported", supportedCities(),
                "history", history == null ? List.of() : history));
        Map<String, Object> out = new java.util.HashMap<>();
        out.put("kind", node.path("kind").asText("unclear"));
        out.put("city", node.hasNonNull("city") ? node.get("city").asText() : null);
        out.put("message", node.path("message").asText("想去哪里玩？说说你的想法～"));
        List<Map<String, Object>> sugs = new java.util.ArrayList<>();
        node.path("suggestions").forEach(s -> {
            if (s.hasNonNull("name")) {
                sugs.add(Map.of("name", s.get("name").asText(),
                        "reason", s.path("reason").asText("")));
            }
        });
        out.put("suggestions", sugs);
        return out;
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
                        item.setStartTime(parseRequiredTime(startTime));
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
                        entity.setStartTime(parseRequiredTime(startTime));
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
        invalidatePendingActions(userId, itineraryId);
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

    private java.time.LocalTime parseRequiredTime(String value) {
        try {
            return java.time.LocalTime.parse(value);
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
        ItineraryItem current = scope.stream()
                .filter(i -> "hotel".equals(i.getItemType()))
                .findFirst().orElse(null);
        if (current == null) {
            return false;
        }

        List<PoiKnowledge> hotels = poiKnowledgeMapper.selectList(new LambdaQueryWrapper<PoiKnowledge>()
                .eq(PoiKnowledge::getCity, city)
                .eq(PoiKnowledge::getCategory, "hotel"));
        if (hotels.isEmpty()) {
            return false;
        }
        String[] keywords = hotelKeywords(tier);
        PoiKnowledge selected = hotels.stream()
                .filter(h -> !String.valueOf(h.getId()).equals(current.getPoiId()))
                .filter(h -> containsAny((h.getDescription() == null ? "" : h.getDescription())
                        + (h.getTags() == null ? "" : h.getTags()), keywords))
                .findFirst()
                .orElseGet(() -> hotels.stream()
                        .filter(h -> !String.valueOf(h.getId()).equals(current.getPoiId()))
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
        if (tier == null || tier.isBlank()) {
            return new String[0];
        }
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
        if (keywords.length == 0) {
            return true;
        }
        for (String keyword : keywords) {
            if (text.contains(keyword)) {
                return true;
            }
        }
        return false;
    }

    private Integer nextSort(Long dayId) {
        return itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                        .eq(ItineraryItem::getDayId, dayId)).stream()
                .map(ItineraryItem::getSortNo).filter(s -> s != null)
                .max(Integer::compareTo).orElse(-1) + 1;
    }

    @Override
    public Map<String, Object> chatEdit(Long userId, Long itineraryId, String message,
                                        List<Map<String, Object>> history) {
        ItineraryMain main = findOwnedMain(userId, itineraryId);
        List<Map<String, Object>> persistedHistory = chatHistory(userId, itineraryId);
        List<Map<String, Object>> effectiveHistory = persistedHistory.isEmpty()
                ? (history == null ? List.of() : history)
                : persistedHistory.stream()
                .map(item -> Map.<String, Object>of(
                        "role", item.getOrDefault("role", "ai"),
                        "content", item.getOrDefault("content", "")))
                .toList();
        List<Map<String, Object>> persistedPlans = currentPlans(itineraryId);
        String baseRevision = planRevision(persistedPlans);
        List<Map<String, Object>> plans = latestPendingPlans(userId, itineraryId, baseRevision);
        if (plans.isEmpty()) {
            plans = persistedPlans;
        }
        /*
         * plans 由数据库权威状态构造。草稿/酒店候选都会携带该签名，应用时再次计算，
         * 从而阻止另一个标签页或手工编辑后的旧草稿覆盖新行程。
         */
        Map<String, Object> chatBody = new java.util.HashMap<>();
        chatBody.put("city", main.getCity());
        chatBody.put("days", main.getDays());
        chatBody.put("persons", main.getPersons() == null ? 1 : main.getPersons());
        chatBody.put("budget", main.getBudget() == null ? null : main.getBudget().doubleValue());
        List<BudgetDetail> currentBudgets = findBudgetList(itineraryId);
        chatBody.put("current_total", sumAmount(currentBudgets).doubleValue());
        chatBody.put("current_hotel_total", currentBudgets.stream()
                .filter(b -> "酒店".equals(b.getCategory()))
                .map(BudgetDetail::getAmount).filter(java.util.Objects::nonNull)
                .reduce(BigDecimal.ZERO, BigDecimal::add).doubleValue());
        chatBody.put("start_date", main.getStartDate() == null ? null : main.getStartDate().toString());
        chatBody.put("end_date", main.getEndDate() == null ? null : main.getEndDate().toString());
        chatBody.put("preferences", main.getPreferences() == null ? List.of()
                : List.of(main.getPreferences().split(",")));
        chatBody.put("hotel_tier", main.getHotelTier());
        chatBody.put("plans", plans);
        chatBody.put("history", effectiveHistory.size() <= 20 ? effectiveHistory
                : effectiveHistory.subList(effectiveHistory.size() - 20, effectiveHistory.size()));
        chatBody.put("message", message == null ? "" : message);
        JsonNode node = agentService.chatTurn(chatBody);
        Map<String, Object> out = new java.util.HashMap<>();
        out.put("reply", node.path("reply").asText("已更新草稿"));
        out.put("changed", node.path("changed").asBoolean(false));
        List<Object> responsePlans = attachBaseRevision(objectMapperTreeList(node.get("plans")), baseRevision, false);
        List<Object> responseHotelOptions = attachBaseRevision(
                objectMapperTreeList(node.get("hotelOptions")), baseRevision, true);
        out.put("plans", responsePlans);
        out.put("hotelOptions", responseHotelOptions);
        out.put("baseRevision", baseRevision);
        out.put("requiresConfirmation", node.path("requiresConfirmation").asBoolean(false));
        out.put("planDocument", node.get("planDocument"));
        out.put("operations", objectMapperTreeList(node.get("operations")));
        out.put("pendingAction", node.get("pendingAction"));
        saveChatMessage(userId, itineraryId, "user", message, List.of(), List.of(), false);
        if (Boolean.TRUE.equals(out.get("changed")) || !responseHotelOptions.isEmpty()) {
            invalidatePendingActions(userId, itineraryId);
        }
        ItineraryChatMessage aiMessage = saveChatMessage(userId, itineraryId, "ai", String.valueOf(out.get("reply")),
                (List<?>) out.get("plans"), (List<?>) out.get("hotelOptions"),
                Boolean.TRUE.equals(out.get("changed")));
        out.put("messageId", aiMessage.getId());
        return out;
    }

    @Override
    public List<Map<String, Object>> chatHistory(Long userId, Long itineraryId) {
        findOwnedMain(userId, itineraryId);
        List<ItineraryChatMessage> messages = chatMessageMapper.selectList(
                new LambdaQueryWrapper<ItineraryChatMessage>()
                        .eq(ItineraryChatMessage::getItineraryId, itineraryId)
                        .eq(ItineraryChatMessage::getUserId, userId)
                        .orderByDesc(ItineraryChatMessage::getId)
                        .last("LIMIT 100"));
        java.util.Collections.reverse(messages);
        return messages
                .stream().map(message -> {
                    Map<String, Object> item = new java.util.LinkedHashMap<>();
                    item.put("id", message.getId());
                    item.put("role", message.getRole());
                    item.put("content", message.getContent());
                    item.put("plans", readJsonList(message.getPlansJson()));
                    item.put("hotelOptions", readJsonList(message.getHotelOptionsJson()));
                    item.put("changed", Integer.valueOf(1).equals(message.getChanged()));
                    item.put("baseRevision", actionBaseRevision(message));
                    item.put("createdAt", message.getCreatedAt());
                    return item;
                }).toList();
    }

    @Override
    @Transactional
    public void clearChatHistory(Long userId, Long itineraryId) {
        findOwnedMain(userId, itineraryId);
        chatMessageMapper.delete(new LambdaQueryWrapper<ItineraryChatMessage>()
                .eq(ItineraryChatMessage::getItineraryId, itineraryId)
                .eq(ItineraryChatMessage::getUserId, userId));
    }

    private ItineraryChatMessage saveChatMessage(Long userId, Long itineraryId, String role, String content,
                                                  List<?> plans, List<?> hotelOptions, boolean changed) {
        ItineraryChatMessage message = new ItineraryChatMessage();
        message.setItineraryId(itineraryId);
        message.setUserId(userId);
        message.setRole(role);
        message.setContent(content == null ? "" : content);
        message.setPlansJson(writeJson(plans));
        message.setHotelOptionsJson(writeJson(hotelOptions));
        message.setChanged(changed ? 1 : 0);
        chatMessageMapper.insert(message);
        return message;
    }

    private List<Map<String, Object>> currentPlans(Long itineraryId) {
        List<Map<String, Object>> plans = new java.util.ArrayList<>();
        for (ItineraryDay day : dayMapper.selectList(new LambdaQueryWrapper<ItineraryDay>()
                .eq(ItineraryDay::getItineraryId, itineraryId).orderByAsc(ItineraryDay::getDayNo))) {
            List<Map<String, Object>> items = new java.util.ArrayList<>();
            for (ItineraryItem item : itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                    .eq(ItineraryItem::getDayId, day.getId()).orderByAsc(ItineraryItem::getSortNo))) {
                Map<String, Object> im = new java.util.LinkedHashMap<>();
                im.put("id", item.getId());
                im.put("item_type", item.getItemType());
                im.put("poi_name", item.getPoiName());
                im.put("poi_id", item.getPoiId());
                im.put("address", item.getAddress());
                im.put("latitude", item.getLatitude());
                im.put("longitude", item.getLongitude());
                im.put("start_time", item.getStartTime() == null ? null : item.getStartTime().toString());
                im.put("end_time", item.getEndTime() == null ? null : item.getEndTime().toString());
                im.put("duration_min", item.getDurationMin());
                im.put("cost", item.getCost());
                im.put("tag", item.getTag());
                im.put("remark", item.getRemark());
                im.put("sort_no", item.getSortNo());
                items.add(im);
            }
            Map<String, Object> pm = new java.util.LinkedHashMap<>();
            pm.put("day_no", day.getDayNo());
            pm.put("note", day.getNote());
            pm.put("items", items);
            plans.add(pm);
        }
        return plans;
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> latestPendingPlans(Long userId, Long itineraryId, String baseRevision) {
        return chatMessageMapper.selectList(new LambdaQueryWrapper<ItineraryChatMessage>()
                        .eq(ItineraryChatMessage::getItineraryId, itineraryId)
                        .eq(ItineraryChatMessage::getUserId, userId)
                        .eq(ItineraryChatMessage::getRole, "ai")
                        .eq(ItineraryChatMessage::getChanged, 1)
                        .orderByDesc(ItineraryChatMessage::getId))
                .stream()
                .filter(message -> baseRevision.equals(actionBaseRevision(message)))
                .findFirst()
                .map(message -> readJsonList(message.getPlansJson()).stream()
                        .map(row -> (Map<String, Object>) objectMapper.convertValue(row, Map.class))
                        .toList())
                .orElse(List.of());
    }

    private String planRevision(List<Map<String, Object>> plans) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(writeJson(plans).getBytes(StandardCharsets.UTF_8));
            return java.util.HexFormat.of().formatHex(digest);
        } catch (java.security.NoSuchAlgorithmException e) {
            throw new BizException(500, "无法生成行程版本标识");
        }
    }

    @SuppressWarnings("unchecked")
    private List<Object> attachBaseRevision(List<Object> rows, String baseRevision, boolean camelCase) {
        List<Object> result = new java.util.ArrayList<>();
        for (Object row : rows) {
            Map<String, Object> map = objectMapper.convertValue(row, java.util.LinkedHashMap.class);
            map.put(camelCase ? "baseRevision" : "_baseRevision", baseRevision);
            result.add(map);
        }
        return result;
    }

    private void invalidatePendingActions(Long userId, Long itineraryId) {
        List<ItineraryChatMessage> messages = chatMessageMapper.selectList(
                new LambdaQueryWrapper<ItineraryChatMessage>()
                        .eq(ItineraryChatMessage::getItineraryId, itineraryId)
                        .eq(ItineraryChatMessage::getUserId, userId)
                        .eq(ItineraryChatMessage::getRole, "ai"));
        for (ItineraryChatMessage message : messages) {
            if (hasActionPayload(message)) {
                consumePendingAction(message);
            }
        }
    }

    private boolean hasActionPayload(ItineraryChatMessage message) {
        return Integer.valueOf(1).equals(message.getChanged())
                || !readJsonList(message.getPlansJson()).isEmpty()
                || !readJsonList(message.getHotelOptionsJson()).isEmpty();
    }

    private void consumePendingAction(ItineraryChatMessage message) {
        message.setPlansJson("[]");
        message.setHotelOptionsJson("[]");
        message.setChanged(0);
        chatMessageMapper.updateById(message);
    }

    private String actionBaseRevision(ItineraryChatMessage message) {
        List<Object> plans = readJsonList(message.getPlansJson());
        if (!plans.isEmpty() && plans.get(0) instanceof Map<?, ?> map) {
            Object revision = map.get("_baseRevision");
            return revision == null ? null : String.valueOf(revision);
        }
        List<Object> options = readJsonList(message.getHotelOptionsJson());
        if (!options.isEmpty() && options.get(0) instanceof Map<?, ?> map) {
            Object revision = map.get("baseRevision");
            return revision == null ? null : String.valueOf(revision);
        }
        return null;
    }

    private ItineraryChatMessage requirePendingAction(Long userId, Long itineraryId,
                                                       Long messageId, String baseRevision,
                                                       boolean hotelAction) {
        if (messageId == null || baseRevision == null || baseRevision.isBlank()) {
            throw new BizException(409, "该方案缺少版本信息，请重新生成后再应用");
        }
        ItineraryChatMessage message = chatMessageMapper.selectOne(
                new LambdaQueryWrapper<ItineraryChatMessage>()
                        .eq(ItineraryChatMessage::getId, messageId)
                        .eq(ItineraryChatMessage::getItineraryId, itineraryId)
                        .eq(ItineraryChatMessage::getUserId, userId)
                        .eq(ItineraryChatMessage::getRole, "ai")
                        .last("LIMIT 1"));
        List<Object> payload = message == null ? List.of() : readJsonList(
                hotelAction ? message.getHotelOptionsJson() : message.getPlansJson());
        if (message == null || payload.isEmpty()) {
            throw new BizException(409, "该方案已失效，请使用最新建议");
        }
        ItineraryChatMessage latest = chatMessageMapper.selectList(
                        new LambdaQueryWrapper<ItineraryChatMessage>()
                                .eq(ItineraryChatMessage::getItineraryId, itineraryId)
                                .eq(ItineraryChatMessage::getUserId, userId)
                                .eq(ItineraryChatMessage::getRole, "ai")
                                .orderByDesc(ItineraryChatMessage::getId))
                .stream().filter(this::hasActionPayload).findFirst().orElse(null);
        if (latest == null || !latest.getId().equals(message.getId())) {
            throw new BizException(409, "该方案已被更新的建议取代，请使用最新方案");
        }
        String currentRevision = planRevision(currentPlans(itineraryId));
        if (!baseRevision.equals(actionBaseRevision(message)) || !baseRevision.equals(currentRevision)) {
            consumePendingAction(message);
            throw new BizException(409, "行程已发生变化，该方案已失效，请重新生成建议");
        }
        return message;
    }

    @SuppressWarnings("unchecked")
    private void validateHotelChoice(ItineraryChatMessage message, String hotelName, String roomName) {
        for (Object rawOption : readJsonList(message.getHotelOptionsJson())) {
            if (!(rawOption instanceof Map<?, ?> option)
                    || !hotelName.equals(String.valueOf(option.get("hotelName")))) {
                continue;
            }
            Object rawRooms = option.get("roomTypes");
            if (rawRooms instanceof List<?> rooms && rooms.stream().anyMatch(rawRoom ->
                    rawRoom instanceof Map<?, ?> room
                            && roomName.equals(String.valueOf(room.get("roomName"))))) {
                return;
            }
        }
        throw new BizException(409, "所选酒店或房型不属于当前有效方案，请重新获取建议");
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value == null ? List.of() : value);
        } catch (com.fasterxml.jackson.core.JsonProcessingException e) {
            throw new BizException(500, "保存对话上下文失败");
        }
    }

    private List<Object> readJsonList(String value) {
        if (value == null || value.isBlank()) {
            return List.of();
        }
        try {
            return objectMapper.readValue(value,
                    objectMapper.getTypeFactory().constructCollectionType(List.class, Object.class));
        } catch (com.fasterxml.jackson.core.JsonProcessingException e) {
            return List.of();
        }
    }

    private List<Object> objectMapperTreeList(JsonNode arr) {
        List<Object> list = new java.util.ArrayList<>();
        if (arr != null && arr.isArray()) {
            arr.forEach(n -> list.add(n));
        }
        return list;
    }

    @Override
    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public ItineraryVO applyPlans(Long userId, Long itineraryId, List<Map<String, Object>> plans,
                                  Long actionMessageId, String baseRevision) {
        ItineraryMain main = findOwnedMain(userId, itineraryId);
        ItineraryChatMessage actionMessage = requirePendingAction(
                userId, itineraryId, actionMessageId, baseRevision, false);
        plans = readJsonList(actionMessage.getPlansJson()).stream()
                .map(row -> objectMapper.convertValue(row, Map.class))
                .map(row -> (Map<String, Object>) row)
                .toList();
        List<ItineraryDay> days = dayMapper.selectList(new LambdaQueryWrapper<ItineraryDay>()
                .eq(ItineraryDay::getItineraryId, itineraryId).orderByAsc(ItineraryDay::getDayNo));
        validatePlans(plans, days);
        Map<Long, ItineraryItem> existingItems = itemMapper.selectList(
                        new LambdaQueryWrapper<ItineraryItem>()
                                .eq(ItineraryItem::getItineraryId, itineraryId))
                .stream().collect(java.util.stream.Collectors.toMap(ItineraryItem::getId, item -> item));
        java.util.Set<Long> retainedItemIds = new java.util.HashSet<>();
        Map<Integer, ItineraryDay> dayByNo = new java.util.HashMap<>();
        for (ItineraryDay day : days) {
            dayByNo.put(day.getDayNo(), day);
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
                if (name == null || name.isBlank() || "null".equals(name)) {
                    continue;
                }
                PoiKnowledge poi = poiKnowledgeMapper.selectOne(new LambdaQueryWrapper<PoiKnowledge>()
                        .eq(PoiKnowledge::getCity, main.getCity())
                        .eq(PoiKnowledge::getName, name)
                        .last("LIMIT 1"));
                ItineraryItem existing = null;
                if (item.get("id") instanceof Number itemId) {
                    existing = existingItems.get(itemId.longValue());
                }
                ItineraryItem e = existing == null ? new ItineraryItem() : existing;
                e.setDayId(day.getId());
                e.setItineraryId(itineraryId);
                e.setItemType(str(item.get("item_type"), poi != null ? poi.getCategory() : "attraction"));
                e.setPoiName(name);
                if (poi != null) {
                    e.setPoiId(String.valueOf(poi.getId()));
                    e.setAddress(poi.getAddress());
                    e.setLatitude(poi.getLatitude());
                    e.setLongitude(poi.getLongitude());
                    e.setCost(poi.getTicketPrice());
                    e.setDurationMin(poi.getDurationMin());
                    e.setTag(poi.getTags());
                }
                if (existing != null && name.equals(existing.getPoiName())) {
                    // LLM 只维护计划结构；既有项目的权威价格始终沿用数据库值。
                    e.setCost(existing.getCost());
                }
                java.time.LocalTime st = parseTime(item.get("start_time"));
                java.time.LocalTime et = parseTime(item.get("end_time"));
                e.setStartTime(st);
                e.setEndTime(et);
                if (item.get("duration_min") instanceof Number n) {
                    e.setDurationMin(n.intValue());
                }
                e.setTag(str(item.get("tag"), e.getTag()));
                e.setRemark(str(item.get("remark"), e.getRemark()));
                e.setSortNo(sortNo++);
                if (existing == null) {
                    itemMapper.insert(e);
                } else {
                    retainedItemIds.add(existing.getId());
                    itemMapper.updateById(e);
                }
            }
        }
        for (Long existingId : existingItems.keySet()) {
            if (!retainedItemIds.contains(existingId)) {
                itemMapper.deleteById(existingId);
            }
        }
        budgetEngine.recalculate(itineraryId);
        consumePendingAction(actionMessage);
        return detail(userId, itineraryId);
    }

    @Override
    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    @Transactional
    public ItineraryVO applyHotelOption(Long userId, Long itineraryId, HotelOptionApplyRequest request) {
        ItineraryMain main = findOwnedMain(userId, itineraryId);
        ItineraryChatMessage actionMessage = requirePendingAction(
                userId, itineraryId, request.getActionMessageId(), request.getBaseRevision(), true);
        if (request.getHotelName() == null || request.getHotelName().isBlank()
                || request.getHotelName().length() > 128) {
            throw new BizException(400, "酒店名称不合法");
        }
        PoiKnowledge hotel = poiKnowledgeMapper.selectOne(new LambdaQueryWrapper<PoiKnowledge>()
                .eq(PoiKnowledge::getCity, main.getCity())
                .eq(PoiKnowledge::getCategory, "hotel")
                .eq(PoiKnowledge::getName, request.getHotelName())
                .last("LIMIT 1"));
        if (hotel == null) {
            throw new BizException(404, "未找到该城市的酒店候选");
        }
        validateHotelChoice(actionMessage, request.getHotelName(), request.getRoomType());
        List<ItineraryItem> hotelItems = itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                .eq(ItineraryItem::getItineraryId, itineraryId)
                .eq(ItineraryItem::getItemType, "hotel"));
        List<ItineraryDay> itineraryDays = dayMapper.selectList(new LambdaQueryWrapper<ItineraryDay>()
                .eq(ItineraryDay::getItineraryId, itineraryId));
        Map<Long, ItineraryDay> dayById = itineraryDays.stream()
                .collect(java.util.stream.Collectors.toMap(ItineraryDay::getId, day -> day));
        Map<Integer, ItineraryDay> dayByNo = itineraryDays.stream()
                .collect(java.util.stream.Collectors.toMap(ItineraryDay::getDayNo, day -> day));
        java.util.Set<Integer> existingHotelDayNos = hotelItems.stream()
                .map(item -> dayById.get(item.getDayId()))
                .filter(java.util.Objects::nonNull)
                .map(ItineraryDay::getDayNo)
                .collect(java.util.stream.Collectors.toSet());
        java.util.Set<Integer> selectedDayNos = new java.util.LinkedHashSet<>(request.getDayNos());
        if (selectedDayNos.isEmpty() || !dayByNo.keySet().containsAll(selectedDayNos)) {
            throw new BizException(400, "选择的入住晚次不在当前行程中");
        }

        HotelRoomType roomType = hotelRoomTypeMapper.selectOne(new LambdaQueryWrapper<HotelRoomType>()
                .eq(HotelRoomType::getPoiId, hotel.getId())
                .eq(HotelRoomType::getRoomName, request.getRoomType())
                .last("LIMIT 1"));
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
                    .filter(existing -> existing.getDayId().equals(day.getId()))
                    .findFirst().orElse(null);
            boolean newItem = item == null;
            if (newItem) {
                item = new ItineraryItem();
                item.setItineraryId(itineraryId);
                item.setDayId(day.getId());
                item.setItemType("hotel");
                item.setStartTime(java.time.LocalTime.of(20, 0));
                item.setSortNo(nextSort(day.getId()));
            }
            java.time.LocalDate stayDate = day.getTravelDate() == null ? main.getStartDate() : day.getTravelDate();
            BigDecimal adjustedPrice = com.travel.backend.common.SeasonPrice.apply(roomBasePrice, stayDate);
            String priceRemark = "房型：" + request.getRoomType() + "；基准价￥" + roomBasePrice + "；按" +
                    com.travel.backend.common.SeasonPrice.label(stayDate) + "系数×" +
                    com.travel.backend.common.SeasonPrice.factor(stayDate) +
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
            if (newItem) {
                itemMapper.insert(item);
            } else {
                itemMapper.updateById(item);
            }
        }
        if (selectedDayNos.containsAll(existingHotelDayNos)
                && request.getTier() != null && !request.getTier().isBlank()) {
            main.setHotelTier(request.getTier());
            mainMapper.updateById(main);
        }
        budgetEngine.recalculate(itineraryId);
        consumePendingAction(actionMessage);
        return detail(userId, itineraryId);
    }

    private String str(Object v, String fallback) {
        if (v == null) {
            return fallback;
        }
        String s = String.valueOf(v);
        return s.isBlank() || "null".equals(s) ? fallback : s;
    }

    private void validatePlans(List<Map<String, Object>> plans, List<ItineraryDay> days) {
        if (plans == null || plans.size() != days.size()) {
            throw new BizException(400, "行程草稿必须包含全部日期，未应用任何修改");
        }
        java.util.Set<Integer> seenDays = new java.util.HashSet<>();
        java.util.Set<Integer> validDays = days.stream().map(ItineraryDay::getDayNo)
                .collect(java.util.stream.Collectors.toSet());
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
        if (value == null || String.valueOf(value).isBlank() || "null".equals(value)) {
            return;
        }
        parseRequiredTime(String.valueOf(value));
    }

    private void validateItemRequest(ItemUpsertRequest request) {
        if (request.getItemType() != null
                && !List.of("attraction", "food", "hotel", "transport").contains(request.getItemType())) {
            throw new BizException(400, "行程项类型不合法");
        }
        if (request.getPoiName() != null && request.getPoiName().length() > 128) {
            throw new BizException(400, "地点名称过长");
        }
        if (request.getCost() != null
                && (request.getCost().signum() < 0 || request.getCost().compareTo(new BigDecimal("1000000")) > 0)) {
            throw new BizException(400, "费用必须在 0 到 1000000 之间");
        }
        if (request.getDurationMin() != null
                && (request.getDurationMin() < 0 || request.getDurationMin() > 1440)) {
            throw new BizException(400, "时长必须在 0 到 1440 分钟之间");
        }
    }

    private java.time.LocalTime parseTime(Object v) {
        if (v == null) {
            return null;
        }
        try {
            return java.time.LocalTime.parse(String.valueOf(v));
        } catch (Exception e) {
            return null;
        }
    }
}
