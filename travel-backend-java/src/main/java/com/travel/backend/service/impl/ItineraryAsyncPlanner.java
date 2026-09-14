package com.travel.backend.service.impl;

import tools.jackson.databind.json.JsonMapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.NullNode;
import com.travel.backend.common.AgentStreamContract;
import com.travel.backend.common.BizException;
import com.travel.backend.common.ItineraryEventPublisher;
import com.travel.backend.dto.AgentGenerateResponse;
import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.mapper.ItineraryMainMapper;
import com.travel.backend.service.AgentService;
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

    private final AgentService agentService;
    private final ItineraryMainMapper mainMapper;
    private final ItineraryDayPersistenceService dayPersistenceService;
    private final ItineraryVersionService versionService;
    private final ItineraryGenerationGate gate;
    private final ItineraryEnricher enricher;
    private final BudgetEngine budgetEngine;
    private final Executor enricherExecutor;
    private final CacheManager cacheManager;
    private final ItineraryEventPublisher eventPublisher;
    private final ObjectMapper objectMapper = JsonMapper.builder().build();
    /** 流内契约违规容忍上限：超过视为协议破坏，中止整段流交给逐日修复降级。 */
    private static final int STREAM_CONTRACT_ERROR_LIMIT = 3;

    public ItineraryAsyncPlanner(AgentService agentService, ItineraryMainMapper mainMapper,
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
            // 壳数据可见性：创建路径无事务、insert 即提交，异步任务在提交后才入队执行，
            // 因此这里只需一次防御性检查，不做盲等重试（旧实现 sleep 500ms ×10 属于
            // 事务可见性问题的错误解法）。注意：若将来给 create 加事务，必须改为
            // afterCommit 后再提交异步任务，而不是恢复轮询。
            if (mainMapper.selectById(itineraryId) == null) {
                log.error("itinerary shell {} not visible before planning; abort", itineraryId);
                throw new BizException(500, "行程壳数据不存在，无法开始生成");
            }
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
            // 整段流式升级：全新行程一次 LLM 生成整趟——模型看得见全盘，跨天重复
            // 与地理走回头路在源头收敛；Python 边流边落地，Java 逐天落库（前端经
            // 既有 SSE 逐天点亮）。恢复续跑（部分天已 SUCCEEDED）仍走逐日循环只补失败天。
            boolean freshTrip = dayPersistenceService.unfinishedDayNos(itineraryId).size() >= request.getDays();
            boolean suggestionsPersisted = false;
            if (freshTrip) {
                try {
                    suggestionsPersisted = planWholeTrip(userId, itineraryId, request, context, fingerprint);
                } catch (Exception streamEx) {
                    log.warn("whole-trip stream failed for itinerary {}: {}; fallback to per-day loop",
                            itineraryId, streamEx.getMessage());
                }
            }
            // 幂等逐日循环：整段流式已成功的天在此只做幂等校验与 used 登记，
            // 缺失/失败天逐日修复（含单日反思重试），保证最终每天齐备。
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
            // 备选池（发现更多）：整段流式已持久化时跳过，避免用修复路径的
            // 第 1 天 suggestions 覆盖整段建议池；否则沿用第 1 天返回（多日与单日语义一致）
            if (!suggestionsPersisted) {
                enricher.persistSuggestions(itineraryId, firstDaySuggestions);
            }
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

    /**
     * 整段流式生成：调 Python /v1/generate-stream（JSON Lines），逐天落库。
     *
     * <p>事件处理：day/day_patch → 幂等校验后落库并转发 dayStart/dayDone 事件；
     * suggestions → 直接持久化备选池（整段建议池比单日更丰富）；
     * done → 捕获整趟主题与产出天清单；error → 仅记日志，缺天交给逐日循环修复。</p>
     *
     * @return 是否已在流内持久化备选池（调用方据此决定是否用第 1 天 suggestions 兜底）
     */
    private boolean planWholeTrip(Long userId, Long itineraryId, GenerateRequest request,
                                  JsonNode context, String fingerprint) {
        final int totalDays = request.getDays();
        Map<String, Object> payload = new java.util.HashMap<>();
        payload.put("city", request.getCity());
        payload.put("persons", request.getPersons());
        payload.put("budget", request.getBudget() == null ? null : request.getBudget().doubleValue());
        payload.put("start_date", request.getStartDate() == null ? null : request.getStartDate().toString());
        payload.put("day_no", 1);
        payload.put("days", totalDays);
        payload.put("used_names", List.of());
        payload.put("hotel_tier", request.getHotelTier());
        payload.put("chosen_hotel", null);
        payload.put("needs_hotel", request.getStayNights() != null && request.getStayNights() > 0);
        payload.put("requirements", request.getRequirements());
        payload.put("intent", resolveIntent(request));
        payload.put("context", context);
        payload.put("request_id", "itinerary-" + itineraryId);
        log.info("whole-trip stream generating itinerary {} ({} days)", itineraryId, totalDays);
        final boolean[] suggestionsDone = {false};
        final boolean[] doneSeen = {false};
        final int[] contractErrors = {0};
        try {
            agentService.generateTripStream(payload, node -> {
                String type = node.path("type").asText("");
                if (!AgentStreamContract.get().isKnownType(node)) {
                    // 未知类型 = Python 侧前向兼容的附加事件：忽略且不计数（增量演进不算协议破坏）
                    log.debug("stream event with unknown type ignored for {}: {}", itineraryId, type);
                    return;
                }
                List<String> violations = AgentStreamContract.get().violations(node);
                if (!violations.isEmpty()) {
                    // 字段改名/缺失必须响亮：拒绝进入 convertValue，避免静默落 null 或丢事件
                    contractErrors[0]++;
                    log.warn("stream event rejected by contract for {} (#{}): type={} {}",
                            itineraryId, contractErrors[0], type,
                            AgentStreamContract.summarize(violations));
                    if (contractErrors[0] > STREAM_CONTRACT_ERROR_LIMIT) {
                        throw new BizException(502, "行程流事件契约校验失败");
                    }
                    return;
                }
                switch (type) {
                    case "day", "day_patch" -> {
                        JsonNode planNode = node.get("plan");
                        if (planNode == null || planNode.isNull()) {
                            return;
                        }
                        int dayNo = planNode.path("dayNo").asInt(0);
                        if (dayNo < 1 || dayNo > totalDays) {
                            log.warn("stream day_no out of range for {}: {}", itineraryId, dayNo);
                            return;
                        }
                        AgentGenerateResponse.DailyPlan plan =
                                objectMapper.convertValue(planNode, AgentGenerateResponse.DailyPlan.class);
                        try {
                            persistStreamDay(userId, itineraryId, request, dayNo, plan, fingerprint,
                                    "day_patch".equals(type));
                        } catch (Exception ex) {
                            // 单天落库失败不中断流：该天留待逐日循环修复
                            log.warn("stream day {} persist failed for {}: {}", dayNo, itineraryId, ex.getMessage());
                        }
                    }
                    case "suggestions" -> {
                        try {
                            JsonNode items = node.get("items");
                            if (items == null || !items.isArray() || items.isEmpty()) {
                                return;
                            }
                            List<AgentGenerateResponse.Suggestion> rows = objectMapper.convertValue(
                                    items, new tools.jackson.core.type.TypeReference<List<AgentGenerateResponse.Suggestion>>() {
                                    });
                            enricher.persistSuggestions(itineraryId, rows);
                            suggestionsDone[0] = true;
                        } catch (Exception ex) {
                            log.warn("stream suggestions persist failed for {}: {}", itineraryId, ex.getMessage());
                        }
                    }
                    case "done" -> {
                        doneSeen[0] = true;
                        String tripTheme = node.path("tripTheme").asText("");
                        if (!tripTheme.isBlank()) {
                            // 整趟主题落库：与 day1 幂等重写口径一致（单列更新防并发覆盖）
                            mainMapper.update(null, new LambdaUpdateWrapper<ItineraryMain>()
                                    .eq(ItineraryMain::getId, itineraryId)
                                    .set(ItineraryMain::getTripTheme, tripTheme.trim()));
                        }
                        log.info("whole-trip stream done for {}: emitted {} of {} days, complete={}",
                                itineraryId, node.path("daysEmitted").size(), totalDays,
                                node.path("complete").asBoolean());
                    }
                    case "error" -> log.warn("whole-trip stream error for {}: {}",
                            itineraryId, node.path("message").asText(""));
                    default -> { }
                }
            });
            if (contractErrors[0] > 0) {
                log.warn("whole-trip stream for {} finished with {} contract violation(s); "
                        + "affected days fall back to per-day generation", itineraryId, contractErrors[0]);
            }
        } catch (Exception streamEx) {
            // done 事件已完整处理后的连接收尾异常（如 Premature EOF）不影响结果：
            // 缺失天仍会由逐日循环幂等修复，这里不向调用方升级为整段失败。
            if (doneSeen[0]) {
                log.info("stream closed after done for itinerary {} ({}), ignoring: {}",
                        itineraryId, streamEx.getMessage(), streamEx.getClass().getSimpleName());
            } else {
                throw streamEx;
            }
        }
        return suggestionsDone[0];
    }

    /** 整段流式的单天落库：日锁 → 幂等校验 → markRunning → persist → 事件 → 缓存/预算。 */
    private void persistStreamDay(Long userId, Long itineraryId, GenerateRequest request, int dayNo,
                                  AgentGenerateResponse.DailyPlan plan, String fingerprint,
                                  boolean overwrite) {
        String actionId = "day-" + itineraryId + "-" + dayNo;
        if (!gate.tryMark(itineraryId, dayNo)) {
            log.warn("stream day lock busy, skip itinerary {} day {}", itineraryId, dayNo);
            return;
        }
        try {
            ItineraryDay day = dayPersistenceService.findDay(itineraryId, dayNo);
            if (day == null) {
                throw new BizException(500, "行程日不存在");
            }
            gate.verifyAction(day, actionId, fingerprint);
            if (!"SUCCEEDED".equals(day.getGenerationStatus()) || overwrite) {
                dayPersistenceService.markRunning(day, actionId, fingerprint);
                eventPublisher.dayStart(itineraryId, dayNo);
                dayPersistenceService.persist(itineraryId, request, dayNo, plan, actionId, fingerprint, overwrite);
                eventPublisher.dayDone(itineraryId, dayNo, plan.getTheme(),
                        plan.getItems() == null ? 0 : plan.getItems().size(), plan.getNote());
                ItineraryEnricher.evictDetailCache(cacheManager, userId, itineraryId);
                submitBudgetRecalculate(itineraryId);
            }
        } finally {
            gate.unmark(itineraryId, dayNo);
        }
    }

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
