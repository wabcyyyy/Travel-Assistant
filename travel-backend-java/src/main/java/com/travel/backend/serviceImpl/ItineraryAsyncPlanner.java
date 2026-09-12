package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.NullNode;
import com.travel.backend.common.BizException;
import com.travel.backend.common.ItineraryEventPublisher;
import com.travel.backend.dto.AgentGenerateResponse;
import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.mapper.ItineraryMainMapper;
import com.travel.backend.service.BudgetEngine;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.cache.CacheManager;
import org.springframework.core.task.TaskRejectedException;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executor;

/**
 * 逐日流式生成编排（纯流程）：等壳 → 置 GENERATING → 指纹（幂等门）→ 上下文一次 →
 * 逐日「日锁/校验/落库/预算异步重算/精确失效」→ 备选池 → 汇总终态，失败走 fail。
 * 幂等原语/事务写入/富化分别收拢在 {@link ItineraryGenerationGate}、
 * {@link ItineraryDayPersistenceService}、{@link ItineraryEnricher}，本类只做流程编排。
 */
@Slf4j
@Service
public class ItineraryAsyncPlanner {

    private final AgentServiceImpl agentService;
    private final ItineraryMainMapper mainMapper;
    private final ItineraryDayPersistenceService dayPersistenceService;
    private final ItineraryVersionService versionService;
    private final ItineraryGenerationGate gate;
    private final ItineraryEnricher enricher;
    private final BudgetEngine budgetEngine;
    private final Executor enricherExecutor;
    private final CacheManager cacheManager;
    private final ItineraryEventPublisher eventPublisher;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public ItineraryAsyncPlanner(AgentServiceImpl agentService, ItineraryMainMapper mainMapper,
                                 ItineraryDayPersistenceService dayPersistenceService,
                                 ItineraryVersionService versionService,
                                 ItineraryGenerationGate gate, ItineraryEnricher enricher,
                                 BudgetEngine budgetEngine, CacheManager cacheManager,
                                 @Qualifier("enricherExecutor") Executor enricherExecutor,
                                 ItineraryEventPublisher eventPublisher) {
        this.agentService = agentService;
        this.mainMapper = mainMapper;
        this.dayPersistenceService = dayPersistenceService;
        this.versionService = versionService;
        this.gate = gate;
        this.enricher = enricher;
        this.budgetEngine = budgetEngine;
        this.enricherExecutor = enricherExecutor;
        this.cacheManager = cacheManager;
        this.eventPublisher = eventPublisher;
    }

    // 生成任务用独立有界线程池（AsyncConfig.generationExecutor）+ AbortPolicy：拒绝异常在提交点抛出，
    // 由调用方（ItineraryGenerationService / 恢复任务）转成 429 或下轮重试。
    @Async("generationExecutor")
    public void planDays(Long userId, Long itineraryId, GenerateRequest request, JsonNode context) {
        try {
            // 等待壳数据可见（generate 无事务，正常已提交；兜底重试）
            for (int i = 0; i < 10 && mainMapper.selectById(itineraryId) == null; i++) Thread.sleep(500);
            // 显式状态机（J3）：开始（含恢复续跑）即刷新 GENERATING/开始时间，恢复任务据此识别僵尸任务
            mainMapper.update(null, new LambdaUpdateWrapper<ItineraryMain>()
                    .eq(ItineraryMain::getId, itineraryId)
                    .set(ItineraryMain::getGenState, "GENERATING")
                    .set(ItineraryMain::getGenStartedAt, LocalDateTime.now()));
            List<String> usedNames = new ArrayList<>();
            String chosenHotel = null;
            List<AgentGenerateResponse.Suggestion> firstDaySuggestions = null;
            String fingerprint = gate.requestFingerprint(request);
            // AD8：多日/单日统一「一次研究 + 逐日生成」；上下文检索含 RAG/MCP/地图网络请求，留在异步线程
            if (context == null || context.isNull() || context == NullNode.getInstance()) {
                // 带 itineraryId 调 planContext：Python 据此发布研究阶段事件到 gen:events:{id}
                context = agentService.planContext(request.getCity(), request.getPreferences(), itineraryId);
            }
            for (int dayNo = 1; dayNo <= request.getDays(); dayNo++) {
                String actionId = "day-" + itineraryId + "-" + dayNo;
                if (!gate.tryMark(itineraryId, dayNo)) {
                    log.warn("day lock busy, skip itinerary {} day {}", itineraryId, dayNo);
                    continue;
                }
                try {
                    ItineraryDay day = dayPersistenceService.findDay(itineraryId, dayNo);
                    if (day == null) {
                        throw new BizException(500, "行程日不存在");
                    }
                    if ("SUCCEEDED".equals(day.getGenerationStatus())) {
                        // 已成功天只做幂等校验与跨天去重登记，不重写；continue 同时跳过收尾失效（无变更）
                        gate.verifyAction(day, actionId, fingerprint);
                        dayPersistenceService.appendExistingItems(day, usedNames);
                        if (chosenHotel == null) chosenHotel = dayPersistenceService.existingHotel(day);
                        continue;
                    }
                    dayPersistenceService.markRunning(day, actionId, fingerprint);
                    // 事件尽力而为：通知前端该天开始生成（DB 状态仍是真相）
                    eventPublisher.dayStart(itineraryId, dayNo);
                    try {
                        AgentGenerateResponse.DailyPlan plan = generateAndPersistDay(
                                userId, itineraryId, request, context, dayNo, usedNames, chosenHotel, actionId, fingerprint);
                        if (dayNo == 1) {
                            firstDaySuggestions = plan.getSuggestions();
                            // M3-③：整趟主题仅 day_no=1 响应携带，落库成功后单列捕获
                            // （续跑重生成 day1 时幂等重写；禁止整行 updateById 以免覆盖并发编辑）
                            if (plan.getTripTheme() != null && !plan.getTripTheme().isBlank()) {
                                mainMapper.update(null, new LambdaUpdateWrapper<ItineraryMain>()
                                        .eq(ItineraryMain::getId, itineraryId)
                                        .set(ItineraryMain::getTripTheme, plan.getTripTheme().trim()));
                            }
                        }
                    } catch (Exception ex) {
                        dayPersistenceService.markFailed(day, actionId, fingerprint, ex.getMessage());
                        // 降级通知：该天生成失败待重试（scope=day_{n} 与事件协议约定一致）
                        eventPublisher.degraded(itineraryId, "day_" + dayNo, ex.getMessage(), "待重试");
                        throw ex;
                    }
                    ItineraryDay persistedDay = dayPersistenceService.findDay(itineraryId, dayNo);
                    if (persistedDay != null) {
                        dayPersistenceService.appendExistingItems(persistedDay, usedNames);
                        if (chosenHotel == null) chosenHotel = dayPersistenceService.existingHotel(persistedDay);
                    }
                } finally {
                    gate.unmark(itineraryId, dayNo);
                }
                // 每天落库后按 (userId, id) 精确失效详情缓存（J2）；预算重算移出 persist 事务（J5）
                ItineraryEnricher.evictDetailCache(cacheManager, userId, itineraryId);
                submitBudgetRecalculate(itineraryId);
            }
            // 备选池（发现更多）：来自第 1 天生成返回的未选点位，多日与单日语义一致（AD8）
            enricher.persistSuggestions(itineraryId, firstDaySuggestions);
            finish(userId, itineraryId, request);
        } catch (Exception e) {
            log.error("async planning failed for itinerary {}", itineraryId, e);
            // 整体失败通知：AGENT_ERROR 且可重试（协议约定 retryable=true）
            eventPublisher.error(itineraryId, "AGENT_ERROR", e.getMessage(), true);
            fail(userId, itineraryId, e.getMessage());
        }
    }

    /** 测试/运维：查询某天是否仍持锁（委托幂等门）。 */
    public boolean isDayLocked(Long itineraryId, int dayNo) { return gate.isMarked(itineraryId, dayNo); }

    private AgentGenerateResponse.DailyPlan generateAndPersistDay(
            Long userId, Long itineraryId, GenerateRequest request, JsonNode context, int dayNo,
            List<String> usedNames, String chosenHotel, String actionId, String fingerprint) {
        Map<String, Object> payload = new java.util.HashMap<>();
        payload.put("city", request.getCity());
        payload.put("persons", request.getPersons());
        payload.put("budget", request.getBudget() == null ? null : request.getBudget().doubleValue());
        payload.put("start_date", request.getStartDate() == null ? null : request.getStartDate().plusDays(dayNo - 1L).toString());
        payload.put("day_no", dayNo);
        payload.put("used_names", usedNames);
        payload.put("hotel_tier", request.getHotelTier());
        payload.put("chosen_hotel", chosenHotel);
        payload.put("needs_hotel", dayNo <= request.getStayNights());
        payload.put("requirements", request.getRequirements());
        payload.put("intent", resolveIntent(request));
        payload.put("context", context);
        payload.put("request_id", "itinerary-" + itineraryId);
        payload.put("action_id", actionId);
        JsonNode node = agentService.generateDay(payload);
        AgentGenerateResponse.DailyPlan plan = objectMapper.convertValue(node, AgentGenerateResponse.DailyPlan.class);
        dayPersistenceService.persist(itineraryId, request, dayNo, plan, actionId, fingerprint);
        // persist 成功后发 day_done：回执取自 DailyPlan（itemCount=plan.getItems() size，null 安全）
        eventPublisher.dayDone(itineraryId, dayNo, plan.getTheme(),
                plan.getItems() == null ? 0 : plan.getItems().size(), plan.getNote());
        return plan;
    }

    /** 意图兜底：用户未填 intent 时以 requirements 作为意图（M1 契约，重构方案 §4.1.1）。 */
    static String resolveIntent(GenerateRequest request) {
        String intent = request == null ? null : request.getIntent();
        if (intent != null && !intent.isBlank()) return intent.trim();
        return request == null || request.getRequirements() == null ? "" : request.getRequirements();
    }

    private void finish(Long userId, Long itineraryId, GenerateRequest request) {
        ItineraryMain main = mainMapper.selectById(itineraryId);
        if (main == null) { ItineraryEnricher.evictDetailCache(cacheManager, userId, itineraryId); return; }
        // 按天状态汇总终态（COMPLETED/PARTIAL）并单列写回；status 列维持 2 不变
        boolean allSucceeded = dayPersistenceService.allDaysSucceeded(itineraryId);
        dayPersistenceService.completeTrip(main, allSucceeded);
        Long versionId = null;
        try {
            Map<String, Object> snapshot =
                    versionService.createSnapshot(userId, itineraryId, "generate", "行程生成完成");
            // createSnapshot 返回含 id 的 Map（见 ItineraryVersionService），有返回值就用其 id
            if (snapshot != null && snapshot.get("id") instanceof Number number) {
                versionId = number.longValue();
            }
        } catch (Exception snapshotError) { // 版本快照是可恢复能力，不能让已成功生成的行程被降级为失败
            log.warn("version snapshot failed for {}: {}", itineraryId, snapshotError.getMessage());
        }
        // 终态事件：前端据此停止监听；degradedDays=未 SUCCEEDED 的 dayNo（列表接口失败时兜底为空）
        List<Integer> degradedDays = dayPersistenceService.unfinishedDayNos(itineraryId);
        eventPublisher.complete(itineraryId, allSucceeded ? "COMPLETED" : "PARTIAL",
                main.getDays(), degradedDays, versionId);
        submitBudgetRecalculate(itineraryId);
        try { enricher.enrichItinerary(main, request, itineraryId); }
        catch (TaskRejectedException rejected) { // 富化是可选增强：富化池满被拒即弃，不影响主流程
            log.warn("itinerary enrichment rejected for {}: {}", itineraryId, rejected.getMessage());
        }
        ItineraryEnricher.evictDetailCache(cacheManager, userId, itineraryId);
    }

    private void fail(Long userId, Long itineraryId, String message) {
        // failTrip 不清除 gen_resumed：续跑再失败时恢复任务依据它阻止二次续跑（防死循环）
        dayPersistenceService.failTrip(itineraryId, message);
        ItineraryEnricher.evictDetailCache(cacheManager, userId, itineraryId);
    }

    /** 预算重算移出 persist 事务（J5）：异步提交到富化池；被拒只 warn，后续天/finish 还会再算。 */
    private void submitBudgetRecalculate(Long itineraryId) {
        try {
            enricherExecutor.execute(() -> budgetEngine.recalculate(itineraryId));
        } catch (TaskRejectedException rejected) {
            log.warn("budget recalculate rejected for {}: {}", itineraryId, rejected.getMessage());
        }
    }
}
