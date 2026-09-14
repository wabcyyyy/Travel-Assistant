package com.travel.backend.service.impl;

import tools.jackson.databind.json.JsonMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import tools.jackson.databind.ObjectMapper;
import com.travel.backend.common.ItineraryEventPublisher;
import com.travel.backend.dto.AgentButlerNoteRequest;
import com.travel.backend.dto.AgentButlerNoteResponse;
import com.travel.backend.dto.AgentGenerateResponse;
import com.travel.backend.dto.AgentPoiIntrosRequest;
import com.travel.backend.dto.AgentPoiIntrosResponse;
import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.mapper.ItineraryDayMapper;
import com.travel.backend.mapper.ItineraryItemMapper;
import com.travel.backend.mapper.ItineraryMainMapper;
import com.travel.backend.service.AgentService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.CacheManager;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 行程生成收尾的辅助写回：备选池落库、AI 管家讲解与景点介绍富化。
 *
 * <p>独立成 Bean 是为了让富化挂到专用有界池（enricherExecutor）上：富化是可选增强，
 * 不能与主生成流程抢占线程资源，也不能沿用公共 ForkJoinPool 造成无界并发。</p>
 */
@Slf4j
@Service
public class ItineraryEnricher {

    private final AgentService agentService;
    private final ItineraryDayMapper dayMapper;
    private final ItineraryItemMapper itemMapper;
    private final ItineraryMainMapper mainMapper;
    private final CacheManager cacheManager;
    private final ItineraryEventPublisher eventPublisher;
    private final ObjectMapper objectMapper = JsonMapper.builder().build();

    public ItineraryEnricher(AgentService agentService, ItineraryDayMapper dayMapper,
                             ItineraryItemMapper itemMapper, ItineraryMainMapper mainMapper,
                             CacheManager cacheManager, ItineraryEventPublisher eventPublisher) {
        this.agentService = agentService;
        this.dayMapper = dayMapper;
        this.itemMapper = itemMapper;
        this.mainMapper = mainMapper;
        this.cacheManager = cacheManager;
        this.eventPublisher = eventPublisher;
    }

    /**
     * 富化增强：管家讲解写回 plan_note + 景点介绍逐条写回 intro，结束后精确失效详情缓存。
     * 拒绝（池满）与失败都只影响富化本身，不影响行程主流程。
     */
    @Async("enricherExecutor")
    public void enrichItinerary(ItineraryMain main, GenerateRequest request, Long itineraryId) {
        try {
            List<Map<String, Object>> plans = new ArrayList<>();
            for (ItineraryDay day : dayMapper.selectList(new LambdaQueryWrapper<ItineraryDay>()
                    .eq(ItineraryDay::getItineraryId, itineraryId).orderByAsc(ItineraryDay::getDayNo))) {
                List<String> names = itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                                .eq(ItineraryItem::getDayId, day.getId()).orderByAsc(ItineraryItem::getSortNo))
                        .stream().map(ItineraryItem::getPoiName).filter(n -> n != null && !n.isBlank()).toList();
                if (names.isEmpty()) {
                    continue;
                }
                plans.add(Map.of("day_no", day.getDayNo(), "items", names));
            }
            if (!plans.isEmpty()) {
                writeButlerNote(main, request, itineraryId, plans);
            }
        } catch (Exception e) {
            log.warn("butler note failed for {}: {}", itineraryId, e.getMessage());
            // 降级通知：讲解失败只影响富化增强，行程主流程不受影响
            eventPublisher.degraded(itineraryId, "butler", e.getMessage(), "跳过讲解");
        }

        // 景点详细介绍：按去重名称分批生成（一次全量在强模型下输出 4000+ token
        // 会被 max_tokens 截断致 JSON 解析失败返回空），逐条单列回填。
        try {
            List<String> names = itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                            .eq(ItineraryItem::getItineraryId, itineraryId)).stream()
                    .map(ItineraryItem::getPoiName).filter(n -> n != null && !n.isBlank()).distinct().toList();
            if (!names.isEmpty()) {
                Map<String, String> intros = new java.util.HashMap<>();
                final int introBatch = 8;
                for (int i = 0; i < names.size(); i += introBatch) {
                    List<String> chunk = names.subList(i, Math.min(i + introBatch, names.size()));
                    try {
                        AgentPoiIntrosRequest introRequest = new AgentPoiIntrosRequest();
                        introRequest.setCity(main.getCity());
                        introRequest.setNames(chunk);
                        // M3-③：poi-intros 透传意图，与 butlerNote/generate 的 intent 兜底口径一致
                        introRequest.setIntent(ItineraryAsyncPlanner.resolveIntent(request));
                        AgentPoiIntrosResponse introResponse = agentService.poiIntros(introRequest);
                        if (introResponse.getIntros() != null) {
                            intros.putAll(introResponse.getIntros());
                        }
                    } catch (Exception batchEx) {
                        log.warn("poi intros batch failed for {}: {}", itineraryId, batchEx.getMessage());
                    }
                }
                if (!intros.isEmpty()) {
                    // 单列更新而非整行 updateById：富化耗时长，期间用户可能并发编辑同一行，
                    // 整行回写会用陈旧实体覆盖用户改动；且去重后逐名更新减少重复往返。
                    for (String name : names) {
                        String intro = intros.get(name);
                        if (intro != null && !intro.isBlank()) {
                            itemMapper.update(null, new LambdaUpdateWrapper<ItineraryItem>()
                                    .eq(ItineraryItem::getItineraryId, itineraryId)
                                    .eq(ItineraryItem::getPoiName, name)
                                    .set(ItineraryItem::getIntro, intro));
                        }
                    }
                }
            }
        } catch (Exception e) {
            log.warn("poi intros failed for {}: {}", itineraryId, e.getMessage());
            // 降级通知：景点介绍失败同样只影响富化
            eventPublisher.degraded(itineraryId, "poi_intros", e.getMessage(), "跳过景点介绍");
        }

        // 备选池（发现更多）介绍富化：模型单次生成的 60-100 字 intro 遵循度不足，
        // 复用 poi-intros 链路分批补写 200-300 字详细介绍后写回 suggestionsJson。
        // 富化失败只影响备选池介绍文案，不影响主流程。
        try {
            enrichSuggestionIntros(main, request, itineraryId);
        } catch (Exception e) {
            log.warn("suggestion intros failed for {}: {}", itineraryId, e.getMessage());
        }
        evictDetailCache(cacheManager, main.getUserId(), itineraryId);
    }

    /** 读取行程级 suggestionsJson，对缺介绍的点位分批调 poi-intros 补长介绍后单列写回。 */
    private void enrichSuggestionIntros(ItineraryMain main, GenerateRequest request, Long itineraryId) {
        // 富化与主流程异步：重新读一行拿最新 suggestionsJson（避免用 finish 时的陈旧快照）
        ItineraryMain fresh = mainMapper.selectById(itineraryId);
        if (fresh == null) {
            return;
        }
        String json = fresh.getSuggestionsJson();
        if (json == null || json.isBlank()) {
            return;
        }
        List<Map<String, Object>> rows;
        try {
            rows = objectMapper.readValue(json,
                    new tools.jackson.core.type.TypeReference<List<Map<String, Object>>>() {
                    });
        } catch (Exception parseEx) {
            log.warn("suggestions json parse failed for {}: {}", itineraryId, parseEx.getMessage());
            return;
        }
        // 缺介绍的名称按出现顺序分批（poi-intros 按名称数给 max_tokens，批太大易截断）。
        // intro 短于 50 字视为"无有效介绍"（模型单句亮点遵循不了 60-100 字契约），一并富化。
        final int batchSize = 8;
        List<String> pending = rows.stream()
                .filter(r -> {
                    Object intro = r.get("intro");
                    return intro == null || String.valueOf(intro).isBlank()
                            || String.valueOf(intro).length() < 50;
                })
                .map(r -> String.valueOf(r.get("name")))
                .filter(n -> n != null && !n.isBlank() && !"null".equals(n))
                .distinct()
                .toList();
        Map<String, String> intros = new java.util.HashMap<>();
        for (int i = 0; i < pending.size(); i += batchSize) {
            List<String> chunk = pending.subList(i, Math.min(i + batchSize, pending.size()));
            try {
                AgentPoiIntrosRequest introRequest = new AgentPoiIntrosRequest();
                introRequest.setCity(main.getCity());
                introRequest.setNames(chunk);
                introRequest.setIntent(ItineraryAsyncPlanner.resolveIntent(request));
                AgentPoiIntrosResponse resp = agentService.poiIntros(introRequest);
                if (resp.getIntros() != null) {
                    intros.putAll(resp.getIntros());
                }
            } catch (Exception e) {
                log.warn("suggestion intros batch failed for {}: {}", itineraryId, e.getMessage());
            }
        }
        if (intros.isEmpty()) {
            return;
        }
        boolean changed = false;
        for (Map<String, Object> row : rows) {
            Object name = row.get("name");
            if (name == null) {
                continue;
            }
            String intro = intros.get(String.valueOf(name));
            if (intro != null && !intro.isBlank()) {
                row.put("intro", intro);
                changed = true;
            }
        }
        if (changed) {
            try {
                // 单列写回：禁止整行 updateById 覆盖并发编辑
                mainMapper.update(null, new LambdaUpdateWrapper<ItineraryMain>()
                        .eq(ItineraryMain::getId, itineraryId)
                        .set(ItineraryMain::getSuggestionsJson, objectMapper.writeValueAsString(rows)));
            } catch (Exception writeEx) {
                log.warn("suggestions json write failed for {}: {}", itineraryId, writeEx.getMessage());
            }
        }
    }

    private void writeButlerNote(ItineraryMain main, GenerateRequest request, Long itineraryId,
                                 List<Map<String, Object>> plans) throws Exception {
        AgentButlerNoteRequest noteRequest = new AgentButlerNoteRequest();
        noteRequest.setCity(main.getCity());
        noteRequest.setDays(main.getDays());
        noteRequest.setPersons(main.getPersons() == null ? 1 : main.getPersons());
        noteRequest.setPreferences(main.getPreferences() == null ? "" : main.getPreferences());
        noteRequest.setHotelTier(main.getHotelTier() == null ? "" : main.getHotelTier());
        noteRequest.setRegionHint(request.getRegionHint() == null ? "" : request.getRegionHint());
        // Object 字段保持 wire 值与改造前一致：非空为 BigDecimal（JSON 数字），空为 ""
        noteRequest.setBudget(main.getBudget() == null ? "" : main.getBudget());
        noteRequest.setRequirements(request.getRequirements() == null ? "" : request.getRequirements());
        noteRequest.setIntent(ItineraryAsyncPlanner.resolveIntent(request));
        noteRequest.setPlans(plans);
        AgentButlerNoteResponse noteResponse = agentService.butlerNote(noteRequest);
        String note = noteResponse.getNote() == null ? "" : noteResponse.getNote();
        if (!note.isBlank()) {
            // 讲解生成可耗时很久，期间用户可能并发修改同一行程的其它列：
            // 只按 id 精确回写 plan_note 单列，禁止用陈旧实体整行回写，避免丢更新竞态。
            mainMapper.update(null, new LambdaUpdateWrapper<ItineraryMain>()
                    .eq(ItineraryMain::getId, itineraryId)
                    .set(ItineraryMain::getPlanNote, note));
            // 写回成功后通知：preview 截前 60 字，事件体不携带长文本
            eventPublisher.butlerNote(itineraryId, note.length(),
                    note.substring(0, Math.min(60, note.length())));
        }
    }

    /** 落库行程级备选池（发现更多）；失败只记日志，不影响行程主流程。 */
    public void persistSuggestions(Long itineraryId, List<AgentGenerateResponse.Suggestion> suggestions) {
        if (suggestions == null || suggestions.isEmpty()) {
            return;
        }
        try {
            // 单列更新：禁止整行 updateById，避免覆盖用户/富化流程写入的其它字段。
            mainMapper.update(null, new LambdaUpdateWrapper<ItineraryMain>()
                    .eq(ItineraryMain::getId, itineraryId)
                    .set(ItineraryMain::getSuggestionsJson, objectMapper.writeValueAsString(suggestions)));
        } catch (Exception e) {
            log.warn("persist suggestions failed for {}: {}", itineraryId, e.getMessage());
        }
    }

    /**
     * 按 (userId, id) 精确失效详情缓存。key 格式必须与 ItineraryQueryService
     * 的 @Cacheable key "#userId + ':' + #id" 一致；替代原先对整个缓存的全量 clear，
     * 避免一次生成把所有用户的详情缓存全部击穿（J2）。
     */
    static void evictDetailCache(CacheManager cacheManager, Long userId, Long itineraryId) {
        var cache = cacheManager.getCache("itinerary:detail");
        if (cache != null) {
            cache.evict(userId + ":" + itineraryId);
        }
    }
}
