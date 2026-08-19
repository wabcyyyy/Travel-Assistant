package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.travel.backend.common.BizException;
import com.travel.backend.dto.AgentGenerateRequest;
import com.travel.backend.dto.AgentGenerateResponse;
import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.entity.BudgetDetail;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.mapper.BudgetDetailMapper;
import com.travel.backend.mapper.ItineraryDayMapper;
import com.travel.backend.mapper.ItineraryItemMapper;
import com.travel.backend.mapper.ItineraryMainMapper;
import com.travel.backend.service.AgentService;
import com.travel.backend.service.ItineraryService;
import com.travel.backend.vo.ItinerarySummaryVO;
import com.travel.backend.vo.ItineraryVO;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

@Service
public class ItineraryServiceImpl implements ItineraryService {

    private final ItineraryMainMapper mainMapper;
    private final ItineraryDayMapper dayMapper;
    private final ItineraryItemMapper itemMapper;
    private final BudgetDetailMapper budgetMapper;
    private final AgentService agentService;

    public ItineraryServiceImpl(ItineraryMainMapper mainMapper, ItineraryDayMapper dayMapper,
                                ItineraryItemMapper itemMapper, BudgetDetailMapper budgetMapper,
                                AgentService agentService) {
        this.mainMapper = mainMapper;
        this.dayMapper = dayMapper;
        this.itemMapper = itemMapper;
        this.budgetMapper = budgetMapper;
        this.agentService = agentService;
    }

    @Override
    @Transactional
    public ItineraryVO generate(Long userId, GenerateRequest request) {
        AgentGenerateResponse response = agentService.generate(toAgentRequest(request));

        ItineraryMain main = new ItineraryMain();
        main.setUserId(userId);
        main.setTitle(response.getTitle() == null || response.getTitle().isBlank()
                ? request.getCity() + request.getDays() + "日游" : response.getTitle());
        main.setCity(request.getCity());
        main.setStartDate(request.getStartDate());
        main.setEndDate(request.getEndDate());
        main.setDays(request.getDays());
        main.setPersons(request.getPersons());
        main.setBudget(request.getBudget());
        main.setPreferences(request.getPreferences() == null ? null : String.join(",", request.getPreferences()));
        main.setStatus(2);
        mainMapper.insert(main);

        List<ItineraryVO.DayVO> dayVOList = new ArrayList<>();
        if (response.getDailyPlans() != null) {
            for (AgentGenerateResponse.DailyPlan plan : response.getDailyPlans()) {
                ItineraryDay day = new ItineraryDay();
                day.setItineraryId(main.getId());
                day.setDayNo(plan.getDayNo());
                day.setCity(request.getCity());
                day.setNote(plan.getNote());
                day.setTravelDate(request.getStartDate() == null ? null
                        : request.getStartDate().plusDays(plan.getDayNo() - 1));
                dayMapper.insert(day);

                ItineraryVO.DayVO dayVO = new ItineraryVO.DayVO();
                dayVO.setDayId(day.getId());
                dayVO.setDayNo(day.getDayNo());
                dayVO.setTravelDate(day.getTravelDate());
                dayVO.setNote(day.getNote());
                dayVO.setItems(new ArrayList<>());

                if (plan.getItems() != null) {
                    int sortNo = 0;
                    for (AgentGenerateResponse.Item item : plan.getItems()) {
                        ItineraryItem entity = toEntity(day.getId(), main.getId(), item, sortNo++);
                        itemMapper.insert(entity);
                        dayVO.getItems().add(toItemVO(entity));
                    }
                }
                dayVOList.add(dayVO);
            }
        }

        List<ItineraryVO.BudgetVO> budgetVOList = new ArrayList<>();
        List<BudgetDetail> budgetEntities = new ArrayList<>();
        if (response.getBudgetEstimate() != null) {
            for (Map.Entry<String, BigDecimal> entry : response.getBudgetEstimate().entrySet()) {
                BudgetDetail budget = new BudgetDetail();
                budget.setItineraryId(main.getId());
                budget.setCategory(entry.getKey());
                budget.setAmount(entry.getValue());
                budget.setItemCount(0);
                budgetMapper.insert(budget);
                budgetEntities.add(budget);
                budgetVOList.add(toBudgetVO(budget));
            }
        }

        ItineraryVO vo = toVO(main);
        vo.setDayList(dayVOList);
        vo.setBudgetList(budgetVOList);
        vo.setTotalAmount(sumAmount(budgetEntities));
        return vo;
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
}