package com.travel.backend.serviceImpl;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.NullNode;
import com.travel.backend.common.BizException;
import com.travel.backend.common.DistributedStateService;
import com.travel.backend.dto.AgentGenerateResponse;
import com.travel.backend.dto.AgentGenerateRequest;
import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.mapper.ItineraryDayMapper;
import com.travel.backend.mapper.ItineraryItemMapper;
import com.travel.backend.mapper.ItineraryMainMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.CacheManager;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.concurrent.CompletableFuture;

/**
 * 逐日流式生成编排：每天完成即落库并清缓存，前端轮询可见渐进结果。
 */
@Slf4j
@Service
public class ItineraryAsyncPlanner {

    private final AgentServiceImpl agentService;
    private final ItineraryDayMapper dayMapper;
    private final ItineraryItemMapper itemMapper;
    private final ItineraryMainMapper mainMapper;
    private final ItineraryDayPersistenceService dayPersistenceService;
    private final ItineraryVersionService versionService;
    private final CacheManager cacheManager;
    private final DistributedStateService state;
    private final ObjectMapper objectMapper = new ObjectMapper();
    /** 日生成互斥：Redis SETNX（跨实例）；单机 Redis 故障时降级进程内。 */
    private static final Duration DAY_LOCK_TTL = Duration.ofMinutes(5);
    /** 恢复任务自动续跑时写入的标记；fail() 在再次失败时保留它，保证每个行程最多自动续跑一次。 */
    public static final String RESUME_MARKER = "[已自动续跑一次]";

    public ItineraryAsyncPlanner(AgentServiceImpl agentService, ItineraryDayMapper dayMapper,
                                 ItineraryItemMapper itemMapper, ItineraryMainMapper mainMapper,
                                 ItineraryDayPersistenceService dayPersistenceService,
                                 ItineraryVersionService versionService,
                                 CacheManager cacheManager,
                                 DistributedStateService state) {
        this.agentService = agentService;
        this.dayMapper = dayMapper;
        this.itemMapper = itemMapper;
        this.mainMapper = mainMapper;
        this.dayPersistenceService = dayPersistenceService;
        this.versionService = versionService;
        this.cacheManager = cacheManager;
        this.state = state;
    }

    // 生成任务使用独立有界线程池 + AbortPolicy：整段生成对 Python 的读超时可达
    // 180s，若沿用全局 CallerRunsPolicy 会在队列满时退化为 Tomcat 请求线程内
    // 同步执行，并发创建即可耗尽 HTTP 线程（自 DoS）。拒绝异常在提交点抛出，
    // 由调用方（ItineraryGenerationService / 恢复任务）转成 429 或下轮重试。
    @Async("generationExecutor")
    public void planDays(Long userId, Long itineraryId, GenerateRequest request, JsonNode context) {
        try {
            // 等待壳数据可见（generate 无事务，正常已提交；兜底重试）
            for (int i = 0; i < 10; i++) {
                if (mainMapper.selectById(itineraryId) != null) break;
                Thread.sleep(500);
            }
            List<String> usedNames = new ArrayList<>();
            String chosenHotel = null;
            List<AgentGenerateResponse.Suggestion> firstDaySuggestions = null;
            String fingerprint = requestFingerprint(request);

            // 多日规划改用一次整段生成：原实现每天单独请求模型，7 天会产生
            // 7 次网络往返和 7 次推理。整段结果仍按天事务落库，前端继续
            // 使用原有轮询契约，但总等待时间只受一次模型调用影响。
            if (request.getDays() != null && request.getDays() > 1) {
                generateWholeTrip(userId, itineraryId, request, fingerprint);
                finish(userId, itineraryId, request);
                return;
            }

            // 上下文检索可能访问 RAG、MCP 和地图服务，放在异步线程中，避免
            // POST /generate 被外部网络延迟拖住。恢复任务仍可传入已有 context。
            if (context == null || context.isNull() || context == NullNode.getInstance()) {
                context = agentService.planContext(request.getCity(), request.getPreferences());
            }

            for (int dayNo = 1; dayNo <= request.getDays(); dayNo++) {
                String actionId = "day-" + itineraryId + "-" + dayNo;
                String lockKey = dayLockKey(itineraryId, dayNo);
                if (!state.tryMark(lockKey, DAY_LOCK_TTL)) {
                    log.warn("day lock busy, skip itinerary {} day {}", itineraryId, dayNo);
                    continue;
                }
                try {
                    ItineraryDay day = findDay(itineraryId, dayNo);
                    if (day == null) {
                        throw new BizException(500, "行程日不存在");
                    }
                    if ("SUCCEEDED".equals(day.getGenerationStatus())) {
                        verifyAction(day, actionId, fingerprint);
                        appendExistingItems(day, usedNames);
                        if (chosenHotel == null) {
                            chosenHotel = existingHotel(day);
                        }
                        continue;
                    }
                    dayPersistenceService.markRunning(day, actionId, fingerprint);
                    try {
                        List<AgentGenerateResponse.Suggestion> daySuggestions = generateAndPersistDay(
                                userId, itineraryId, request, context, dayNo,
                                usedNames, chosenHotel, actionId, fingerprint);
                        if (dayNo == 1) {
                            firstDaySuggestions = daySuggestions;
                        }
                    } catch (Exception ex) {
                        dayPersistenceService.markFailed(day, actionId, fingerprint, ex.getMessage());
                        throw ex;
                    }
                    ItineraryDay persistedDay = findDay(itineraryId, dayNo);
                    if (persistedDay != null) {
                        appendExistingItems(persistedDay, usedNames);
                        if (chosenHotel == null) {
                            chosenHotel = existingHotel(persistedDay);
                        }
                    }
                } finally {
                    state.unmark(lockKey);
                }
                evictCache();
            }
            // 单日行程走逐日路径：备选池来自第 1 天生成时返回的未选点位
            persistSuggestions(itineraryId, firstDaySuggestions);
            finish(userId, itineraryId, request);
        } catch (Exception e) {
            log.error("async planning failed for itinerary {}", itineraryId, e);
            fail(itineraryId, e.getMessage());
        }
    }

    private static String dayLockKey(Long itineraryId, int dayNo) {
        return "gen:day:" + itineraryId + ":" + dayNo;
    }

    /** 测试/运维：查询某天是否仍持锁。 */
    public boolean isDayLocked(Long itineraryId, int dayNo) {
        return state.isMarked(dayLockKey(itineraryId, dayNo));
    }

    /** 整段生成前把未完成天标为 RUNNING，供恢复任务做 in-flight 判定。 */
    private void markDaysRunningForWholeTrip(Long itineraryId, String fingerprint) {
        List<ItineraryDay> days = dayMapper.selectList(
                new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<ItineraryDay>()
                        .eq(ItineraryDay::getItineraryId, itineraryId));
        for (ItineraryDay day : days) {
            if ("SUCCEEDED".equals(day.getGenerationStatus())
                    || "RUNNING".equals(day.getGenerationStatus())) {
                continue;
            }
            String actionId = "day-" + itineraryId + "-" + day.getDayNo();
            try {
                dayPersistenceService.markRunning(day, actionId, fingerprint);
            } catch (Exception ex) {
                log.warn("mark running failed for day {}: {}", day.getId(), ex.getMessage());
            }
        }
    }

    private void generateWholeTrip(Long userId, Long itineraryId, GenerateRequest request,
                                   String fingerprint) {
        // 防双提交：Agent 调用最长可达 180s，期间必须让恢复任务看到 RUNNING 天，
        // 否则 hasActiveDay=false 会再次 planDays 造成双倍推理与落库竞争。
        markDaysRunningForWholeTrip(itineraryId, fingerprint);
        AgentGenerateRequest agentRequest = new AgentGenerateRequest();
        agentRequest.setCity(request.getCity());
        agentRequest.setDays(request.getDays());
        agentRequest.setPersons(request.getPersons());
        agentRequest.setBudget(request.getBudget());
        agentRequest.setStartDate(request.getStartDate());
        agentRequest.setPreferences(request.getPreferences());
        agentRequest.setHotelTier(request.getHotelTier());
        agentRequest.setRegionHint(request.getRegionHint());
        agentRequest.setRequirements(request.getRequirements());

        AgentGenerateResponse response = agentService.generate(agentRequest);
        if (response == null || response.getDailyPlans() == null
                || response.getDailyPlans().size() < request.getDays()) {
            throw new BizException(502, "整段行程生成结果不完整");
        }
        // 契约透传：Python 端 0 可交付项/草案会如实返回 status=failed，
        // 绝不能当作成功落库为 SUCCEEDED（丽江事故的全栈侧镜像）。
        if ("failed".equals(response.getStatus())) {
            throw new BizException(502, "行程生成失败："
                    + (response.getStatusReason() == null ? "无有效行程内容" : response.getStatusReason()));
        }
        // 备选池（发现更多）：整段生成时由模型从候选池挑出的未排入行程点位
        persistSuggestions(itineraryId, response.getSuggestions());
        Map<Integer, AgentGenerateResponse.DailyPlan> byDay = response.getDailyPlans().stream()
                .filter(plan -> plan != null && plan.getDayNo() != null)
                .collect(java.util.stream.Collectors.toMap(
                        AgentGenerateResponse.DailyPlan::getDayNo, plan -> plan, (first, ignored) -> first));
        // #19：单天落库失败不再立即上抛拖死整个行程，而是标记该天失败并继续
        // 落其余天；全部结束后再汇总上抛。已成功的天保持 SUCCEEDED，恢复任务
        // 续跑时 planDays 会跳过它们，只补失败的天。
        List<Integer> failedDays = new ArrayList<>();
        String firstError = null;
        for (int dayNo = 1; dayNo <= request.getDays(); dayNo++) {
            String actionId = "day-" + itineraryId + "-" + dayNo;
            String lockKey = dayLockKey(itineraryId, dayNo);
            if (!state.tryMark(lockKey, DAY_LOCK_TTL)) {
                log.warn("day lock busy on whole-trip persist, skip itinerary {} day {}", itineraryId, dayNo);
                continue;
            }
            try {
                ItineraryDay day = findDay(itineraryId, dayNo);
                if (day == null) throw new BizException(500, "行程日不存在");
                if ("SUCCEEDED".equals(day.getGenerationStatus())) continue;
                AgentGenerateResponse.DailyPlan plan = byDay.get(dayNo);
                dayPersistenceService.markRunning(day, actionId, fingerprint);
                if (plan == null) {
                    dayPersistenceService.markFailed(day, actionId, fingerprint, "第" + dayNo + "天生成结果缺失");
                    failedDays.add(dayNo);
                    if (firstError == null) firstError = "第" + dayNo + "天生成结果缺失";
                } else {
                    try {
                        dayPersistenceService.persist(itineraryId, request, dayNo, plan, actionId, fingerprint);
                    } catch (Exception ex) {
                        dayPersistenceService.markFailed(day, actionId, fingerprint, ex.getMessage());
                        failedDays.add(dayNo);
                        if (firstError == null) firstError = ex.getMessage();
                    }
                }
            } finally {
                state.unmark(lockKey);
            }
            evictCache();
        }
        if (!failedDays.isEmpty()) {
            throw new BizException(500, "整段生成部分失败（第" + failedDays + "天）：" + firstError);
        }
    }

    private List<AgentGenerateResponse.Suggestion> generateAndPersistDay(Long userId, Long itineraryId, GenerateRequest request,
                                       JsonNode context, int dayNo, List<String> usedNames,
                                       String chosenHotel, String actionId, String fingerprint) {
                Map<String, Object> payload = new java.util.HashMap<>();
                payload.put("city", request.getCity());
                payload.put("persons", request.getPersons());
                payload.put("budget", request.getBudget() == null ? null
                        : request.getBudget().doubleValue());
                payload.put("start_date", request.getStartDate() == null ? null
                        : request.getStartDate().plusDays(dayNo - 1L).toString());
                payload.put("day_no", dayNo);
                payload.put("used_names", usedNames);
                payload.put("hotel_tier", request.getHotelTier());
                payload.put("chosen_hotel", chosenHotel);
                payload.put("needs_hotel", dayNo <= request.getStayNights());
                payload.put("requirements", request.getRequirements());
                payload.put("context", context);
                payload.put("request_id", "itinerary-" + itineraryId);
                payload.put("action_id", actionId);

                JsonNode node = agentService.generateDay(payload);
                AgentGenerateResponse.DailyPlan plan =
                        objectMapper.convertValue(node, AgentGenerateResponse.DailyPlan.class);
                dayPersistenceService.persist(itineraryId, request, dayNo, plan, actionId, fingerprint);
                return plan.getSuggestions();
    }

    /** 落库行程级备选池（发现更多）；失败只记日志，不影响行程主流程。 */
    private void persistSuggestions(Long itineraryId, List<AgentGenerateResponse.Suggestion> suggestions) {
        if (suggestions == null || suggestions.isEmpty()) {
            return;
        }
        try {
            // 单列更新：禁止整行 updateById，避免覆盖用户/富化流程写入的其它字段。
            mainMapper.update(null, new com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper<ItineraryMain>()
                    .eq(ItineraryMain::getId, itineraryId)
                    .set(ItineraryMain::getSuggestionsJson, objectMapper.writeValueAsString(suggestions)));
        } catch (Exception e) {
            log.warn("persist suggestions failed for {}: {}", itineraryId, e.getMessage());
        }
    }

    private ItineraryDay findDay(Long itineraryId, int dayNo) {
        return dayMapper.selectOne(new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<ItineraryDay>()
                .eq(ItineraryDay::getItineraryId, itineraryId)
                .eq(ItineraryDay::getDayNo, dayNo));
    }

    private void verifyAction(ItineraryDay day, String actionId, String fingerprint) {
        if (day.getGenerationActionId() != null && !actionId.equals(day.getGenerationActionId())) {
            throw new BizException(409, "该日期已有不同的生成动作，请使用最新任务");
        }
        if (day.getGenerationFingerprint() != null && !fingerprint.equals(day.getGenerationFingerprint())) {
            throw new BizException(409, "同一日期生成参数已发生变化，请重新创建行程");
        }
    }

    private void appendExistingItems(ItineraryDay day, List<String> usedNames) {
        itemMapper.selectList(new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<ItineraryItem>()
                        .eq(ItineraryItem::getDayId, day.getId()).orderByAsc(ItineraryItem::getSortNo))
                .stream().map(ItineraryItem::getPoiName).filter(name -> name != null && !name.isBlank())
                .forEach(usedNames::add);
    }

    private String existingHotel(ItineraryDay day) {
        return itemMapper.selectList(new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<ItineraryItem>()
                        .eq(ItineraryItem::getDayId, day.getId()))
                .stream().filter(item -> "hotel".equals(item.getItemType()))
                .map(ItineraryItem::getPoiName).findFirst().orElse(null);
    }

    private String requestFingerprint(GenerateRequest request) {
        String source = String.join("|",
                safe(request.getCity()), String.valueOf(request.getDays()), String.valueOf(request.getPersons()),
                String.valueOf(request.getStayNights()), String.valueOf(request.getBudget()),
                String.valueOf(request.getStartDate()), String.valueOf(request.getEndDate()),
                safe(request.getHotelTier()), String.join(",", request.getPreferences() == null ? List.of() : request.getPreferences()));
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(source.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder();
            for (byte value : digest) hex.append(String.format("%02x", value));
            return hex.toString();
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 不可用", impossible);
        }
    }

    private String safe(String value) {
        return value == null ? "" : value;
    }

    private void evictCache() {
        var cache = cacheManager.getCache("itinerary:detail");
        if (cache != null) {
            cache.clear();
        }
    }

    private void finish(Long userId, Long itineraryId, GenerateRequest request) {
        ItineraryMain main = mainMapper.selectById(itineraryId);
        if (main == null) {
            evictCache();
            return;
        }
        String title = main.getCity() + main.getDays() + "日游";
        // #19：续跑成功即清除内部续跑标记，避免残留文案出现在"AI 管家说"卡片。
        String planNote = main.getPlanNote();
        if (planNote != null && planNote.contains(RESUME_MARKER)) {
            planNote = planNote.replace(RESUME_MARKER, "").trim();
        }
        // 单列更新：长任务结束后禁止整行 updateById，避免覆盖用户并发编辑。
        mainMapper.update(null, new com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper<ItineraryMain>()
                .eq(ItineraryMain::getId, itineraryId)
                .set(ItineraryMain::getStatus, 2)
                .set(ItineraryMain::getTitle, title)
                .set(ItineraryMain::getPlanNote, planNote == null || planNote.isBlank() ? null : planNote));

        try {
            versionService.createSnapshot(userId, itineraryId, "generate", "行程生成完成");
        } catch (Exception snapshotError) {
            // 版本快照是可恢复能力，不能让已成功生成的行程被降级为失败。
            log.warn("version snapshot failed for completed itinerary {}: {}", itineraryId,
                    snapshotError.getMessage());
        }
        // 管家讲解和景点介绍属于可选增强，放到独立线程，不能拖慢主体行程完成。
        ItineraryMain enrichSource = mainMapper.selectById(itineraryId);
        if (enrichSource == null) {
            enrichSource = main;
        }
        final ItineraryMain enrichMain = enrichSource;
        CompletableFuture.runAsync(() -> enrichItinerary(enrichMain, request, itineraryId))
                .exceptionally(error -> {
                    log.warn("itinerary enrichment failed for {}: {}", itineraryId, error.getMessage());
                    return null;
                });
        evictCache();
    }

    private void enrichItinerary(ItineraryMain main, GenerateRequest request, Long itineraryId) {
        try {
            List<Map<String, Object>> plans = new ArrayList<>();
            for (ItineraryDay day : dayMapper.selectList(new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<ItineraryDay>()
                    .eq(ItineraryDay::getItineraryId, itineraryId).orderByAsc(ItineraryDay::getDayNo))) {
                List<String> names = itemMapper.selectList(new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<ItineraryItem>()
                                .eq(ItineraryItem::getDayId, day.getId()).orderByAsc(ItineraryItem::getSortNo))
                        .stream().map(ItineraryItem::getPoiName).filter(n -> n != null && !n.isBlank()).toList();
                if (names.isEmpty()) {
                    continue;
                }
                plans.add(Map.of("day_no", day.getDayNo(), "items", names));
            }
            if (plans.isEmpty()) {
                return;
            }
            Map<String, Object> payload = Map.of(
                    "city", main.getCity(),
                    "days", main.getDays(),
                    "persons", main.getPersons() == null ? 1 : main.getPersons(),
                    "preferences", main.getPreferences() == null ? "" : main.getPreferences(),
                    "hotel_tier", main.getHotelTier() == null ? "" : main.getHotelTier(),
                    "region_hint", request.getRegionHint() == null ? "" : request.getRegionHint(),
                    "budget", main.getBudget() == null ? "" : main.getBudget(),
                    "requirements", request.getRequirements() == null ? "" : request.getRequirements(),
                    "plans", plans);
            JsonNode noteNode = agentService.butlerNote(payload);
            String note = noteNode.path("note").asText("");
            if (!note.isBlank()) {
                // #20：讲解生成可耗时很久，期间用户可能并发修改同一行程的其它列。
                // 只按 id 精确回写本流程负责的 plan_note 单列，禁止用陈旧实体
                // updateById 全字段回写，避免丢更新竞态。
                mainMapper.update(null, new com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper<ItineraryMain>()
                        .eq(ItineraryMain::getId, itineraryId)
                        .set(ItineraryMain::getPlanNote, note));
            }
        } catch (Exception e) {
            log.warn("butler note failed for {}: {}", itineraryId, e.getMessage());
        }

        // 景点详细介绍：批量生成后逐条回填
        try {
            List<ItineraryItem> allItems = itemMapper.selectList(new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<ItineraryItem>()
                    .eq(ItineraryItem::getItineraryId, itineraryId));
            List<String> names = allItems.stream().map(ItineraryItem::getPoiName)
                    .filter(n -> n != null && !n.isBlank()).distinct().toList();
            if (!names.isEmpty()) {
                JsonNode introNode = agentService.poiIntros(
                        Map.of("city", main.getCity(), "names", names));
                JsonNode intros = introNode.get("intros");
                if (intros != null && intros.isObject()) {
                    for (ItineraryItem item : allItems) {
                        JsonNode intro = intros.get(item.getPoiName());
                        if (intro != null && !intro.asText().isBlank()) {
                            item.setIntro(intro.asText());
                            itemMapper.updateById(item);
                        }
                    }
                }
            }
        } catch (Exception e) {
            log.warn("poi intros failed for {}: {}", itineraryId, e.getMessage());
        }
        evictCache();
    }

    private void fail(Long itineraryId, String message) {
        ItineraryMain main = mainMapper.selectById(itineraryId);
        if (main != null) {
            String planNote = null;
            if (message != null && !message.isBlank()) {
                // #19：再次失败时保留续跑标记，恢复任务据此知道"已自动续跑过
                // 一次"而不再重拉，防止失败-重生成死循环。
                boolean resumed = main.getPlanNote() != null && main.getPlanNote().contains(RESUME_MARKER);
                planNote = "生成失败：" + message + (resumed ? " " + RESUME_MARKER : "");
            }
            mainMapper.update(null, new com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper<ItineraryMain>()
                    .eq(ItineraryMain::getId, itineraryId)
                    .set(ItineraryMain::getStatus, 3)
                    .set(ItineraryMain::getPlanNote, planNote));
        }
        evictCache();
    }
}
