package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.travel.backend.entity.BudgetDetail;
import com.travel.backend.entity.CityConsumption;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.entity.HotelRoomType;
import com.travel.backend.entity.PoiKnowledge;
import com.travel.backend.mapper.BudgetDetailMapper;
import com.travel.backend.mapper.CityConsumptionMapper;
import com.travel.backend.mapper.ItineraryItemMapper;
import com.travel.backend.mapper.ItineraryMainMapper;
import com.travel.backend.mapper.HotelRoomTypeMapper;
import com.travel.backend.mapper.PoiKnowledgeMapper;
import com.travel.backend.service.BudgetEngine;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
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
    private final HotelRoomTypeMapper hotelRoomTypeMapper;

    public BudgetEngineImpl(ItineraryMainMapper mainMapper, ItineraryItemMapper itemMapper,
                            BudgetDetailMapper budgetMapper, CityConsumptionMapper consumptionMapper,
                            PoiKnowledgeMapper poiMapper, HotelRoomTypeMapper hotelRoomTypeMapper) {
        this.mainMapper = mainMapper;
        this.itemMapper = itemMapper;
        this.budgetMapper = budgetMapper;
        this.consumptionMapper = consumptionMapper;
        this.poiMapper = poiMapper;
        this.hotelRoomTypeMapper = hotelRoomTypeMapper;
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
        List<ItineraryItem> items = itemMapper.selectList(
                new LambdaQueryWrapper<ItineraryItem>().eq(ItineraryItem::getItineraryId, itineraryId));

        BigDecimal ticket = BigDecimal.ZERO;
        BigDecimal meal = BigDecimal.ZERO;
        BigDecimal hotel = BigDecimal.ZERO;
        int ticketCount = 0;
        int mealCount = 0;
        int hotelCount = 0;
        boolean hotelFromPoiFallback = false;

        for (ItineraryItem item : items) {
            String type = item.getItemType();
            BigDecimal unit;
            if (item.getCost() != null) {
                unit = item.getCost();
            } else {
                unit = poiUnitCost(item, main.getCity());
                if (unit != null && "hotel".equals(type)) {
                    // 知识库基准价按出行日期做季节调整（与 agent 端 season.py 同规则）
                    unit = com.travel.backend.common.SeasonPrice.apply(unit, main.getStartDate());
                    hotelFromPoiFallback = true;
                }
            }
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
                int capacity = hotelCapacity(item);
                int roomCount = (int) Math.ceil(persons / (double) capacity);
                hotel = hotel.add(unit.multiply(BigDecimal.valueOf(roomCount)));
                hotelCount++;
            }
        }
        ticket = ticket.multiply(BigDecimal.valueOf(persons));
        meal = meal.multiply(BigDecimal.valueOf(persons));
        // 酒店已逐晚按所选房型容量计算房间数，不再统一假定每间只能住 2 人。

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
        String hotelRemark = "按每晚房费×房间数合计";
        if (hotelFromPoiFallback && hotelCount > 0) {
            LocalDate sd = main.getStartDate();
            hotelRemark = "知识库基准价已按" + com.travel.backend.common.SeasonPrice.label(sd)
                    + "系数×" + com.travel.backend.common.SeasonPrice.factor(sd) + "调整";
        }
        result.add(build(itineraryId, "酒店", hotel, hotelCount, hotelRemark));
        for (BudgetDetail detail : result) {
            budgetMapper.insert(detail);
        }
        return result;
    }

    private BigDecimal poiUnitCost(ItineraryItem item, String city) {
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

    private int hotelCapacity(ItineraryItem item) {
        if (item.getPoiId() == null || item.getRemark() == null) {
            return 2;
        }
        String marker = "房型：";
        int start = item.getRemark().indexOf(marker);
        if (start < 0) {
            return 2;
        }
        start += marker.length();
        int end = item.getRemark().indexOf('；', start);
        String roomName = (end < 0 ? item.getRemark().substring(start)
                : item.getRemark().substring(start, end)).trim();
        try {
            long poiId = Long.parseLong(item.getPoiId());
            HotelRoomType roomType = hotelRoomTypeMapper.selectOne(
                    new LambdaQueryWrapper<HotelRoomType>()
                            .eq(HotelRoomType::getPoiId, poiId)
                            .eq(HotelRoomType::getRoomName, roomName)
                            .last("LIMIT 1"));
            return roomType == null || roomType.getCapacity() == null
                    ? 2 : Math.max(roomType.getCapacity(), 1);
        } catch (NumberFormatException e) {
            return 2;
        }
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
