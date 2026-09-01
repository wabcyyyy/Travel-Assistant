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

    public ItineraryQueryService(ItineraryMainMapper mainMapper, ItineraryDayMapper dayMapper,
                                 ItineraryItemMapper itemMapper, BudgetDetailMapper budgetMapper,
                                 PoiKnowledgeMapper poiKnowledgeMapper) {
        this.mainMapper = mainMapper;
        this.dayMapper = dayMapper;
        this.itemMapper = itemMapper;
        this.budgetMapper = budgetMapper;
        this.poiKnowledgeMapper = poiKnowledgeMapper;
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
        vo.setDayList(dayVOList);
        vo.setStayNights((int) dayVOList.stream()
                .filter(day -> day.getItems().stream().anyMatch(item -> "hotel".equals(item.getItemType())))
                .count());
        vo.setBudgetList(budgetVOList);
        vo.setTotalAmount(sumAmount(budgets));
        return vo;
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
}
