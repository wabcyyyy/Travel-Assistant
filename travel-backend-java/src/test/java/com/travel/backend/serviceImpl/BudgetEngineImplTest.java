package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.travel.backend.entity.BudgetDetail;
import com.travel.backend.entity.CityConsumption;
import com.travel.backend.entity.HotelRoomType;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.entity.PoiKnowledge;
import com.travel.backend.mapper.BudgetDetailMapper;
import com.travel.backend.mapper.CityConsumptionMapper;
import com.travel.backend.mapper.ItineraryItemMapper;
import com.travel.backend.mapper.ItineraryMainMapper;
import com.travel.backend.mapper.PoiKnowledgeMapper;
import com.travel.backend.mapper.HotelRoomTypeMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class BudgetEngineImplTest {

    @Mock
    private ItineraryMainMapper mainMapper;
    @Mock
    private ItineraryItemMapper itemMapper;
    @Mock
    private BudgetDetailMapper budgetMapper;
    @Mock
    private CityConsumptionMapper consumptionMapper;
    @Mock
    private PoiKnowledgeMapper poiMapper;
    @Mock
    private HotelRoomTypeMapper hotelRoomTypeMapper;

    private BudgetEngineImpl engine;

    @BeforeEach
    void setUp() {
        engine = new BudgetEngineImpl(
                mainMapper, itemMapper, budgetMapper, consumptionMapper, poiMapper, hotelRoomTypeMapper);
    }

    private ItineraryMain main(int persons, int days) {
        return main(persons, days, null);
    }

    private ItineraryMain main(int persons, int days, java.time.LocalDate startDate) {
        ItineraryMain main = new ItineraryMain();
        main.setId(1L);
        main.setCity("北京");
        main.setPersons(persons);
        main.setDays(days);
        main.setStartDate(startDate);
        return main;
    }

    private ItineraryItem item(String type, String name, BigDecimal cost, String poiId) {
        ItineraryItem item = new ItineraryItem();
        item.setItemType(type);
        item.setPoiName(name);
        item.setCost(cost);
        item.setPoiId(poiId);
        return item;
    }

    @Test
    void recalculateFourCategoriesWithConsumption() {
        when(mainMapper.selectById(1L)).thenReturn(main(2, 2));
        when(itemMapper.selectList(any(Wrapper.class))).thenReturn(List.of(
                item("attraction", "故宫", new BigDecimal("60"), null),
                item("attraction", "天坛", new BigDecimal("40"), null),
                item("food", "全聚德", new BigDecimal("50"), null),
                item("hotel", "酒店", new BigDecimal("300"), null),
                item("hotel", "酒店", new BigDecimal("300"), null)));
        CityConsumption consumption = new CityConsumption();
        consumption.setCity("北京");
        consumption.setTransportPrice(new BigDecimal("50"));
        when(consumptionMapper.selectOne(any(Wrapper.class))).thenReturn(consumption);
        when(budgetMapper.delete(any(Wrapper.class))).thenReturn(1);
        when(budgetMapper.insert(any(BudgetDetail.class))).thenReturn(1);

        List<BudgetDetail> result = engine.recalculate(1L);

        assertEquals(4, result.size());
        assertEquals(new BigDecimal("200.00"), amount(result, "门票"));
        assertEquals(new BigDecimal("100.00"), amount(result, "餐饮"));
        assertEquals(new BigDecimal("200.00"), amount(result, "交通"));
        assertEquals(new BigDecimal("600.00"), amount(result, "酒店"));
    }

    @Test
    void transportDefaultsWhenConsumptionMissing() {
        when(mainMapper.selectById(1L)).thenReturn(main(2, 2));
        when(itemMapper.selectList(any(Wrapper.class))).thenReturn(List.of(
                item("hotel", "酒店", new BigDecimal("300"), null)));
        when(consumptionMapper.selectOne(any(Wrapper.class))).thenReturn(null);
        when(budgetMapper.delete(any(Wrapper.class))).thenReturn(1);
        when(budgetMapper.insert(any(BudgetDetail.class))).thenReturn(1);

        List<BudgetDetail> result = engine.recalculate(1L);

        assertEquals(new BigDecimal("140.00"), amount(result, "交通"));
        // 单条酒店记录代表一晚：不再重复乘天数（旧实现会得到 600）
        assertEquals(new BigDecimal("300.00"), amount(result, "酒店"));
    }

    @Test
    void seasonalFactorAppliedToPoiFallbackHotel() {
        ItineraryMain m = main(2, 2, java.time.LocalDate.of(2026, 10, 2));
        when(mainMapper.selectById(1L)).thenReturn(m);
        when(itemMapper.selectList(any(Wrapper.class))).thenReturn(List.of(
                item("hotel", "全季王府井店", null, null)));
        when(poiMapper.selectOne(any(Wrapper.class))).thenReturn(poiWithPrice("480"));
        when(consumptionMapper.selectOne(any(Wrapper.class))).thenReturn(null);
        when(budgetMapper.delete(any(Wrapper.class))).thenReturn(1);
        when(budgetMapper.insert(any(BudgetDetail.class))).thenReturn(1);

        List<BudgetDetail> result = engine.recalculate(1L);

        // 国庆窗口系数 1.8：480×1.8×rooms(1)=864
        assertEquals(new BigDecimal("864.00"), amount(result, "酒店"));
        assertEquals("知识库基准价已按节假日旺季系数×1.8调整",
                result.stream().filter(b -> "酒店".equals(b.getCategory()))
                        .map(BudgetDetail::getRemark).findFirst().orElse(""));
    }

    @Test
    void hotelRoomCapacityDeterminesRequiredRoomCount() {
        when(mainMapper.selectById(1L)).thenReturn(main(5, 1));
        ItineraryItem hotel = item("hotel", "家庭酒店", new BigDecimal("600"), "88");
        hotel.setRemark("房型：家庭套房；床型：两张大床");
        when(itemMapper.selectList(any(Wrapper.class))).thenReturn(List.of(hotel));
        HotelRoomType roomType = new HotelRoomType();
        roomType.setPoiId(88L);
        roomType.setRoomName("家庭套房");
        roomType.setCapacity(4);
        when(hotelRoomTypeMapper.selectOne(any(Wrapper.class))).thenReturn(roomType);
        when(consumptionMapper.selectOne(any(Wrapper.class))).thenReturn(null);
        when(budgetMapper.delete(any(Wrapper.class))).thenReturn(1);
        when(budgetMapper.insert(any(BudgetDetail.class))).thenReturn(1);

        List<BudgetDetail> result = engine.recalculate(1L);

        // 5人入住容量4人的家庭套房需要2间，而不是按每间2人计算成3间。
        assertEquals(new BigDecimal("1200.00"), amount(result, "酒店"));
    }

    @Test
    void unitCostFallsBackToPoiKnowledgeByPoiId() {
        when(mainMapper.selectById(1L)).thenReturn(main(1, 1));
        ItineraryItem attraction = item("attraction", "故宫", null, "101");
        when(itemMapper.selectList(any(Wrapper.class))).thenReturn(List.of(attraction));
        PoiKnowledge poi = new PoiKnowledge();
        poi.setId(101L);
        poi.setTicketPrice(new BigDecimal("30"));
        when(poiMapper.selectOne(any(Wrapper.class))).thenReturn(poi);
        when(consumptionMapper.selectOne(any(Wrapper.class))).thenReturn(null);
        when(budgetMapper.delete(any(Wrapper.class))).thenReturn(1);
        when(budgetMapper.insert(any(BudgetDetail.class))).thenReturn(1);

        List<BudgetDetail> result = engine.recalculate(1L);

        assertEquals(new BigDecimal("30.00"), amount(result, "门票"));
        assertEquals(1, count(result, "门票"));
    }

    @Test
    void unitCostFallsBackToPoiKnowledgeByNameAndCity() {
        when(mainMapper.selectById(1L)).thenReturn(main(1, 1));
        ItineraryItem attraction = item("attraction", "故宫", null, null);
        when(itemMapper.selectList(any(Wrapper.class))).thenReturn(List.of(attraction));
        when(poiMapper.selectOne(any(Wrapper.class))).thenReturn(poiWithPrice("70"));
        when(consumptionMapper.selectOne(any(Wrapper.class))).thenReturn(null);
        when(budgetMapper.delete(any(Wrapper.class))).thenReturn(1);
        when(budgetMapper.insert(any(BudgetDetail.class))).thenReturn(1);

        List<BudgetDetail> result = engine.recalculate(1L);

        verify(poiMapper).selectOne(any(Wrapper.class));
        assertEquals(new BigDecimal("70.00"), amount(result, "门票"));
    }

    @Test
    void unknownItemWithoutCostIsSkipped() {
        when(mainMapper.selectById(1L)).thenReturn(main(1, 1));
        when(itemMapper.selectList(any(Wrapper.class))).thenReturn(List.of(
                item("attraction", "未知景点", null, null)));
        when(poiMapper.selectOne(any(Wrapper.class))).thenReturn(null);
        when(consumptionMapper.selectOne(any(Wrapper.class))).thenReturn(null);
        when(budgetMapper.delete(any(Wrapper.class))).thenReturn(1);
        when(budgetMapper.insert(any(BudgetDetail.class))).thenReturn(1);

        List<BudgetDetail> result = engine.recalculate(1L);

        assertEquals(0, count(result, "门票"));
        assertEquals(new BigDecimal("0.00"), amount(result, "门票"));
    }

    @Test
    void recalculateDeletesOldRowsAndInsertsNew() {
        when(mainMapper.selectById(1L)).thenReturn(main(1, 1));
        when(itemMapper.selectList(any(Wrapper.class))).thenReturn(List.of());
        when(consumptionMapper.selectOne(any(Wrapper.class))).thenReturn(null);
        when(budgetMapper.delete(any(Wrapper.class))).thenReturn(1);
        when(budgetMapper.insert(any(BudgetDetail.class))).thenReturn(1);

        engine.recalculate(1L);

        verify(budgetMapper).delete(any(Wrapper.class));
        verify(budgetMapper, org.mockito.Mockito.times(4)).insert(any(BudgetDetail.class));
    }

    private BigDecimal amount(List<BudgetDetail> list, String category) {
        return list.stream()
                .filter(b -> category.equals(b.getCategory()))
                .map(BudgetDetail::getAmount)
                .findFirst().orElse(BigDecimal.ZERO);
    }

    private int count(List<BudgetDetail> list, String category) {
        return list.stream()
                .filter(b -> category.equals(b.getCategory()))
                .map(BudgetDetail::getItemCount)
                .findFirst().orElse(0);
    }

    private PoiKnowledge poiWithPrice(String price) {
        PoiKnowledge poi = new PoiKnowledge();
        poi.setTicketPrice(new BigDecimal(price));
        return poi;
    }
}
