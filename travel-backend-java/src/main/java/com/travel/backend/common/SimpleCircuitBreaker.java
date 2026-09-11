package com.travel.backend.common;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Supplier;

/**
 * 轻量熔断器（滑动失败计数 + 半开试探），用于 Agent 出站调用。
 * <p>
 * 不引入 Resilience4j 以控制依赖面；语义对齐经典三态：
 * CLOSED → 连续失败达阈值 → OPEN（拒绝新请求）→ 超时后 HALF_OPEN（放行一次试探）
 * → 成功 CLOSED / 失败重回 OPEN。
 * <p>
 * 仅包一层「是否允许发起调用」；重试策略见 {@link #execute}。
 */
@Component
public class SimpleCircuitBreaker {

    private static final Logger log = LoggerFactory.getLogger(SimpleCircuitBreaker.class);

    public enum State { CLOSED, OPEN, HALF_OPEN }

    private final int failureThreshold;
    private final Duration openDuration;
    private final AtomicReference<State> state = new AtomicReference<>(State.CLOSED);
    private final AtomicInteger consecutiveFailures = new AtomicInteger();
    private final AtomicLong openedAtMillis = new AtomicLong();
    private final AtomicInteger halfOpenProbe = new AtomicInteger(0);

    public SimpleCircuitBreaker(
            @Value("${app.agent.circuit.failure-threshold:5}") int failureThreshold,
            @Value("${app.agent.circuit.open-seconds:30}") long openSeconds) {
        this.failureThreshold = Math.max(1, failureThreshold);
        this.openDuration = Duration.ofSeconds(Math.max(1, openSeconds));
    }

    public State currentState() {
        maybeHalfOpen();
        return state.get();
    }

    /** 管理端可观测：当前状态与配置。 */
    public java.util.Map<String, Object> snapshot() {
        return java.util.Map.of(
                "state", currentState().name(),
                "failureThreshold", failureThreshold,
                "openSeconds", openDuration.toSeconds(),
                "consecutiveFailures", consecutiveFailures.get()
        );
    }

    /** 是否允许本次请求发出。 */
    public boolean tryAcquire() {
        maybeHalfOpen();
        State s = state.get();
        if (s == State.CLOSED) {
            return true;
        }
        if (s == State.OPEN) {
            return false;
        }
        // HALF_OPEN：只放行一个试探
        return halfOpenProbe.compareAndSet(0, 1);
    }

    public void onSuccess() {
        consecutiveFailures.set(0);
        halfOpenProbe.set(0);
        if (state.get() != State.CLOSED) {
            log.info("circuit breaker closed after success");
        }
        state.set(State.CLOSED);
    }

    public void onFailure() {
        halfOpenProbe.set(0);
        if (state.get() == State.HALF_OPEN) {
            open();
            return;
        }
        int n = consecutiveFailures.incrementAndGet();
        if (n >= failureThreshold) {
            open();
        }
    }

    private void open() {
        openedAtMillis.set(System.currentTimeMillis());
        state.set(State.OPEN);
        consecutiveFailures.set(0);
        log.warn("circuit breaker OPEN for agent calls (threshold={}, open={}s)",
                failureThreshold, openDuration.toSeconds());
    }

    private void maybeHalfOpen() {
        if (state.get() != State.OPEN) {
            return;
        }
        long elapsed = System.currentTimeMillis() - openedAtMillis.get();
        if (elapsed >= openDuration.toMillis()) {
            if (state.compareAndSet(State.OPEN, State.HALF_OPEN)) {
                halfOpenProbe.set(0);
                log.info("circuit breaker HALF_OPEN");
            }
        }
    }

    /**
     * 带熔断与有限重试的执行器。
     *
     * @param action           业务调用
     * @param maxAttempts      总尝试次数（含首次）；1 表示不重试
     * @param retryOnTransient 是否对瞬时异常（连接失败等）重试；生成类应传 false
     */
    public <T> T execute(String name, Supplier<T> action, int maxAttempts, boolean retryOnTransient) {
        if (!tryAcquire()) {
            throw new BizException(502, "Agent 服务暂时不可用（熔断打开），请稍后重试");
        }
        int attempts = Math.max(1, maxAttempts);
        RuntimeException last = null;
        for (int i = 0; i < attempts; i++) {
            try {
                T result = action.get();
                onSuccess();
                return result;
            } catch (BizException ex) {
                // 业务 5xx：Agent 不可达/信封异常 → 算失败；4xx 不进重试
                last = ex;
                if (ex.getCode() == 429 || ex.getCode() == 400 || ex.getCode() == 403) {
                    onFailure();
                    throw ex;
                }
                if (!retryOnTransient || i + 1 >= attempts) {
                    onFailure();
                    throw ex;
                }
                sleepQuietly(200L * (i + 1));
            } catch (RuntimeException ex) {
                last = ex;
                if (!retryOnTransient || i + 1 >= attempts) {
                    onFailure();
                    throw ex;
                }
                sleepQuietly(200L * (i + 1));
            }
        }
        onFailure();
        if (last != null) {
            throw last;
        }
        throw new BizException(502, "Agent 服务调用失败");
    }

    private static void sleepQuietly(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
        }
    }
}
