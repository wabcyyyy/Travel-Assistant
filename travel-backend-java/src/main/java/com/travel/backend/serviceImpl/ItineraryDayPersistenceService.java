package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.travel.backend.common.BizException;
import com.travel.backend.dto.AgentGenerateResponse;
import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.mapper.ItineraryDayMapper;
import com.travel.backend.mapper.ItineraryItemMapper;
import com.travel.backend.mapper.ItineraryMainMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * 每日结果与行程收尾的事务写入、幂等保护。
 *
 * <p>远程 Agent 调用发生在事务外；只有完整结果准备好后才在一个短事务中
 * 清理旧草稿、写入全部项目并标记 SUCCEEDED，避免响应丢失或半写入造成重复。</p>
 *
 * <p>预算重算已移出 persist 事务（J5）：recalculate 是全行程 delete+insert，
 * 放在单日写库事务里会放大锁持有时间，改由编排层在事务提交后异步执行。
 * 行程级终态（COMPLETED/PARTIAL/FAILED）写回也收拢于此，编排层只做流程。</p>
 */
@Service
public class ItineraryDayPersistenceService {

    /** 旧实现续跑标记文案；状态机改用 gen_resumed 承载，仅保留对存量 planNote 的一次性清洗。 */
    private static final String LEGACY_RESUME_MARKER = "[已自动续跑一次]";

    private final ItineraryDayMapper dayMapper;
    private final ItineraryItemMapper itemMapper;
    private final ItineraryMainMapper mainMapper;
    private final ItineraryGenerationGate gate;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public ItineraryDayPersistenceService(ItineraryDayMapper dayMapper,
                                          ItineraryItemMapper itemMapper,
                                          ItineraryMainMapper mainMapper,
                                          ItineraryGenerationGate gate) {
        this.dayMapper = dayMapper;
        this.itemMapper = itemMapper;
        this.mainMapper = mainMapper;
        this.gate = gate;
    }

    @Transactional
    public void persist(Long itineraryId, GenerateRequest request, int dayNo,
                        AgentGenerateResponse.DailyPlan plan,
                        String actionId, String fingerprint) {
        ItineraryDay day = findDay(itineraryId, dayNo);
        if (day == null) {
            throw new BizException(500, "行程日不存在");
        }
        gate.verifyAction(day, actionId, fingerprint);
        if ("SUCCEEDED".equals(day.getGenerationStatus())) {
            return;
        }

        day.setGenerationActionId(actionId);
        day.setGenerationFingerprint(fingerprint);
        day.setGenerationStatus("RUNNING");
        day.setGenerationError(null);
        if (plan.getNote() != null) {
            day.setNote(plan.getNote());
        }
        Map<String, Object> metadata = new LinkedHashMap<>();
        if (plan.getTheme() != null) metadata.put("theme", plan.getTheme());
        if (plan.getMiniRoute() != null && !plan.getMiniRoute().isEmpty()) metadata.put("miniRoute", plan.getMiniRoute());
        if (plan.getBackupPlan() != null && !plan.getBackupPlan().isEmpty()) metadata.put("backupPlan", plan.getBackupPlan());
        if (plan.getPhotoSpots() != null && !plan.getPhotoSpots().isEmpty()) metadata.put("photoSpots", plan.getPhotoSpots());
        if (plan.getPracticalNotes() != null && !plan.getPracticalNotes().isEmpty()) metadata.put("practicalNotes", plan.getPracticalNotes());
        // M3-③：整趟主题的备选日方案（仅 day_no=1 响应携带）随 metadataJson 落库，前端据此展示"换一种玩法"
        if (plan.getDayOptions() != null && !plan.getDayOptions().isEmpty()) metadata.put("dayOptions", plan.getDayOptions());
        try {
            day.setMetadataJson(metadata.isEmpty() ? null : objectMapper.writeValueAsString(metadata));
        } catch (Exception ignored) {
            day.setMetadataJson(null);
        }
        dayMapper.updateById(day);

        // 失败重试或恢复时清理可能遗留的半成品；本方法处于事务中，失败会整体回滚。
        itemMapper.delete(new LambdaQueryWrapper<ItineraryItem>().eq(ItineraryItem::getDayId, day.getId()));
        int sortNo = 0;
        int stayNights = request.getStayNights() == null
                ? Math.max(request.getDays() - 1, 0) : request.getStayNights();
        if (plan.getItems() != null) {
            for (AgentGenerateResponse.Item item : plan.getItems()) {
                if ("hotel".equals(item.getItemType()) && dayNo > stayNights) {
                    continue;
                }
                ItineraryItem entity = new ItineraryItem();
                entity.setDayId(day.getId());
                entity.setItineraryId(itineraryId);
                entity.setItemType(item.getItemType());
                entity.setPoiName(item.getPoiName());
                entity.setPoiId(item.getPoiId());
                entity.setAddress(item.getAddress());
                entity.setLatitude(item.getLatitude());
                entity.setLongitude(item.getLongitude());
                entity.setStartTime(parseTimeSafe(item.getStartTime()));
                entity.setEndTime(parseTimeSafe(item.getEndTime()));
                entity.setDurationMin(item.getDurationMin());
                entity.setCost(item.getCost());
                entity.setTag(item.getTag());
                entity.setRemark(item.getRemark());
                // 叙事理由（M3-③）：契约字段 why_this，PDF/VO 直接读本列
                entity.setWhyNote(item.getWhyThis());
                entity.setOpenTime(item.getOpenTime());
                entity.setImageUrl(item.getImage());
                entity.setSource(item.getSource());
                entity.setSourceUpdatedAt(parseDateTimeSafe(item.getSourceUpdatedAt()));
                entity.setVerificationStatus(defaultString(item.getVerificationStatus(), "unverified"));
                entity.setValueKind(defaultString(item.getValueKind(), "generated"));
                entity.setFreshnessStatus(defaultString(item.getFreshnessStatus(), "unknown"));
                entity.setReviewRequirement(defaultString(item.getReviewRequirement(), "before_departure"));
                if (item.getFactEvidence() != null && !item.getFactEvidence().isEmpty()) {
                    try {
                        entity.setFactEvidenceJson(objectMapper.writeValueAsString(item.getFactEvidence()));
                    } catch (Exception ignored) {
                        entity.setFactEvidenceJson(null);
                    }
                }
                entity.setSortNo(sortNo++);
                itemMapper.insert(entity);
            }
        }
        day.setGenerationStatus("SUCCEEDED");
        day.setGenerationError(null);
        dayMapper.updateById(day);
    }

    /** 按行程+天号查日记录；编排层生成前后各查一次（生成前定位、落库后读取最终项）。 */
    public ItineraryDay findDay(Long itineraryId, int dayNo) {
        return dayMapper.selectOne(new LambdaQueryWrapper<ItineraryDay>()
                .eq(ItineraryDay::getItineraryId, itineraryId)
                .eq(ItineraryDay::getDayNo, dayNo));
    }

    /** 登记某天已落库的点位名到 usedNames，供跨天 used_names 去重传给 Python。 */
    public void appendExistingItems(ItineraryDay day, List<String> usedNames) {
        itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                        .eq(ItineraryItem::getDayId, day.getId()).orderByAsc(ItineraryItem::getSortNo))
                .stream().map(ItineraryItem::getPoiName).filter(name -> name != null && !name.isBlank())
                .forEach(usedNames::add);
    }

    /** 取该天已落库的酒店名（多日共享同一酒店时作为 chosen_hotel 传给后续天）。 */
    public String existingHotel(ItineraryDay day) {
        return itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                        .eq(ItineraryItem::getDayId, day.getId()))
                .stream().filter(item -> "hotel".equals(item.getItemType()))
                .map(ItineraryItem::getPoiName).findFirst().orElse(null);
    }

    @Transactional
    public void markRunning(ItineraryDay day, String actionId, String fingerprint) {
        gate.verifyAction(day, actionId, fingerprint);
        day.setGenerationActionId(actionId);
        day.setGenerationFingerprint(fingerprint);
        day.setGenerationStatus("RUNNING");
        day.setGenerationError(null);
        dayMapper.updateById(day);
    }

    @Transactional
    public void markFailed(ItineraryDay day, String actionId, String fingerprint, String error) {
        gate.verifyAction(day, actionId, fingerprint);
        day.setGenerationActionId(actionId);
        day.setGenerationFingerprint(fingerprint);
        day.setGenerationStatus("FAILED");
        day.setGenerationError(error == null ? "每日生成失败" : error.substring(0, Math.min(error.length(), 500)));
        dayMapper.updateById(day);
    }

    // ================= 行程级终态写回（由编排层收尾时调用，单列更新禁整行回写） =================

    /**
     * 行程收尾终态（J3 状态机）：按天状态汇总 COMPLETED/PARTIAL 写入 gen_state；
     * status 列维持 2 不变（用户可见语义不变）；gen_resumed 清零表示本次（含续跑）成功收尾。
     */
    @Transactional
    public void completeTrip(ItineraryMain main, boolean allSucceeded) {
        String planNote = main.getPlanNote();
        // 存量清洗：旧实现把续跑标记写进 planNote，成功后清除避免残留"AI 管家说"卡片（新实现不再写入）
        if (planNote != null && planNote.contains(LEGACY_RESUME_MARKER)) {
            planNote = planNote.replace(LEGACY_RESUME_MARKER, "").trim();
        }
        mainMapper.update(null, new LambdaUpdateWrapper<ItineraryMain>()
                .eq(ItineraryMain::getId, main.getId())
                .set(ItineraryMain::getStatus, 2)
                .set(ItineraryMain::getGenState, allSucceeded ? "COMPLETED" : "PARTIAL")
                .set(ItineraryMain::getGenFinishedAt, LocalDateTime.now())
                .set(ItineraryMain::getGenResumed, false)
                .set(ItineraryMain::getTitle, main.getCity() + main.getDays() + "日游")
                .set(ItineraryMain::getPlanNote, planNote == null || planNote.isBlank() ? null : planNote));
    }

    /**
     * 行程失败终态：status 维持 3 语义不变，gen_state=FAILED + gen_finished_at 落位。
     * 不清除 gen_resumed——续跑再次失败时恢复任务依据它阻止二次续跑（防死循环）。
     */
    @Transactional
    public void failTrip(Long itineraryId, String message) {
        String planNote = message == null || message.isBlank() ? null : "生成失败：" + message;
        mainMapper.update(null, new LambdaUpdateWrapper<ItineraryMain>()
                .eq(ItineraryMain::getId, itineraryId)
                .set(ItineraryMain::getStatus, 3)
                .set(ItineraryMain::getGenState, "FAILED")
                .set(ItineraryMain::getGenFinishedAt, LocalDateTime.now())
                .set(ItineraryMain::getPlanNote, planNote));
    }

    /** 全部天 SUCCEEDED 才算完成；存在未成功天（如日锁跳过）→ false，编排层据此置 PARTIAL。 */
    public boolean allDaysSucceeded(Long itineraryId) {
        return dayMapper.selectList(new LambdaQueryWrapper<ItineraryDay>()
                        .eq(ItineraryDay::getItineraryId, itineraryId)).stream()
                .allMatch(day -> "SUCCEEDED".equals(day.getGenerationStatus()));
    }

    /** 事件协议 complete.degradedDays：未 SUCCEEDED 的 dayNo 升序列表（全成功时为空列表）。 */
    public List<Integer> unfinishedDayNos(Long itineraryId) {
        return dayMapper.selectList(new LambdaQueryWrapper<ItineraryDay>()
                        .eq(ItineraryDay::getItineraryId, itineraryId)).stream()
                .filter(day -> !"SUCCEEDED".equals(day.getGenerationStatus()))
                .map(ItineraryDay::getDayNo)
                .sorted()
                .toList();
    }

    private LocalTime parseTimeSafe(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String normalized = value.trim();
        if (normalized.startsWith("24:")) {
            normalized = "00:" + normalized.substring(3);
        }
        try {
            return LocalTime.parse(normalized);
        } catch (Exception ignored) {
            return null;
        }
    }

    private java.time.LocalDateTime parseDateTimeSafe(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return java.time.OffsetDateTime.parse(value).toLocalDateTime();
        } catch (Exception ignored) {
            try {
                return java.time.LocalDateTime.parse(value);
            } catch (Exception ignoredAgain) {
                return null;
            }
        }
    }

    private String defaultString(String value, String fallback) {
        return value == null || value.isBlank() ? fallback : value;
    }
}
