package com.travel.backend.common;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class SimpleCircuitBreakerTest {

    private SimpleCircuitBreaker breaker;

    @BeforeEach
    void setUp() {
        breaker = new SimpleCircuitBreaker(3, 1);
    }

    @Test
    void opensAfterConsecutiveFailures() {
        assertTrue(breaker.tryAcquire());
        breaker.onFailure();
        breaker.onFailure();
        breaker.onFailure();
        assertEquals(SimpleCircuitBreaker.State.OPEN, breaker.currentState());
        assertFalse(breaker.tryAcquire());
    }

    @Test
    void successResetsFailures() {
        breaker.onFailure();
        breaker.onFailure();
        breaker.onSuccess();
        breaker.onFailure();
        breaker.onFailure();
        assertTrue(breaker.tryAcquire());
        assertEquals(SimpleCircuitBreaker.State.CLOSED, breaker.currentState());
    }

    @Test
    void halfOpenAllowsSingleProbe() throws Exception {
        breaker.onFailure();
        breaker.onFailure();
        breaker.onFailure();
        assertEquals(SimpleCircuitBreaker.State.OPEN, breaker.currentState());
        Thread.sleep(1100);
        assertEquals(SimpleCircuitBreaker.State.HALF_OPEN, breaker.currentState());
        assertTrue(breaker.tryAcquire());
        assertFalse(breaker.tryAcquire());
        breaker.onSuccess();
        assertEquals(SimpleCircuitBreaker.State.CLOSED, breaker.currentState());
    }

    @Test
    void executeRetriesTransientWhenEnabled() {
        AtomicInteger calls = new AtomicInteger();
        String result = breaker.execute("t", () -> {
            if (calls.incrementAndGet() == 1) {
                throw new BizException(502, "temp");
            }
            return "ok";
        }, 2, true);
        assertEquals("ok", result);
        assertEquals(2, calls.get());
        assertEquals(SimpleCircuitBreaker.State.CLOSED, breaker.currentState());
    }

    @Test
    void executeDoesNotRetryWhenDisabled() {
        AtomicInteger calls = new AtomicInteger();
        assertThrows(BizException.class, () -> breaker.execute("t", () -> {
            calls.incrementAndGet();
            throw new BizException(502, "fail");
        }, 1, false));
        assertEquals(1, calls.get());
    }

    @Test
    void executeRejectsWhenOpen() {
        breaker.onFailure();
        breaker.onFailure();
        breaker.onFailure();
        BizException ex = assertThrows(BizException.class,
                () -> breaker.execute("t", () -> "x", 1, false));
        assertTrue(ex.getMessage().contains("熔断"));
    }

    @Test
    void openDurationConfigurable() {
        SimpleCircuitBreaker shortOpen = new SimpleCircuitBreaker(1, 1);
        shortOpen.onFailure();
        assertEquals(SimpleCircuitBreaker.State.OPEN, shortOpen.currentState());
    }
}
