package com.travel.backend.service.impl;

import com.travel.backend.common.BizException;
import com.travel.backend.common.DistributedStateService;
import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.entity.ItineraryDay;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.List;

/**
 * 幂等门：收拢逐日生成的三层判重原语。
 *
 * <p>此前 Planner 与 ItineraryDayPersistenceService 各自持有一份 verifyAction、
 * 请求指纹实现，语义存在漂移风险；日锁 key 的拼装也散落在编排层。统一收口到本类后，
 * 两处调用同一实现，保证 409 判定与指纹算法永远一致（409 语义：
 * actionId 不一致 → 该日期已有不同的生成动作；fingerprint 不一致 → 生成参数已变化）。</p>
 */
@Service
public class ItineraryGenerationGate {

    /** 日生成互斥：Redis SETNX（跨实例）；单机 Redis 故障时降级进程内。TTL 大于单日最坏生成耗时。 */
    private static final Duration DAY_LOCK_TTL = Duration.ofMinutes(5);

    private final DistributedStateService state;

    public ItineraryGenerationGate(DistributedStateService state) {
        this.state = state;
    }

    /** 日锁 key：按 (itineraryId, dayNo) 粒度互斥，避免两个任务并发生成同一天。 */
    public static String dayLockKey(Long itineraryId, int dayNo) {
        return "gen:day:" + itineraryId + ":" + dayNo;
    }

    /** 尝试占用某天的生成日锁；已被占用（其它实例/任务在生成同一天）返回 false。 */
    public boolean tryMark(Long itineraryId, int dayNo) {
        return state.tryMark(dayLockKey(itineraryId, dayNo), DAY_LOCK_TTL);
    }

    public void unmark(Long itineraryId, int dayNo) {
        state.unmark(dayLockKey(itineraryId, dayNo));
    }

    /** 测试/运维：查询某天是否仍持锁。 */
    public boolean isMarked(Long itineraryId, int dayNo) {
        return state.isMarked(dayLockKey(itineraryId, dayNo));
    }

    /**
     * 校验该天是否可被本动作写入：不匹配即抛 409，防止旧任务覆盖新任务的生成结果。
     * 唯一实现，Planner 与 PersistenceService 均改调这里。
     */
    public void verifyAction(ItineraryDay day, String actionId, String fingerprint) {
        if (day.getGenerationActionId() != null && !actionId.equals(day.getGenerationActionId())) {
            throw new BizException(409, "该日期已有不同的生成动作，请使用最新任务");
        }
        if (day.getGenerationFingerprint() != null && !fingerprint.equals(day.getGenerationFingerprint())) {
            throw new BizException(409, "同一日期生成参数已发生变化，请重新创建行程");
        }
    }

    /**
     * 生成参数指纹（SHA-256）：同参数重试/续跑指纹一致可幂等续写；参数变化则指纹变化，
     * 配合 verifyAction 阻止用新参数覆写旧参数已生成的天。
     */
    public String requestFingerprint(GenerateRequest request) {
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

    private static String safe(String value) {
        return value == null ? "" : value;
    }
}
