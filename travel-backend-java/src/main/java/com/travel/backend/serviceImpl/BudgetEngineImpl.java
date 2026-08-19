package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.travel.backend.entity.BudgetDetail;
import com.travel.backend.entity.CityConsumption;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.entity.PoiKnowledge;
import com.travel.backend.mapper.BudgetDetailMapper;
import com.travel.backend.mapper.CityConsumptionMapper;
import com.travel.backend.mapper.ItineraryItemMapper;
import com.travel.backend.mapper.ItineraryMainMapper;
import com.travel.backend.mapper.PoiKnowledgeMapper;
import com.travel.backend.service.BudgetEngine;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.List;

@Service
public class BudgetEngineImpl implements BudgetEngine {

    private static final BigDecimal DEFAULT_TRANSPORT_PER_DAY = new BigDecimal("35.00");
    private static final BigDecimal DEFAULT_HOTEL_PER_ROOM = new BigDecimal("300.00");

    private final ItineraryMainMapper mainMapper;
    private final ItineraryItemMapper itemMapper;
    private final BudgetDetailMapper budgetMapper;
    private final CityConsumptionMapper consumptionMapper;
    private final PoiKnowledgeMapper poiMapper;

    public BudgetEngineImpl(ItineraryMainMapper mainMapper, ItineraryItemMapper itemMapper,
                            BudgetDetailMapper budgetMapper, CityConsumptionMapper consumptionMapper,
                            PoiKnowledgeMapper poiMapper) {
        this.mainMapper = mainMapper;
        this.itemMapper = itemMapper;
        this.budgetMapper = budgetMapper;
        this.consumptionMapper = consumptionMapper;
        this.poiMapper = poiMapper;
    }

    @Override
    @Transactional
    public List<BudgetDetail> recalculate(Long itineraryId) {
        ItineraryMain main = mainMapper.selectById(itineraryId);
        if (main == null) {
            return new ArrayList<>();
        }
        int persons = main.getPersons() == null ? 1 : main.getPersons();
        int days = main.getDays() == null ? 1 : main.getDays();
        int rooms = (int) Math.ceil(persons / 2.0);

        List<ItineraryItem> items = itemMapper.selectList(
                new LambdaQueryWrapper<ItineraryItem>().eq(ItineraryItem::getItineraryId, itineraryId));

        BigDecimal ticket = BigDecimal.ZERO;
        BigDecimal meal = BigDecimal.ZERO;
        BigDecimal hotel = BigDecimal.ZERO;
        int ticketCount = 0;
        int mealCount = 0;
        int hotelCount = 0;

        for (ItineraryItem item : items) {
            String type = item.getItemType();
            BigDecimal unit = unitCost(item, main.getCity());
            if (unit == null) {
                continue;
            }
            if ("attraction".equals(type)) {
                ticket = ticket.add(unit);
                ticketCount++;
            } else if ("food".equals(type)) {
                meal = meal.add(unit);
                mealCount++;
            } else if ("hotel".equals(type)) {
                hotel = hotel.add(unit);
                hotelCount++;
            }
        }
        ticket = ticket.multiply(BigDecimal.valueOf(persons));
        meal = meal.multiply(BigDecimal.valueOf(persons));
        hotel = hotel.multiply(BigDecimal.valueOf(rooms)).multiply(BigDecimal.valueOf(days));

        CityConsumption consumption = consumptionMapper.selectOne(
                new LambdaQueryWrapper<CityConsumption>().eq(CityConsumption::getCity, main.getCity()));
        BigDecimal transportPerDay = DEFAULT_TRANSPORT_PER_DAY;
        if (consumption != null && consumption.getTransportPrice() != null) {
            transportPerDay = consumption.getTransportPrice();
        }
        BigDecimal transport = transportPerDay.multiply(BigDecimal.valueOf(days))
                .multiply(BigDecimal.valueOf(persons));

        budgetMapper.delete(new LambdaQueryWrapper<BudgetDetail>()
                .eq(BudgetDetail::getItineraryId, itineraryId));

        List<BudgetDetail> result = new ArrayList<>();
        result.add(build(itineraryId, "门票", ticket, ticketCount, "按景点票价×人数"));
        result.add(build(itineraryId, "餐饮", meal, mealCount, "按餐饮单价×人数"));
        result.add(build(itineraryId, "交通", transport, days, "按城市系数×天数×人数"));
        result.add(build(itineraryId, "酒店", hotel, hotelCount, "按单间价×房间数×晚数"));
        for (BudgetDetail detail : result) {
            budgetMapper.insert(detail);
        }
        return result;
    }

    private BigDecimal unitCost(ItineraryItem item, String city) {
        if (item.getCost() != null) {
            return item.getCost();
        }
        PoiKnowledge poi = null;
        if (item.getPoiId() != null && !item.getPoiId().isBlank()) {
            poi = poiMapper.selectOne(new LambdaQueryWrapper<PoiKnowledge>()
                    .eq(PoiKnowledge::getId, item.getPoiId()));
        }
        if (poi == null && item.getPoiName() != null && !item.getPoiName().isBlank()) {
            poi = poiMapper.selectOne(new LambdaQueryWrapper<PoiKnowledge>()
                    .eq(PoiKnowledge::getCity, city)
                    .eq(PoiKnowledge::getName, item.getPoiName())
                    .last("LIMIT 1"));
        }
        return poi != null ? poi.getTicketPrice() : null;
    }

    private BudgetDetail build(Long itineraryId, String category, BigDecimal amount,
                               int itemCount, String remark) {
        BudgetDetail detail = new BudgetDetail();
        detail.setItineraryId(itineraryId);
        detail.setCategory(category);
        detail.setAmount(amount.setScale(2, RoundingMode.HALF_UP));
        detail.setItemCount(itemCount);
        detail.setRemark(remark);
        return detail;
    }
}