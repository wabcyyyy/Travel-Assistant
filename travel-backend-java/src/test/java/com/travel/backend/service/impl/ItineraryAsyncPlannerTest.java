package com.travel.backend.service.impl;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.travel.backend.common.BizException;
import com.travel.backend.common.DistributedStateService;
import com.travel.backend.dto.AgentGenerateResponse;
import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.mapper.ItineraryMainMapper;
import com.travel.backend.service.AgentService;
import com.travel.backend.service.BudgetEngine;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.cache.Cache;
import org.springframework.cache.CacheManager;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.entity.ItineraryVersion;
import com.travel.backend.entity.ExportTask;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 逐日生成编排的状态机测试（AD8：单日/多日统一逐日生成流）：
 * 研究一次（planContext）+ 逐日 generate-day、失败天可被恢复任务识别续跑、
 * 建议池来自第 1 天生成结果，整段 /v1/generate 不再出现在主路径。
 * M2-②：幂等原语经 ItineraryGenerationGate、终态写回/预算异步/精确失效为编排外职责。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class ItineraryAsyncPlannerTest {

    @Mock
    private AgentService agentService;
    @Mock
    private ItineraryMainMapper mainMapper;
    @Mock
    private ItineraryDayPersistenceService dayPersistenceService;
    @Mock
    private ItineraryVersionService versionService;
    @Mock
    private ItineraryEnricher enricher;
    @Mock
    private BudgetEngine budgetEngine;
    @Mock
    private CacheManager cacheManager;
    @Mock
    private com.travel.backend.common.ItineraryEventPublisher eventPublisher;

    private ItineraryAsyncPlanner planner;
    private ItineraryGenerationGate gate;
    private DistributedStateService state;
    private final tools.jackson.databind.ObjectMapper json =
            new tools.jackson.databind.ObjectMapper();

    @BeforeAll
    static void initMybatisTableInfo() {
        // 纯 Mockito 单测无 Spring/MyBatis 容器，LambdaUpdateWrapper 需要 TableInfo 缓存
        MybatisConfiguration configuration = new MybatisConfiguration();
        org.apache.ibatis.builder.MapperBuilderAssistant assistant =
                new org.apache.ibatis.builder.MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, ItineraryMain.class);
        TableInfoHelper.initTableInfo(assistant, com.travel.backend.entity.ItineraryDay.class);
        TableInfoHelper.initTableInfo(assistant, ItineraryItem.class);
        TableInfoHelper.initTableInfo(assistant, ItineraryVersion.class);
        TableInfoHelper.initTableInfo(assistant, ExportTask.class);
    }

    @BeforeEach
    void setUp() {
        // 单测不依赖 Redis：prefer-redis=false 走进程内实现；门用真实实例保住日锁语义
        state = new DistributedStateService(null, false);
        gate = new ItineraryGenerationGate(state);
        // 直接执行器让预算异步重算在测试内同步可见
        planner = new ItineraryAsyncPlanner(agentService, mainMapper, dayPersistenceService,
                versionService, gate, enricher, budgetEngine, cacheManager, Runnable::run, eventPublisher);
        when(dayPersistenceService.allDaysSucceeded(anyLong())).thenReturn(true);
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

    /** 构造 generateDay 返回的单日 JSON（可选附 suggestions 备选池，对应 AD8 逐日语义）。 */
    private tools.jackson.databind.JsonNode dayNode(int dayNo, String suggestionsJson) throws Exception {
        String extra = suggestionsJson == null ? "" : ",\"suggestions\":" + suggestionsJson;
        return json.readTree("{\"dayNo\":" + dayNo + ",\"items\":[]" + extra + "}");
    }

    /** 逐日路径每天会查两次日记录（生成前 + 落库后），按调用次序成对返回 PENDING 天。 */
    private void stubDayLookup(long itineraryId, int days) {
        ItineraryDay[] lookups = new ItineraryDay[days * 2];
        for (int i = 0; i < days; i++) {
            lookups[2 * i] = day(itineraryId, i + 1, "PENDING");
            lookups[2 * i + 1] = day(itineraryId, i + 1, "PENDING");
        }
        when(dayPersistenceService.findDay(eq(itineraryId), anyInt()))
                .thenReturn(lookups[0], java.util.Arrays.copyOfRange(lookups, 1, lookups.length));
    }

    private Cache stubDetailCache() {
        Cache detailCache = mock(Cache.class);
        when(cacheManager.getCache("itinerary:detail")).thenReturn(detailCache);
        return detailCache;
    }

    /** AD8 核心回归：多日走统一逐日流——planContext 研究一次、generateDay 逐日 3 次，整段 generate 不再被调用。 */
    @Test
    void multiDaySuccessUsesPerDayFlowAndFinishesAsGenerated() throws Exception {
        long itineraryId = 1001L;
        Cache detailCache = stubDetailCache();
        when(mainMapper.selectById(itineraryId)).thenReturn(main(itineraryId, 3));
        stubDayLookup(itineraryId, 3);
        when(agentService.planContext(anyString(), any(), any())).thenReturn(json.createObjectNode());
        // 第 1 天返回备选池，其余天不返回
        when(agentService.generateDay(any())).thenAnswer(invocation -> {
            java.util.Map<String, Object> payload = invocation.getArgument(0);
            int dayNo = (int) payload.get("day_no");
            return dayNode(dayNo, dayNo == 1 ? "[{\"name\":\"备用观景台\",\"category\":\"attraction\"}]" : null);
        });

        planner.planDays(7L, itineraryId, request(3), null);

        // 研究阶段恰好一次、逐日生成恰好 3 次、整段流式生成从未发生
        verify(agentService, times(1)).planContext(anyString(), any(), any());
        verify(agentService, times(3)).generateDay(any());
        verify(agentService, never()).generateTripStream(any(), any());
        verify(dayPersistenceService, times(3)).persist(eq(itineraryId), any(), anyInt(), any(), anyString(), anyString());
        verify(dayPersistenceService, never()).markFailed(any(), anyString(), anyString(), any());
        // 开场置 GENERATING（J3 状态机）是 mainMapper 唯一一次 update；终态写回下沉 PersistenceService
        @SuppressWarnings({"unchecked", "rawtypes"})
        ArgumentCaptor<Wrapper<ItineraryMain>> updates = ArgumentCaptor.forClass((Class) Wrapper.class);
        verify(mainMapper, times(1)).update(isNull(), updates.capture());
        assertTrue(((com.baomidou.mybatisplus.core.conditions.update.Update) updates.getValue())
                .getSqlSet().contains("gen_state"));
        // 第 1 天 suggestions 写入行程级备选池
        @SuppressWarnings({"unchecked", "rawtypes"})
        ArgumentCaptor<List<AgentGenerateResponse.Suggestion>> suggestions =
                ArgumentCaptor.forClass((Class) List.class);
        verify(enricher).persistSuggestions(eq(itineraryId), suggestions.capture());
        assertEquals(1, suggestions.getValue().size());
        assertEquals("备用观景台", suggestions.getValue().get(0).getName());
        // 全部天成功：按天汇总 COMPLETED，版本快照被记录
        verify(dayPersistenceService).completeTrip(any(ItineraryMain.class), eq(true));
        verify(versionService).createSnapshot(eq(7L), eq(itineraryId), eq("generate"), anyString());
        // 预算重算移出 persist 事务（J5）：3 天各一次 + finish 收口一次，且走 enricherExecutor
        verify(budgetEngine, times(4)).recalculate(itineraryId);
        // 精确失效（J2）：3 天落库各一次 + finish 一次，key 与 ItineraryQueryService 的 "userId:id" 一致
        verify(detailCache, times(4)).evict("7:" + itineraryId);
    }

    /** AD8 失败粒度更细：某天生成失败即 markFailed 该天并整体置失败终态（status=3），已成功天保持 SUCCEEDED 供续跑跳过。 */
    @Test
    void multiDayDayFailureMarksDayFailedAndFailsTrip() throws Exception {
        long itineraryId = 1002L;
        when(mainMapper.selectById(itineraryId)).thenReturn(main(itineraryId, 3));
        stubDayLookup(itineraryId, 3);
        when(agentService.planContext(anyString(), any(), any())).thenReturn(json.createObjectNode());
        // 第 1 天正常，第 2 天生成失败，循环中断（第 3 天本轮不再尝试）
        when(agentService.generateDay(any()))
                .thenReturn(dayNode(1, null))
                .thenThrow(new BizException(500, "day 2 generation boom"));

        planner.planDays(7L, itineraryId, request(3), null);

        verify(agentService, times(2)).generateDay(any());
        verify(agentService, never()).generateTripStream(any(), any());
        ArgumentCaptor<Integer> persistedDays = ArgumentCaptor.forClass(Integer.class);
        verify(dayPersistenceService, times(1))
                .persist(eq(itineraryId), any(), persistedDays.capture(), any(), anyString(), anyString());
        assertEquals(List.of(1), persistedDays.getAllValues());
        ArgumentCaptor<ItineraryDay> failedDay = ArgumentCaptor.forClass(ItineraryDay.class);
        ArgumentCaptor<String> failedError = ArgumentCaptor.forClass(String.class);
        verify(dayPersistenceService).markFailed(failedDay.capture(), anyString(), anyString(), failedError.capture());
        assertEquals(2, failedDay.getValue().getDayNo());
        assertTrue(failedError.getValue().contains("day 2 generation boom"));
        // 状态机（J3）：走 FAILED 终态（failTrip），不再进入完成汇总；未记录"生成完成"快照
        verify(dayPersistenceService).failTrip(eq(itineraryId), contains("day 2 generation boom"));
        verify(dayPersistenceService, never()).completeTrip(any(), anyBoolean());
        verify(versionService, never()).createSnapshot(anyLong(), anyLong(), anyString(), anyString());
        // 预算重算只发生在第 1 天成功后（fail 路径不提交）
        verify(budgetEngine, times(1)).recalculate(itineraryId);
    }

    /** planDays 结束后日锁被清理（#12：静态集合不随行程无界增长）。 */
    @Test
    void dayLocksReleasedAfterPlanning() throws Exception {
        long itineraryId = 1005L;
        when(mainMapper.selectById(itineraryId)).thenReturn(main(itineraryId, 1));
        // 单日路径走 generateDay；这里只验证锁清理：直接检查门状态
        when(agentService.planContext(anyString(), any(), any())).thenReturn(
                new tools.jackson.databind.ObjectMapper().createObjectNode());
        when(agentService.generateDay(any())).thenThrow(new BizException(500, "boom"));

        planner.planDays(7L, itineraryId, request(1), null);

        assertTrue(!planner.isDayLocked(itineraryId, 1), "该行程的日锁应已释放");
        assertTrue(!state.isMarked("gen:day:" + itineraryId + ":1"));
    }

    /** J3 状态机 PARTIAL 触发条件：日锁被占导致存在未 SUCCEEDED 天 → completeTrip(allSucceeded=false)。 */
    @Test
    void dayLockSkippedDayYieldsPartialCompletion() throws Exception {
        long itineraryId = 1008L;
        when(mainMapper.selectById(itineraryId)).thenReturn(main(itineraryId, 3));
        stubDayLookup(itineraryId, 3);
        when(agentService.planContext(anyString(), any(), any())).thenReturn(json.createObjectNode());
        when(agentService.generateDay(any())).thenAnswer(invocation -> {
            java.util.Map<String, Object> payload = invocation.getArgument(0);
            return dayNode((int) payload.get("day_no"), null);
        });
        // 预占第 2 天日锁 → 该天被跳过（语义与并发任务持锁一致）
        assertTrue(gate.tryMark(itineraryId, 2));
        // 第 2 天被跳过即存在未 SUCCEEDED 天（编排层只做汇总判断）
        when(dayPersistenceService.allDaysSucceeded(itineraryId)).thenReturn(false);

        planner.planDays(7L, itineraryId, request(3), null);

        verify(agentService, times(2)).generateDay(any());
        ArgumentCaptor<ItineraryMain> finished = ArgumentCaptor.forClass(ItineraryMain.class);
        verify(dayPersistenceService).completeTrip(finished.capture(), eq(false));
        assertEquals(itineraryId, finished.getValue().getId());
    }

    // ===== P1-6：壳数据可见性 =====

    /** 壳数据不可见时快速失败：不再盲等 5 秒，也不进入生成/落库（如实置失败终态）。 */
    @Test
    void invisibleShellFailsFastWithoutBlindWait() {
        long itineraryId = 1013L;
        when(mainMapper.selectById(itineraryId)).thenReturn(null);

        long started = System.nanoTime();
        planner.planDays(7L, itineraryId, request(1), null);
        long elapsedMs = (System.nanoTime() - started) / 1_000_000;

        assertTrue(elapsedMs < 1000, "不应再盲等（旧实现 sleep 500ms ×10）");
        verify(agentService, never()).generateDay(any());
        verify(mainMapper, never()).update(isNull(), any(Wrapper.class));
        verify(dayPersistenceService).failTrip(eq(itineraryId), contains("壳数据不存在"));
    }

    // ===== P0-1：流事件契约（contracts/stream_events.schema.json）=====

    /** 契约拒绝的事件不落库（不再 convertValue 静默落 null），缺失天由逐日循环修复。 */
    @Test
    void contractRejectedDayEventFallsBackToPerDayGeneration() throws Exception {
        long itineraryId = 1011L;
        when(mainMapper.selectById(itineraryId)).thenReturn(main(itineraryId, 1));
        when(dayPersistenceService.unfinishedDayNos(itineraryId)).thenReturn(List.of(1));
        when(agentService.planContext(anyString(), any(), any())).thenReturn(json.createObjectNode());
        // 整段流：start + 字段改名的 day 事件（dayNo → day_no）+ done
        doAnswer(invocation -> {
            java.util.function.Consumer<tools.jackson.databind.JsonNode> onLine =
                    invocation.getArgument(1);
            onLine.accept(json.readTree("{\"type\":\"start\",\"runId\":\"r-1\"}"));
            onLine.accept(json.readTree("{\"type\":\"day\",\"plan\":{\"day_no\":1,\"items\":[]}}"));
            onLine.accept(json.readTree("{\"type\":\"done\",\"daysExpected\":1,\"daysEmitted\":[],"
                    + "\"tripTheme\":null,\"complete\":false,\"message\":null}"));
            return null;
        }).when(agentService).generateTripStream(any(), any());
        when(dayPersistenceService.findDay(itineraryId, 1)).thenReturn(day(itineraryId, 1, "PENDING"));
        when(agentService.generateDay(any())).thenReturn(dayNode(1, null));

        planner.planDays(7L, itineraryId, request(1), null);

        // 契约拒绝：流路径的 7 参落库从未发生（旧实现会静默丢弃并留下 null 字段）
        verify(dayPersistenceService, never())
                .persist(anyLong(), any(), anyInt(), any(), anyString(), anyString(), anyBoolean());
        // 逐日循环兜底修复该天（6 参落库），行程仍可完成
        verify(agentService, times(1)).generateDay(any());
        verify(dayPersistenceService, times(1))
                .persist(eq(itineraryId), any(), anyInt(), any(), anyString(), anyString());
    }

    /** 契约违规超阈值（>3）：中止整段流，异常被编排吸收后仍走逐日修复降级。 */
    @Test
    void contractViolationThresholdAbortsStreamAndFallsBack() throws Exception {
        long itineraryId = 1012L;
        when(mainMapper.selectById(itineraryId)).thenReturn(main(itineraryId, 1));
        when(dayPersistenceService.unfinishedDayNos(itineraryId)).thenReturn(List.of(1));
        when(agentService.planContext(anyString(), any(), any())).thenReturn(json.createObjectNode());
        doAnswer(invocation -> {
            java.util.function.Consumer<tools.jackson.databind.JsonNode> onLine =
                    invocation.getArgument(1);
            // 4 条违规事件：第 4 条触发 >3 阈值即抛 BizException(502) 中止流
            for (int i = 0; i < 4; i++) {
                onLine.accept(json.readTree("{\"type\":\"day\",\"plan\":{\"day_no\":1,\"items\":[]}}"));
            }
            return null;
        }).when(agentService).generateTripStream(any(), any());
        when(dayPersistenceService.findDay(itineraryId, 1)).thenReturn(day(itineraryId, 1, "PENDING"));
        when(agentService.generateDay(any())).thenReturn(dayNode(1, null));

        planner.planDays(7L, itineraryId, request(1), null);

        verify(agentService, times(1)).generateDay(any());
        verify(dayPersistenceService, times(1))
                .persist(eq(itineraryId), any(), anyInt(), any(), anyString(), anyString());
        verify(dayPersistenceService).completeTrip(any(ItineraryMain.class), eq(true));
    }

    // ===== M3-③：整趟主题捕获 =====

    /** 第 1 天落库成功后捕获 trip_theme：单列 LambdaUpdateWrapper 写 itinerary_main.trip_theme（禁止整行 updateById）。 */
    @Test
    void firstDayTripThemeCapturedViaSingleColumnUpdate() throws Exception {
        long itineraryId = 1009L;
        when(mainMapper.selectById(itineraryId)).thenReturn(main(itineraryId, 1));
        when(dayPersistenceService.findDay(itineraryId, 1)).thenReturn(day(itineraryId, 1, "PENDING"));
        when(agentService.planContext(anyString(), any(), any())).thenReturn(json.createObjectNode());
        when(agentService.generateDay(any())).thenReturn(
                json.readTree("{\"dayNo\":1,\"items\":[],\"tripTheme\":\" 江南水乡慢旅行 \"}"));

        planner.planDays(7L, itineraryId, request(1), null);

        @SuppressWarnings({"unchecked", "rawtypes"})
        ArgumentCaptor<Wrapper<ItineraryMain>> updates = ArgumentCaptor.forClass((Class) Wrapper.class);
        // 开场置 GENERATING 一次 + day1 主题捕获一次；其余主表写回均下沉 PersistenceService
        verify(mainMapper, times(2)).update(isNull(), updates.capture());
        com.baomidou.mybatisplus.core.conditions.update.Update themeUpdate =
                (com.baomidou.mybatisplus.core.conditions.update.Update) updates.getAllValues().get(1);
        assertTrue(themeUpdate.getSqlSet().contains("trip_theme"), "应为 trip_theme 单列更新");
        com.baomidou.mybatisplus.core.conditions.AbstractWrapper<?, ?, ?> themeWrapper =
                (com.baomidou.mybatisplus.core.conditions.AbstractWrapper<?, ?, ?>) updates.getAllValues().get(1);
        assertTrue(themeWrapper.getParamNameValuePairs().containsValue("江南水乡慢旅行"),
                "写入值应为 trim 后的主题");
    }

    /** day1 未携带 tripTheme（旧口径/降级响应）时不产生额外主表 update。 */
    @Test
    void noTripThemeInFirstDayPlanMeansNoExtraMainUpdate() throws Exception {
        long itineraryId = 1010L;
        when(mainMapper.selectById(itineraryId)).thenReturn(main(itineraryId, 1));
        when(dayPersistenceService.findDay(itineraryId, 1)).thenReturn(day(itineraryId, 1, "PENDING"));
        when(agentService.planContext(anyString(), any(), any())).thenReturn(json.createObjectNode());
        when(agentService.generateDay(any())).thenReturn(dayNode(1, null));

        planner.planDays(7L, itineraryId, request(1), null);

        // 仅有开场置 GENERATING 的一次 update
        verify(mainMapper, times(1)).update(isNull(), any(Wrapper.class));
    }

    // ===== M1：intent 贯通（重构方案 §4.1.1）=====

    /** resolveIntent：intent 有值时 trim 后返回，优先于 requirements。 */
    @Test
    void resolveIntentTrimsAndPrefersExplicitIntent() {
        GenerateRequest request = request(3);
        request.setIntent("  想去杭州看西湖  ");
        request.setRequirements("预算五万");
        assertEquals("想去杭州看西湖", ItineraryAsyncPlanner.resolveIntent(request));
    }

    /** resolveIntent：intent 空白或 null 时以 requirements 兜底。 */
    @Test
    void resolveIntentFallsBackToRequirementsWhenIntentBlankOrNull() {
        GenerateRequest blank = request(3);
        blank.setIntent("   ");
        blank.setRequirements("预算五万");
        assertEquals("预算五万", ItineraryAsyncPlanner.resolveIntent(blank));

        GenerateRequest absent = request(3);
        absent.setRequirements("预算五万");
        assertEquals("预算五万", ItineraryAsyncPlanner.resolveIntent(absent));
    }

    /** resolveIntent：intent 与 requirements 皆空（含 request 为 null）时返回空串而非 null。 */
    @Test
    void resolveIntentReturnsEmptyStringWhenBothAbsent() {
        assertEquals("", ItineraryAsyncPlanner.resolveIntent(request(3)));
        assertEquals("", ItineraryAsyncPlanner.resolveIntent(null));
    }

    /** M1 透传点 1（AD8 逐日语义）：多日路径把兜底后的 intent 放入每天的 generateDay payload。 */
    @Test
    void multiDayPassesResolvedIntentToGenerateDayPayload() throws Exception {
        long itineraryId = 1006L;
        when(mainMapper.selectById(itineraryId)).thenReturn(main(itineraryId, 3));
        stubDayLookup(itineraryId, 3);
        when(agentService.planContext(anyString(), any(), any())).thenReturn(json.createObjectNode());
        when(agentService.generateDay(any())).thenAnswer(invocation -> {
            java.util.Map<String, Object> payload = invocation.getArgument(0);
            return dayNode((int) payload.get("day_no"), null);
        });

        GenerateRequest request = request(3);
        request.setIntent("  想去杭州看西湖  ");
        planner.planDays(7L, itineraryId, request, null);

        @SuppressWarnings({"unchecked", "rawtypes"})
        ArgumentCaptor<java.util.Map<String, Object>> captor =
                ArgumentCaptor.forClass((Class) java.util.Map.class);
        verify(agentService, times(3)).generateDay(captor.capture());
        assertTrue(captor.getAllValues().stream()
                .allMatch(payload -> "想去杭州看西湖".equals(payload.get("intent"))));
        verify(agentService, never()).generateTripStream(any(), any());
    }

    /** M1 透传点 2：单日路径把兜底后的 intent 放入 generateDay payload。 */
    @Test
    void singleDayPassesResolvedIntentToGenerateDayPayload() throws Exception {
        long itineraryId = 1007L;
        when(mainMapper.selectById(itineraryId)).thenReturn(main(itineraryId, 1));
        when(dayPersistenceService.findDay(itineraryId, 1)).thenReturn(day(itineraryId, 1, "PENDING"));
        when(agentService.planContext(anyString(), any(), any())).thenReturn(
                new tools.jackson.databind.ObjectMapper().createObjectNode());
        when(agentService.generateDay(any())).thenReturn(
                new tools.jackson.databind.ObjectMapper().readTree("{\"dayNo\":1,\"items\":[]}"));

        GenerateRequest request = request(1);
        request.setRequirements("预算五万");
        planner.planDays(7L, itineraryId, request, null);

        @SuppressWarnings({"unchecked", "rawtypes"})
        ArgumentCaptor<java.util.Map<String, Object>> captor =
                ArgumentCaptor.forClass((Class) java.util.Map.class);
        verify(agentService).generateDay(captor.capture());
        assertEquals("预算五万", captor.getValue().get("intent"));
    }
}
