package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
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

    private final AgentServiceImpl agentService;
    private final ItineraryDayMapper dayMapper;
    private final ItineraryItemMapper itemMapper;
    private final ItineraryMainMapper mainMapper;
    private final CacheManager cacheManager;
    private final ItineraryEventPublisher eventPublisher;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public ItineraryEnricher(AgentServiceImpl agentService, ItineraryDayMapper dayMapper,
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

        // 景点详细介绍：批量生成后按去重名称逐条单列回填
        try {
            List<String> names = itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                            .eq(ItineraryItem::getItineraryId, itineraryId)).stream()
                    .map(ItineraryItem::getPoiName).filter(n -> n != null && !n.isBlank()).distinct().toList();
            if (!names.isEmpty()) {
                AgentPoiIntrosRequest introRequest = new AgentPoiIntrosRequest();
                introRequest.setCity(main.getCity());
                introRequest.setNames(names);
                // M3-③：poi-intros 透传意图，与 butlerNote/generate 的 intent 兜底口径一致
                introRequest.setIntent(ItineraryAsyncPlanner.resolveIntent(request));
                AgentPoiIntrosResponse introResponse = agentService.poiIntros(introRequest);
                Map<String, String> intros = introResponse.getIntros();
                if (intros != null && !intros.isEmpty()) {
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
        evictDetailCache(cacheManager, main.getUserId(), itineraryId);
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
