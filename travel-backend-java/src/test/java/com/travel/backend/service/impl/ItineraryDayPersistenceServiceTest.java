package com.travel.backend.service.impl;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.travel.backend.common.BizException;
import com.travel.backend.common.DistributedStateService;
import com.travel.backend.dto.AgentGenerateResponse;
import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.mapper.ItineraryDayMapper;
import com.travel.backend.mapper.ItineraryItemMapper;
import com.travel.backend.mapper.ItineraryMainMapper;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 每日/行程收尾落库的事务写入与幂等保护测试。
 * 覆盖 actionId/fingerprint 409 防重（经幂等门）、SUCCEEDED 幂等跳过、末日酒店不落库、
 * 失败标记，以及 J3 状态机终态列与 J5 预算重算移出 persist 事务的回归。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class ItineraryDayPersistenceServiceTest {

    @Mock
    private ItineraryDayMapper dayMapper;
    @Mock
    private ItineraryItemMapper itemMapper;
    @Mock
    private ItineraryMainMapper mainMapper;

    private ItineraryDayPersistenceService service;
    private ItineraryGenerationGate gate;

    @BeforeAll
    static void initMybatisTableInfo() {
        // 终态写回用例读取 LambdaUpdateWrapper 的绑定值，需要 TableInfo 列缓存
        MybatisConfiguration configuration = new MybatisConfiguration();
        org.apache.ibatis.builder.MapperBuilderAssistant assistant =
                new org.apache.ibatis.builder.MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, ItineraryMain.class);
        TableInfoHelper.initTableInfo(assistant, ItineraryDay.class);
        TableInfoHelper.initTableInfo(assistant, ItineraryItem.class);
    }

    @BeforeEach
    void setUp() {
        // 单测不依赖 Redis：prefer-redis=false 走进程内实现；门用真实实例保住 409 语义
        gate = new ItineraryGenerationGate(new DistributedStateService(null, false));
        service = new ItineraryDayPersistenceService(dayMapper, itemMapper, mainMapper, gate);
    }

    private GenerateRequest request(int days, int stayNights) {
        GenerateRequest request = new GenerateRequest();
        request.setCity("杭州");
        request.setDays(days);
        request.setPersons(2);
        request.setStayNights(stayNights);
        return request;
    }

    private ItineraryDay pendingDay(String actionId, String fingerprint) {
        ItineraryDay day = new ItineraryDay();
        day.setId(50L);
        day.setItineraryId(9L);
        day.setDayNo(1);
        day.setGenerationStatus("PENDING");
        day.setGenerationActionId(actionId);
        day.setGenerationFingerprint(fingerprint);
        return day;
    }

    private AgentGenerateResponse.DailyPlan planWithItems(String... hotelOnLastDay) {
        AgentGenerateResponse.DailyPlan plan = new AgentGenerateResponse.DailyPlan();
        plan.setDayNo(1);
        plan.setNote("第一天");
        java.util.List<AgentGenerateResponse.Item> items = new java.util.ArrayList<>();
        AgentGenerateResponse.Item attraction = new AgentGenerateResponse.Item();
        attraction.setItemType("attraction");
        attraction.setPoiName("西湖");
        attraction.setCost(new BigDecimal("0"));
        items.add(attraction);
        for (String hotel : hotelOnLastDay) {
            AgentGenerateResponse.Item hotelItem = new AgentGenerateResponse.Item();
            hotelItem.setItemType("hotel");
            hotelItem.setPoiName(hotel);
            hotelItem.setCost(new BigDecimal("400"));
            items.add(hotelItem);
        }
        plan.setItems(items);
        return plan;
    }

    /** M3-③：item 落库写 why_note 列，dayOptions 进 metadataJson（仅非空时写入）。 */
    @Test
    void persistWritesWhyNoteAndDayOptionsMetadata() {
        when(dayMapper.selectOne(any(Wrapper.class))).thenReturn(pendingDay(null, null));
        when(itemMapper.insert(any(ItineraryItem.class))).thenReturn(1);
        AgentGenerateResponse.DailyPlan plan = planWithItems();
        plan.getItems().get(0).setWhyThis("湖光山色是杭州的城市名片");
        AgentGenerateResponse.DayOption option = new AgentGenerateResponse.DayOption();
        option.setLabel("西湖经典线");
        option.setSummary("断桥—苏堤—雷峰塔");
        option.setTradeoff("步行多但打卡全");
        plan.setDayOptions(List.of(option));

        service.persist(9L, request(2, 1), 1, plan, "day-9-1", "fp");

        // why_this → why_note 列
        ArgumentCaptor<ItineraryItem> items = ArgumentCaptor.forClass(ItineraryItem.class);
        verify(itemMapper).insert(items.capture());
        assertEquals("湖光山色是杭州的城市名片", items.getValue().getWhyNote());
        // dayOptions 进 metadataJson（落库发生在第一次 updateById 之前）
        ArgumentCaptor<ItineraryDay> days = ArgumentCaptor.forClass(ItineraryDay.class);
        verify(dayMapper, org.mockito.Mockito.atLeastOnce()).updateById(days.capture());
        assertTrue(days.getAllValues().get(0).getMetadataJson().contains("\"dayOptions\""));
    }

    /** J5：预算重算不再位于 persist 事务内（改由编排层异步提交），persist 收尾只标 SUCCEEDED。 */
    @Test
    void persistWritesItemsAndMarksSucceeded() {
        when(dayMapper.selectOne(any(Wrapper.class))).thenReturn(pendingDay(null, null));
        when(itemMapper.insert(any(ItineraryItem.class))).thenReturn(1);

        service.persist(9L, request(2, 1), 1, planWithItems(), "day-9-1", "fp");

        ArgumentCaptor<ItineraryDay> captor = ArgumentCaptor.forClass(ItineraryDay.class);
        verify(dayMapper, org.mockito.Mockito.atLeastOnce()).updateById(captor.capture());
        assertEquals("SUCCEEDED", captor.getAllValues().get(captor.getAllValues().size() - 1).getGenerationStatus());
        // persist 后没有任何预算重算副作用：BudgetEngine 依赖已从本服务移除（构造器层面编译期保证）
    }

    /** #24：dayNo 超过住宿晚数的酒店项不落库（末日不计房价）。 */
    @Test
    void hotelItemBeyondStayNightsIsSkipped() {
        ItineraryDay day = pendingDay(null, null);
        day.setDayNo(2);
        when(dayMapper.selectOne(any(Wrapper.class))).thenReturn(day);
        when(itemMapper.insert(any(ItineraryItem.class))).thenReturn(1);

        service.persist(9L, request(2, 1), 2, planWithItems("杭州大酒店"), "day-9-2", "fp");

        ArgumentCaptor<ItineraryItem> items = ArgumentCaptor.forClass(ItineraryItem.class);
        verify(itemMapper).insert(items.capture());
        // 只落了景点，末日酒店被跳过
        assertEquals(1, items.getAllValues().size());
        assertEquals("attraction", items.getAllValues().get(0).getItemType());
    }

    /** 幂等：同日已 SUCCEEDED 直接返回，不重复写明细。 */
    @Test
    void succeededDayIsNotRewritten() {
        ItineraryDay day = pendingDay("day-9-1", "fp");
        day.setGenerationStatus("SUCCEEDED");
        when(dayMapper.selectOne(any(Wrapper.class))).thenReturn(day);

        service.persist(9L, request(2, 1), 1, planWithItems(), "day-9-1", "fp");

        verify(itemMapper, never()).insert(any(ItineraryItem.class));
    }

    /** 防重：同一 actionId 携带不同指纹 → 409（幂等门唯一实现）。 */
    @Test
    void mismatchedFingerprintRejectedWith409() {
        when(dayMapper.selectOne(any(Wrapper.class))).thenReturn(pendingDay("day-9-1", "fp-old"));

        BizException ex = assertThrows(BizException.class,
                () -> service.persist(9L, request(2, 1), 1, planWithItems(), "day-9-1", "fp-new"));
        assertEquals(409, ex.getCode());
    }

    /** 防重：不同 actionId 抢占同一天 → 409（幂等门唯一实现）。 */
    @Test
    void mismatchedActionIdRejectedWith409() {
        when(dayMapper.selectOne(any(Wrapper.class))).thenReturn(pendingDay("day-9-1", "fp"));

        BizException ex = assertThrows(BizException.class,
                () -> service.persist(9L, request(2, 1), 1, planWithItems(), "other-action", "fp"));
        assertEquals(409, ex.getCode());
    }

    /** markFailed 写入截断后的错误信息并置 FAILED（供恢复任务识别续跑）。 */
    @Test
    void markFailedRecordsTruncatedError() {
        ItineraryDay day = pendingDay("day-9-1", "fp");
        String longError = "x".repeat(900);

        service.markFailed(day, "day-9-1", "fp", longError);

        ArgumentCaptor<ItineraryDay> captor = ArgumentCaptor.forClass(ItineraryDay.class);
        verify(dayMapper).updateById(captor.capture());
        assertEquals("FAILED", captor.getValue().getGenerationStatus());
        assertTrue(captor.getValue().getGenerationError().length() <= 500);
    }

    /** J3 状态机：完成终态写 COMPLETED + gen_resumed 清零 + 一次性清洗旧续跑标记文案。 */
    @Test
    void completeTripWritesCompletedStateMachine() {
        ItineraryMain main = new ItineraryMain();
        main.setId(9L);
        main.setCity("杭州");
        main.setDays(3);
        main.setStatus(1);
        main.setPlanNote("生成失败：x [已自动续跑一次]");

        service.completeTrip(main, true);

        Object[] bound = captureUpdateValues();
        assertTrue(containsValue(bound, "COMPLETED"));
        assertTrue(containsValue(bound, 2));
        assertTrue(containsValue(bound, Boolean.FALSE));
        // 旧实现写入 planNote 的续跑标记在成功收尾时被一次性清洗
        assertTrue(containsValue(bound, "生成失败：x"));
        assertTrue(sqlSet().contains("gen_state") && sqlSet().contains("gen_resumed"));
    }

    /** J3 状态机：存在未 SUCCEEDED 天（如日锁跳过）→ PARTIAL；status 列维持 2 语义不变。 */
    @Test
    void completeTripWritesPartialWhenDaysIncomplete() {
        ItineraryMain main = new ItineraryMain();
        main.setId(9L);
        main.setCity("杭州");
        main.setDays(3);

        service.completeTrip(main, false);

        assertTrue(containsValue(captureUpdateValues(), "PARTIAL"));
        assertTrue(sqlSet().contains("status"));
    }

    /** J3 状态机：失败终态写 FAILED（status 维持 3），不清 gen_resumed（防二次续跑依据）。 */
    @Test
    void failTripWritesFailedStateMachine() {
        service.failTrip(9L, "boom");

        Object[] bound = captureUpdateValues();
        assertTrue(containsValue(bound, "FAILED"));
        assertTrue(containsValue(bound, 3));
        assertTrue(containsValue(bound, "生成失败：boom"));
    }

    private Object[] captureUpdateValues() {
        @SuppressWarnings({"unchecked", "rawtypes"})
        ArgumentCaptor<Wrapper<ItineraryMain>> captor = ArgumentCaptor.forClass((Class) Wrapper.class);
        verify(mainMapper).update(isNull(), captor.capture());
        com.baomidou.mybatisplus.core.conditions.AbstractWrapper<?, ?, ?> wrapper =
                (com.baomidou.mybatisplus.core.conditions.AbstractWrapper<?, ?, ?>) captor.getValue();
        return wrapper.getParamNameValuePairs().values().toArray();
    }

    private String sqlSet() {
        @SuppressWarnings({"unchecked", "rawtypes"})
        ArgumentCaptor<Wrapper<ItineraryMain>> captor = ArgumentCaptor.forClass((Class) Wrapper.class);
        verify(mainMapper).update(isNull(), captor.capture());
        return ((com.baomidou.mybatisplus.core.conditions.update.Update) captor.getValue()).getSqlSet();
    }

    private static boolean containsValue(Object[] values, Object expected) {
        for (Object value : values) {
            if (value == expected || (value != null && value.equals(expected))) {
                return true;
            }
        }
        return false;
    }
}
