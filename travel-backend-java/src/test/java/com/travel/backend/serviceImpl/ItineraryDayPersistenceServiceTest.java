package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.travel.backend.common.BizException;
import com.travel.backend.dto.AgentGenerateResponse;
import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.mapper.ItineraryDayMapper;
import com.travel.backend.mapper.ItineraryItemMapper;
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
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 每日落库的事务写入与幂等保护测试（审计遗留项：核心编排零测试兜底）。
 * 覆盖 actionId/fingerprint 409 防重、SUCCEEDED 幂等跳过、末日酒店不落库、失败标记。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class ItineraryDayPersistenceServiceTest {

    @Mock
    private ItineraryDayMapper dayMapper;
    @Mock
    private ItineraryItemMapper itemMapper;
    @Mock
    private com.travel.backend.service.BudgetEngine budgetEngine;

    private ItineraryDayPersistenceService service;

    @BeforeEach
    void setUp() {
        service = new ItineraryDayPersistenceService(dayMapper, itemMapper, budgetEngine);
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

    @Test
    void persistWritesItemsAndMarksSucceeded() {
        when(dayMapper.selectOne(any(Wrapper.class))).thenReturn(pendingDay(null, null));
        when(itemMapper.insert(any(ItineraryItem.class))).thenReturn(1);

        service.persist(9L, request(2, 1), 1, planWithItems(), "day-9-1", "fp");

        ArgumentCaptor<ItineraryDay> captor = ArgumentCaptor.forClass(ItineraryDay.class);
        verify(dayMapper, org.mockito.Mockito.atLeastOnce()).updateById(captor.capture());
        assertEquals("SUCCEEDED", captor.getAllValues().get(captor.getAllValues().size() - 1).getGenerationStatus());
        verify(budgetEngine).recalculate(9L);
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

    /** 防重：同一 actionId 携带不同指纹 → 409。 */
    @Test
    void mismatchedFingerprintRejectedWith409() {
        when(dayMapper.selectOne(any(Wrapper.class))).thenReturn(pendingDay("day-9-1", "fp-old"));

        BizException ex = assertThrows(BizException.class,
                () -> service.persist(9L, request(2, 1), 1, planWithItems(), "day-9-1", "fp-new"));
        assertEquals(409, ex.getCode());
    }

    /** 防重：不同 actionId 抢占同一天 → 409。 */
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
}
