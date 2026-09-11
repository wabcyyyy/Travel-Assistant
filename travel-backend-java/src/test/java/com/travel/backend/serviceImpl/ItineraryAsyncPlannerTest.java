package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.travel.backend.common.BizException;
import com.travel.backend.common.DistributedStateService;
import com.travel.backend.dto.AgentGenerateResponse;
import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.entity.ItineraryDay;
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
import org.springframework.cache.CacheManager;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.entity.ItineraryVersion;
import com.travel.backend.entity.ExportTask;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 整段生成编排的状态机测试（审计修复 #19 回归兜底）：
 * 部分失败不拖死全程、失败终态可被恢复任务识别、Python failed 契约不透传为成功。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class ItineraryAsyncPlannerTest {

    @Mock
    private AgentServiceImpl agentService;
    @Mock
    private ItineraryDayMapper dayMapper;
    @Mock
    private ItineraryItemMapper itemMapper;
    @Mock
    private ItineraryMainMapper mainMapper;
    @Mock
    private ItineraryDayPersistenceService dayPersistenceService;
    @Mock
    private ItineraryVersionService versionService;
    @Mock
    private CacheManager cacheManager;

    private ItineraryAsyncPlanner planner;
    private DistributedStateService state;

    @BeforeAll
    static void initMybatisTableInfo() {
        // 纯 Mockito 单测无 Spring/MyBatis 容器，LambdaUpdateWrapper 需要 TableInfo 缓存
        MybatisConfiguration configuration = new MybatisConfiguration();
        org.apache.ibatis.builder.MapperBuilderAssistant assistant =
                new org.apache.ibatis.builder.MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, ItineraryMain.class);
        TableInfoHelper.initTableInfo(assistant, ItineraryDay.class);
        TableInfoHelper.initTableInfo(assistant, ItineraryItem.class);
        TableInfoHelper.initTableInfo(assistant, ItineraryVersion.class);
    }

    @BeforeEach
    void setUp() {
        // 单测不依赖 Redis：prefer-redis=false 走进程内实现
        state = new DistributedStateService(null, false);
        planner = new ItineraryAsyncPlanner(agentService, dayMapper, itemMapper, mainMapper,
                dayPersistenceService, versionService, cacheManager, state);
    }

    private GenerateRequest request(int days) {
        GenerateRequest request = new GenerateRequest();
        request.setCity("杭州");
        request.setDays(days);
        request.setPersons(2);
        request.setStayNights(Math.max(days - 1, 0));
        return request;
    }

    private ItineraryMain main(long id, int days) {
        ItineraryMain main = new ItineraryMain();
        main.setId(id);
        main.setUserId(7L);
        main.setCity("杭州");
        main.setDays(days);
        main.setStatus(1);
        return main;
    }

    private ItineraryDay day(long itineraryId, int dayNo, String status) {
        ItineraryDay day = new ItineraryDay();
        day.setId(itineraryId * 100 + dayNo);
        day.setItineraryId(itineraryId);
        day.setDayNo(dayNo);
        day.setGenerationStatus(status);
        return day;
    }

    private AgentGenerateResponse tripResponse(int days, String status) {
        AgentGenerateResponse response = new AgentGenerateResponse();
        response.setStatus(status);
        response.setDailyPlans(java.util.stream.IntStream.rangeClosed(1, days).mapToObj(dayNo -> {
            AgentGenerateResponse.DailyPlan plan = new AgentGenerateResponse.DailyPlan();
            plan.setDayNo(dayNo);
            plan.setItems(List.of());
            return plan;
        }).toList());
        return response;
    }

    /** 全部天成功：行程置为已生成（status=2），版本快照被记录。 */
    @Test
    void wholeTripSuccessFinishesAsGenerated() {
        long itineraryId = 1001L;
        when(mainMapper.selectById(itineraryId)).thenReturn(main(itineraryId, 3));
        when(dayMapper.selectOne(any(Wrapper.class))).thenReturn(
                day(itineraryId, 1, "PENDING"), day(itineraryId, 2, "PENDING"), day(itineraryId, 3, "PENDING"));
        when(agentService.generate(any())).thenReturn(tripResponse(3, "degraded"));

        planner.planDays(7L, itineraryId, request(3), null);

        verify(dayPersistenceService, times(3)).persist(eq(itineraryId), any(), anyInt(), any(), anyString(), anyString());
        verify(dayPersistenceService, never()).markFailed(any(), anyString(), anyString(), any());
        // finish() 使用 LambdaUpdateWrapper 而非 updateById
        verify(mainMapper, times(1)).update(isNull(), any());
        verify(versionService).createSnapshot(eq(7L), eq(itineraryId), eq("generate"), anyString());
    }

    /** #19 核心：第 2 天落库失败不拖死全程——其余天照常落库，终态置 3 且带失败原因。 */
    @Test
    void wholeTripPartialFailurePersistsOtherDaysAndMarksFailed() {
        long itineraryId = 1002L;
        when(mainMapper.selectById(itineraryId)).thenReturn(main(itineraryId, 3));
        when(dayMapper.selectOne(any(Wrapper.class))).thenReturn(
                day(itineraryId, 1, "PENDING"), day(itineraryId, 2, "PENDING"), day(itineraryId, 3, "PENDING"));
        when(agentService.generate(any())).thenReturn(tripResponse(3, "degraded"));
        // 仅第 2 天落库抛错，其余天正常。
        doAnswer(invocation -> {
            int dayNo = invocation.getArgument(2);
            if (dayNo == 2) {
                throw new IllegalStateException("db write failed on day 2");
            }
            return null;
        }).when(dayPersistenceService).persist(eq(itineraryId), any(), anyInt(), any(), anyString(), anyString());

        planner.planDays(7L, itineraryId, request(3), null);

        // 部分失败不中断循环：三天都被尝试落库（第 2 天在方法内抛错仍计一次调用），
        // 第 2 天被标记 FAILED（可被恢复任务识别续跑）。
        ArgumentCaptor<Integer> attemptedDays = ArgumentCaptor.forClass(Integer.class);
        verify(dayPersistenceService, times(3))
                .persist(eq(itineraryId), any(), attemptedDays.capture(), any(), anyString(), anyString());
        assertEquals(List.of(1, 2, 3), attemptedDays.getAllValues());
        ArgumentCaptor<ItineraryDay> failedDay = ArgumentCaptor.forClass(ItineraryDay.class);
        ArgumentCaptor<String> failedError = ArgumentCaptor.forClass(String.class);
        verify(dayPersistenceService).markFailed(failedDay.capture(), anyString(), anyString(), failedError.capture());
        assertEquals(2, failedDay.getValue().getDayNo());
        assertTrue(failedError.getValue().contains("db write failed"));
        // 终态通过 LambdaUpdateWrapper 写 status=3；未记录"生成完成"快照
        verify(mainMapper, times(1)).update(isNull(), any());
        verify(versionService, never()).createSnapshot(anyLong(), anyLong(), anyString(), anyString());
    }

    /** #17 契约：Python 返回 status=failed 时整段作废，一天都不落库。 */
    @Test
    void wholeTripPythonFailedStatusAbortsBeforePersist() {
        long itineraryId = 1003L;
        when(mainMapper.selectById(itineraryId)).thenReturn(main(itineraryId, 2));
        when(agentService.generate(any())).thenReturn(tripResponse(2, "failed"));

        planner.planDays(7L, itineraryId, request(2), null);

        verify(dayPersistenceService, never()).persist(anyLong(), any(), anyInt(), any(), anyString(), anyString());
        verify(mainMapper, times(1)).update(isNull(), any());
    }

    /** 整段结果缺天：抛业务异常并置失败终态，而不是静默交付半截行程。 */
    @Test
    void wholeTripIncompleteResponseFails() {
        long itineraryId = 1004L;
        when(mainMapper.selectById(itineraryId)).thenReturn(main(itineraryId, 3));
        when(agentService.generate(any())).thenReturn(tripResponse(2, "degraded"));

        planner.planDays(7L, itineraryId, request(3), null);

        verify(dayPersistenceService, never()).persist(anyLong(), any(), anyInt(), any(), anyString(), anyString());
        verify(mainMapper, times(1)).update(isNull(), any());
    }

    /** planDays 结束后日锁被清理（#12：静态集合不随行程无界增长）。 */
    @Test
    void dayLocksReleasedAfterPlanning() throws Exception {
        long itineraryId = 1005L;
        when(mainMapper.selectById(itineraryId)).thenReturn(main(itineraryId, 1));
        // 单日路径走 generateDay；这里只验证锁清理：直接反射检查 map 状态
        when(agentService.planContext(anyString(), any())).thenReturn(
                new com.fasterxml.jackson.databind.ObjectMapper().createObjectNode());
        when(agentService.generateDay(any())).thenThrow(new BizException(500, "boom"));

        planner.planDays(7L, itineraryId, request(1), null);

        assertTrue(!planner.isDayLocked(itineraryId, 1), "该行程的日锁应已释放");
        assertTrue(!state.isMarked("gen:day:" + itineraryId + ":1"));
    }
}
