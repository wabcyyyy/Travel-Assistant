package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.travel.backend.common.DistributedStateService;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.mapper.ItineraryDayMapper;
import com.travel.backend.mapper.ItineraryItemMapper;
import com.travel.backend.mapper.ItineraryMainMapper;
import com.travel.backend.service.AgentService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.cache.CacheManager;

import java.time.LocalDateTime;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 状态恢复任务测试（审计修复 #19/#23 回归兜底）：
 * 完成态自动置 2、部分失败可续跑一次、已续跑过的不再重拉（防死循环）、
 * 运行中的天不与原任务并发。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class ItineraryStatusRecoveryTest {

    @Mock
    private ItineraryMainMapper mainMapper;
    @Mock
    private ItineraryDayMapper dayMapper;
    @Mock
    private ItineraryItemMapper itemMapper;
    @Mock
    private CacheManager cacheManager;
    @Mock
    private AgentService agentService;
    @Mock
    private ItineraryAsyncPlanner planner;

    private ItineraryStatusRecovery recovery;
    private DistributedStateService state;

    @BeforeEach
    void setUp() throws Exception {
        state = new DistributedStateService(null, false);
        recovery = new ItineraryStatusRecovery(mainMapper, dayMapper, itemMapper,
                cacheManager, agentService, planner, state);
    }

    private ItineraryMain main(long id, int days, int status, String planNote) {
        ItineraryMain main = new ItineraryMain();
        main.setId(id);
        main.setUserId(7L);
        main.setCity("杭州");
        main.setDays(days);
        main.setStatus(status);
        main.setPlanNote(planNote);
        return main;
    }

    private ItineraryDay day(long itineraryId, int dayNo, String status, String error, LocalDateTime updatedAt) {
        ItineraryDay day = new ItineraryDay();
        day.setId(itineraryId * 100 + dayNo);
        day.setItineraryId(itineraryId);
        day.setDayNo(dayNo);
        day.setGenerationStatus(status);
        day.setGenerationError(error);
        day.setUpdatedAt(updatedAt);
        return day;
    }

    /** selectList 第一次返回生成中列表，第二次返回失败列表。 */
    private void stubLists(List<ItineraryMain> generating, List<ItineraryMain> failed) {
        when(mainMapper.selectList(any(Wrapper.class))).thenReturn(generating, failed);
    }

    /** 全部天已完成 → 行程自动置为已生成（status=2），不触发续跑。 */
    @Test
    void completedTripIsMarkedGenerated() {
        ItineraryMain target = main(2001L, 2, 1, null);
        stubLists(List.of(target), List.of());
        when(dayMapper.selectList(any(Wrapper.class))).thenReturn(List.of(
                day(2001L, 1, "SUCCEEDED", null, null),
                day(2001L, 2, "SUCCEEDED", null, null)));

        recovery.recover();

        assertEquals(2, target.getStatus());
        verify(mainMapper).updateById(target);
        verify(planner, never()).planDays(anyLong(), anyLong(), any(), any());
    }

    /** #19：status=3 且所有未成功天均为 FAILED 且有错误 → 续跑一次并重置为生成中。 */
    @Test
    void partiallyFailedTripIsResumedOnce() {
        ItineraryMain target = main(2002L, 3, 3, "生成失败：整段生成部分失败（第[2]天）");
        stubLists(List.of(), List.of(target));
        when(dayMapper.selectList(any(Wrapper.class))).thenReturn(List.of(
                day(2002L, 1, "SUCCEEDED", null, null),
                day(2002L, 2, "FAILED", "db write failed", LocalDateTime.now().minusMinutes(30)),
                day(2002L, 3, "SUCCEEDED", null, null)));

        recovery.recover();

        verify(planner).planDays(eq(7L), eq(2002L), any(), isNull());
        // 续跑前置为生成中，并写入"已自动续跑一次"标记供 fail() 保留
        assertEquals(1, target.getStatus());
        assertTrue(target.getPlanNote().contains(ItineraryAsyncPlanner.RESUME_MARKER));
        verify(mainMapper).updateById(target);
    }

    /** 防死循环：planNote 已含续跑标记的行程不再被重拉。 */
    @Test
    void alreadyResumedTripIsNotPickedUpAgain() {
        ItineraryMain target = main(2003L, 3, 3, "生成失败：又一次失败 " + ItineraryAsyncPlanner.RESUME_MARKER);
        stubLists(List.of(), List.of(target));
        when(dayMapper.selectList(any(Wrapper.class))).thenReturn(List.of(
                day(2003L, 1, "SUCCEEDED", null, null),
                day(2003L, 2, "FAILED", "still failing", LocalDateTime.now().minusMinutes(30)),
                day(2003L, 3, "SUCCEEDED", null, null)));

        recovery.recover();

        verify(planner, never()).planDays(anyLong(), anyLong(), any(), any());
        verify(mainMapper, never()).updateById(any(ItineraryMain.class));
    }

    /** 非落库失败（如天仍为 PENDING）不满足续跑条件，避免把未知状态误判为可重跑。 */
    @Test
    void failedTripWithPendingDayIsNotResumed() {
        ItineraryMain target = main(2004L, 2, 3, "生成失败：中断");
        stubLists(List.of(), List.of(target));
        when(dayMapper.selectList(any(Wrapper.class))).thenReturn(List.of(
                day(2004L, 1, "SUCCEEDED", null, null),
                day(2004L, 2, "PENDING", null, LocalDateTime.now().minusMinutes(30))));

        recovery.recover();

        verify(planner, never()).planDays(anyLong(), anyLong(), any(), any());
    }

    /** 并发保护：近 5 分钟内仍在 RUNNING 的天，本轮不接管。 */
    @Test
    void activeRunningDayBlocksRecovery() {
        ItineraryMain target = main(2005L, 2, 1, null);
        stubLists(List.of(target), List.of());
        when(dayMapper.selectList(any(Wrapper.class))).thenReturn(List.of(
                day(2005L, 1, "SUCCEEDED", null, null),
                day(2005L, 2, "RUNNING", null, LocalDateTime.now().minusSeconds(10))));

        recovery.recover();

        verify(planner, never()).planDays(anyLong(), anyLong(), any(), any());
        assertNull(target.getPlanNote());
        assertEquals(1, target.getStatus());
    }

    /** 去重表：同一行程一轮内只会被拉起一次。 */
    @Test
    void resumeDedupesWithinTtl() {
        ItineraryMain target = main(2006L, 2, 3, "生成失败：部分失败");
        stubLists(List.of(), List.of(target, target));
        when(dayMapper.selectList(any(Wrapper.class))).thenReturn(List.of(
                day(2006L, 1, "FAILED", "boom", LocalDateTime.now().minusMinutes(30)),
                day(2006L, 2, "FAILED", "boom", LocalDateTime.now().minusMinutes(30))));

        recovery.recover();

        verify(planner, org.mockito.Mockito.times(1)).planDays(anyLong(), anyLong(), any(), any());
    }
}
