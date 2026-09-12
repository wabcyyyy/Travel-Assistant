package com.travel.backend.common;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.listener.PatternTopic;
import org.springframework.data.redis.listener.RedisMessageListenerContainer;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;

/**
 * 事件订阅链路的唯一管理者（M2-③ AD2 + M2-④ 真机演练韧性修正）：
 *
 * <p><b>为什么容器不由 Spring 管理：</b>{@link RedisMessageListenerContainer} 是
 * SmartLifecycle，注册为 Bean 会在上下文刷新期自动 start；Redis 不可达时启动即抛
 * RedisListenerExecutionFailedException，会拖死整个应用——而事件只是尽力而为通知
 * （DB 才是真相），无 Redis 只应失去 SSE、保留轮询降级（真机演练实测踩坑）。
 * 因此这里自持容器实例、手动控制启停，失败只记日志并周期重试。</p>
 *
 * <ul>
 *   <li>就绪后尝试启动订阅；失败不阻断启动；</li>
 *   <li>容器停止（启动失败残留）→ 周期重试，Redis 恢复后 SSE 自动续上；</li>
 *   <li>订阅期间 Redis 失联 → 主动断开全部 SSE 连接：事件源唯一，保持连接只会造成
 *       「连接健康但事件永不再来」的假活；客户端重连失败 3 次即降级回轮询。</li>
 * </ul>
 */
@Component
public class ItineraryEventChannelManager {

    private static final Logger log = LoggerFactory.getLogger(ItineraryEventChannelManager.class);

    private final ItinerarySseGateway gateway;
    private final RedisConnectionFactory connectionFactory;
    private final RedisMessageListenerContainer container;
    /**
     * 订阅是否真实存活。不能信 container.isRunning()：start() 失败（Redis 不可达）
     * 时生命周期标志已先行置位，isRunning 恒为 true，守卫会因此永不重试（真机演练踩坑）。
     */
    private volatile boolean subscriptionActive = false;

    /** @Autowired 消歧：类有两个构造器（测试用包级注入容器），Spring 需显式指定装配入口。 */
    @org.springframework.beans.factory.annotation.Autowired
    public ItineraryEventChannelManager(ItinerarySseGateway gateway, RedisConnectionFactory connectionFactory) {
        this(gateway, connectionFactory, new RedisMessageListenerContainer());
    }

    /** 包内可见：测试注入 mock 容器，验证启停/重建决策而不依赖真实 Redis。 */
    ItineraryEventChannelManager(ItinerarySseGateway gateway, RedisConnectionFactory connectionFactory,
                                 RedisMessageListenerContainer container) {
        this.gateway = gateway;
        this.connectionFactory = connectionFactory;
        this.container = container;
        this.container.setConnectionFactory(connectionFactory);
        this.container.addMessageListener((message, pattern) -> {
            try {
                String channel = new String(message.getChannel(), StandardCharsets.UTF_8);
                String body = new String(message.getBody(), StandardCharsets.UTF_8);
                gateway.onRedisMessage(channel, body);
            } catch (Exception e) {
                // 单条事件失败只丢一条尽力而为通知，不抛出以免中断订阅
                log.warn("handle gen event failed: {}", e.getMessage());
            }
        }, new PatternTopic(ItineraryEventPublisher.CHANNEL_PREFIX + "*"));
        try {
            this.container.afterPropertiesSet();
        } catch (Exception e) {
            log.warn("event listener container init failed: {}", e.getMessage());
        }
    }

    /** 应用就绪后尝试启动订阅；失败不阻断启动。 */
    @EventListener(ApplicationReadyEvent.class)
    public void onReady() {
        tryStart();
    }

    @Scheduled(fixedDelay = 30_000, initialDelay = 30_000)
    public void guard() {
        boolean alive = redisAlive();
        // 曾启动失败而 Redis 现已可用：重置容器（清掉半启动状态）后重建订阅
        if (alive && !subscriptionActive) {
            try {
                container.stop();
            } catch (Exception ignored) {
                // 未启动过的 stop 是 no-op；异常同样不影响随后的 start
            }
            tryStart();
        }
        // 有订阅者但 Redis 失联 → 断开全部连接，促使前端走降级；订阅存活状态不再可信
        if (gateway.hasSubscribers() && !alive) {
            log.warn("redis unreachable with active sse subscribers, closing all event streams");
            gateway.closeAll();
            subscriptionActive = false;
        }
    }

    private void tryStart() {
        try {
            if (!subscriptionActive) {
                container.start();
                subscriptionActive = true;
                log.info("itinerary event subscription started");
            }
        } catch (Exception e) {
            subscriptionActive = false;
            log.warn("itinerary event subscription start failed (will retry): {}", e.getMessage());
        }
    }

    /** 单测观察用：订阅是否处于已建立状态。 */
    boolean isSubscriptionActive() {
        return subscriptionActive;
    }

    /** ping 探活；任何异常都视为失联。 */
    private boolean redisAlive() {
        try {
            return connectionFactory.getConnection().ping() != null;
        } catch (Exception e) {
            return false;
        }
    }
}
