package com.travel.backend.config;

import tools.jackson.databind.DefaultTyping;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.jsontype.BasicPolymorphicTypeValidator;
import com.fasterxml.jackson.annotation.JsonAutoDetect;
import com.fasterxml.jackson.annotation.PropertyAccessor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.serializer.GenericJacksonJsonRedisSerializer;
import org.springframework.data.redis.serializer.StringRedisSerializer;

/**
 * Redis 模板配置。
 *
 * <p>生成事件订阅容器（gen:events:*）不在此注册：{@code RedisMessageListenerContainer}
 * 是 SmartLifecycle，注册为 Bean 会在上下文刷新期自动启动，Redis 不可达时会拖死整个应用；
 * 改由 {@link com.travel.backend.common.ItineraryEventChannelManager} 自管生命周期
 * （手动启停 + 失败重试 + 失联断流），保证「无 Redis 只失去 SSE、轮询降级照常可用」。</p>
 */
@Configuration
public class RedisConfig {

    @Bean
    public RedisTemplate<String, Object> redisTemplate(RedisConnectionFactory connectionFactory) {
        RedisTemplate<String, Object> template = new RedisTemplate<>();
        template.setConnectionFactory(connectionFactory);

        ObjectMapper mapper = JsonMapper.builder()
                .changeDefaultVisibility(checker ->
                        checker.withVisibility(PropertyAccessor.ALL, JsonAutoDetect.Visibility.ANY))
                .activateDefaultTyping(redisTypeValidator(), DefaultTyping.NON_FINAL)
                .build();
        GenericJacksonJsonRedisSerializer valueSerializer = new GenericJacksonJsonRedisSerializer(mapper);
        StringRedisSerializer keySerializer = new StringRedisSerializer();

        template.setKeySerializer(keySerializer);
        template.setHashKeySerializer(keySerializer);
        template.setValueSerializer(valueSerializer);
        template.setHashValueSerializer(valueSerializer);
        template.afterPropertiesSet();
        return template;
    }

    /** 反序列化白名单：只允许应用域与 JDK 常用类型（替代 Jackson 2 的 laissez-faire 校验器）。 */
    private static BasicPolymorphicTypeValidator redisTypeValidator() {
        return BasicPolymorphicTypeValidator.builder()
                .allowIfSubType("com.travel.backend.")
                .allowIfSubType("java.util.")
                .allowIfSubType("java.time.")
                .allowIfSubType("java.math.")
                .build();
    }
}
