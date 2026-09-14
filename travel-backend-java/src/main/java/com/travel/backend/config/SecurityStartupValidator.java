package com.travel.backend.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.net.InetAddress;
import java.util.Set;

/**
 * 启动期安全配置校验：演示友好默认值在生产绑定下必须 fail-fast，
 * 避免「空 JWT 密钥 / 空内部 Token」静默放行。
 */
@Component
public class SecurityStartupValidator implements InitializingBean {

    private static final Logger log = LoggerFactory.getLogger(SecurityStartupValidator.class);
    private static final Set<String> LOOPBACK = Set.of("127.0.0.1", "localhost", "0:0:0:0:0:0:0:1", "::1");

    @Value("${server.address:127.0.0.1}")
    private String serverAddress;

    @Value("${app.jwt.secret:}")
    private String jwtSecret;

    @Value("${app.agent.internal-token:}")
    private String agentInternalToken;

    @Value("${app.agent.base-url:http://localhost:8000}")
    private String agentBaseUrl;

    @Value("${app.security.enforce-secret-check:true}")
    private boolean enforceSecretCheck;

    @Override
    public void afterPropertiesSet() {
        boolean loopbackBind = isLoopback(serverAddress);
        if (!enforceSecretCheck) {
            log.warn("app.security.enforce-secret-check=false：跳过 JWT/内部 Token 强校验（仅限本地演示）");
            if (jwtSecret == null || jwtSecret.isBlank()) {
                log.warn("JWT_SECRET 未配置，将使用进程内临时密钥，重启后全部会话失效且无法多实例共享");
            }
            return;
        }
        if (jwtSecret == null || jwtSecret.isBlank()) {
            throw new IllegalStateException(
                    "JWT_SECRET 未配置。请设置至少 32 位随机字符；本地演示可设 enforce-secret-check=false。");
        }
        if (jwtSecret.length() < 32) {
            throw new IllegalStateException("JWT_SECRET 过短（至少 32 字符）");
        }
        // 生成类接口会烧 LLM 配额：与 Python 侧策略对齐，空内部 Token 不得在非回环下运行。
        boolean agentLikelyLocal = agentBaseUrl == null
                || agentBaseUrl.contains("127.0.0.1")
                || agentBaseUrl.contains("localhost");
        if (!loopbackBind && (agentInternalToken == null || agentInternalToken.isBlank()) && !agentLikelyLocal) {
            throw new IllegalStateException(
                    "服务绑定非回环地址且 AGENT_INTERNAL_TOKEN 为空，内部 Agent 调用将无鉴权；请配置 Token。");
        }
        if ((agentInternalToken == null || agentInternalToken.isBlank()) && !loopbackBind) {
            log.warn("AGENT_INTERNAL_TOKEN 为空：仅因 Agent 地址看起来是本机而放行，生产请务必配置。");
        }
        log.info("Security startup checks passed (bind={}, agent={})", serverAddress, agentBaseUrl);
    }

    private static boolean isLoopback(String address) {
        if (address == null || address.isBlank()) {
            return true;
        }
        String host = address.trim();
        if (LOOPBACK.contains(host)) {
            return true;
        }
        try {
            return InetAddress.getByName(host).isLoopbackAddress();
        } catch (Exception ex) {
            log.warn("cannot resolve configured host, treated as non-loopback: host={}", host, ex);
            return false;
        }
    }
}
