package com.travel.backend.serviceImpl;

import com.travel.backend.common.BizException;
import com.travel.backend.common.DistributedStateService;
import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.entity.ItineraryDay;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 幂等门测试：409 两分支（actionId 不一致 / fingerprint 不一致）、
 * 指纹稳定性（同参数同指纹、变参变指纹）、日锁 mark/unmark 语义。
 * 此前 Planner 与 PersistenceService 各持一份 verifyAction 实现，本测试锁定统一后的唯一语义。
 */
class ItineraryGenerationGateTest {

    private final DistributedStateService state = new DistributedStateService(null, false);
    private final ItineraryGenerationGate gate = new ItineraryGenerationGate(state);

    private ItineraryDay day(String actionId, String fingerprint) {
        ItineraryDay day = new ItineraryDay();
        day.setId(50L);
        day.setItineraryId(9L);
        day.setDayNo(1);
        day.setGenerationActionId(actionId);
        day.setGenerationFingerprint(fingerprint);
        return day;
    }

    private GenerateRequest request(String city, int days) {
        GenerateRequest request = new GenerateRequest();
        request.setCity(city);
        request.setDays(days);
        request.setPersons(2);
        request.setStayNights(days - 1);
        return request;
    }

    /** 409 分支一：该天已登记不同 actionId → 视为已有不同生成动作，拒绝。 */
    @Test
    void verifyActionRejectsDifferentActionIdWith409() {
        BizException ex = assertThrows(BizException.class,
                () -> gate.verifyAction(day("day-9-1", "fp"), "day-9-2", "fp"));
        assertEquals(409, ex.getCode());
    }

    /** 409 分支二：同 actionId 但指纹不同 → 生成参数已变化，拒绝。 */
    @Test
    void verifyActionRejectsDifferentFingerprintWith409() {
        BizException ex = assertThrows(BizException.class,
                () -> gate.verifyAction(day("day-9-1", "fp-old"), "day-9-1", "fp-new"));
        assertEquals(409, ex.getCode());
    }

    /** 首次生成（无历史动作/指纹）与完全一致的续跑均放行。 */
    @Test
    void verifyActionPassesForFreshDayAndMatchingAction() {
        assertDoesNotThrow(() -> gate.verifyAction(day(null, null), "day-9-1", "fp"));
        assertDoesNotThrow(() -> gate.verifyAction(day("day-9-1", "fp"), "day-9-1", "fp"));
    }

    /** 指纹稳定性：同参数重复计算指纹一致（重试/续跑可幂等续写）。 */
    @Test
    void requestFingerprintIsStableForSameParams() {
        assertEquals(gate.requestFingerprint(request("杭州", 3)),
                gate.requestFingerprint(request("杭州", 3)));
    }

    /** 指纹敏感性：任一生成参数变化 → 指纹变化（配合 409 阻止新参数覆写旧结果）。 */
    @Test
    void requestFingerprintChangesWhenParamsChange() {
        String base = gate.requestFingerprint(request("杭州", 3));
        assertNotEquals(base, gate.requestFingerprint(request("苏州", 3)));
        assertNotEquals(base, gate.requestFingerprint(request("杭州", 2)));
    }

    /** 日锁语义：未占用可占、占用期内互斥、释放后可重入。 */
    @Test
    void dayLockIsMutuallyExclusiveUntilUnmarked() {
        assertTrue(gate.tryMark(9L, 1));
        assertTrue(gate.isMarked(9L, 1));
        assertFalse(gate.tryMark(9L, 1), "持锁期间同天不可再占用");
        gate.unmark(9L, 1);
        assertFalse(gate.isMarked(9L, 1));
        assertTrue(gate.tryMark(9L, 1));
    }

    /** 日锁按天隔离：同行程不同天互不影响。 */
    @Test
    void dayLocksAreIsolatedPerDay() {
        assertTrue(gate.tryMark(9L, 1));
        assertFalse(gate.isMarked(9L, 2));
        assertTrue(gate.tryMark(9L, 2));
        assertEquals("gen:day:9:1", ItineraryGenerationGate.dayLockKey(9L, 1));
    }
}
