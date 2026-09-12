package com.travel.backend.controller;

import com.fasterxml.jackson.databind.JsonNode;
import com.travel.backend.common.ItineraryEventPublisher;
import com.travel.backend.common.ItinerarySseGateway;
import com.travel.backend.common.SecurityUtils;
import com.travel.backend.service.UserService;
import com.travel.backend.serviceImpl.AgentServiceImpl;
import com.travel.backend.serviceImpl.ItineraryChatService;
import com.travel.backend.serviceImpl.ItineraryQueryService;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;

/**
 * 行程生成/对话的 SSE 实时端点（M2-③ AD2）。
 *
 * <ul>
 *   <li>{@code GET /api/itinerary/{id}/events} — 订阅生成进度事件流
 *       （day_start/day_done/degraded/error/complete/research_* 等统一信封）。</li>
 *   <li>{@code POST /api/itinerary/{id}/chat-edit/stream} — 对话编辑的流式变体：
 *       同参构造 chatTurn 请求，reply 按 ~40 字符分片推 chat_token，随后 chat_draft、chat_done。
 *       旧的阻塞端点 /chat-edit 原样保留作为降级路径。</li>
 * </ul>
 *
 * <p>两个端点都先做归属校验（非本人 404，与 /{id} 详情一致），再建立 SSE 连接。</p>
 */
@RestController
@RequestMapping("/api/itinerary")
public class ItinerarySseController {

    /** reply 分片长度：~40 字符打字机节奏，兼顾前端渲染频率与事件数。 */
    private static final int CHAT_TOKEN_CHUNK_SIZE = 40;

    private final ItineraryQueryService queryService;
    private final ItineraryChatService chatService;
    private final AgentServiceImpl agentService;
    private final ItinerarySseGateway gateway;
    private final ItineraryEventPublisher eventPublisher;
    private final UserService userService;
    private final Executor taskExecutor;

    public ItinerarySseController(ItineraryQueryService queryService,
                                  ItineraryChatService chatService,
                                  AgentServiceImpl agentService,
                                  ItinerarySseGateway gateway,
                                  ItineraryEventPublisher eventPublisher,
                                  UserService userService,
                                  @Qualifier("taskExecutor") Executor taskExecutor) {
        this.queryService = queryService;
        this.chatService = chatService;
        this.agentService = agentService;
        this.gateway = gateway;
        this.eventPublisher = eventPublisher;
        this.userService = userService;
        this.taskExecutor = taskExecutor;
    }

    /** 订阅行程生成进度事件流；归属校验复用详情查询的拥有者语义（非本人 404）。 */
    @GetMapping("/{id}/events")
    public SseEmitter events(@PathVariable Long id) {
        queryService.findOwnedMain(currentUserId(), id);
        return gateway.subscribe(id);
    }

    /**
     * 对话编辑 SSE 变体：方法内创建 emitter，把阻塞的 chatTurn 调用提交到 taskExecutor，
     * 结果 reply 分片成 chat_token → chat_draft → chat_done 推给浏览器。
     * payload 与阻塞版 chatEdit 完全同参构造，保证两条路径的 Agent 输入一致。
     */
    @PostMapping("/{id}/chat-edit/stream")
    public SseEmitter chatEditStream(@PathVariable Long id,
                                     @RequestBody Map<String, Object> body) {
        Long userId = currentUserId();
        queryService.findOwnedMain(userId, id);
        String message = String.valueOf(body.getOrDefault("message", ""));
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> history =
                (List<Map<String, Object>>) body.getOrDefault("history", List.of());

        SseEmitter emitter = new SseEmitter(0L);
        ItineraryChatService.ChatTurnContext ctx;
        try {
            ctx = chatService.buildChatTurnContext(userId, id, message, history);
        } catch (Exception e) {
            // 上下文构建失败（归属问题上方已校验，这里多为 DB/序列化故障）：发 error 后收尾
            sendLocal(id, emitter, "error",
                    Map.of("code", "AGENT_ERROR", "message", String.valueOf(e.getMessage()), "retryable", true));
            emitter.complete();
            return emitter;
        }
        // UUID 短串仅用于前端归并同一条回复的 token 流，与落库消息 id 无关
        String messageId = UUID.randomUUID().toString().substring(0, 8);
        try {
            taskExecutor.execute(() -> streamChatTurn(userId, id, messageId, message, ctx, emitter));
        } catch (RejectedExecutionException rejected) {
            // 池满背压：与生成任务的 429 语义一致，SSE 下转成 error 事件后收尾
            sendLocal(id, emitter, "error",
                    Map.of("code", "AGENT_BUSY", "message", "行程助手繁忙，请稍后重试", "retryable", true));
            emitter.complete();
        }
        return emitter;
    }

    /** 流式任务主体：chatTurn → 落库 → chat_token* → chat_draft → chat_done；任何失败转 error 事件。 */
    private void streamChatTurn(Long userId, Long itineraryId, String messageId, String message,
                                ItineraryChatService.ChatTurnContext ctx, SseEmitter emitter) {
        try {
            JsonNode node = agentService.chatTurn(ctx.chatBody());
            // 与阻塞端点同一条收尾路径（组装出参 + 落库对话记忆），保证历史与
            // pendingAction 语义一致；reply 经 chat_token 流式推送，其余字段随 chat_draft 一次送达。
            Map<String, Object> out = chatService.finalizeChatTurn(userId, itineraryId, message, ctx, node);
            String reply = String.valueOf(out.get("reply"));
            for (String delta : chunk(reply, CHAT_TOKEN_CHUNK_SIZE)) {
                sendLocal(itineraryId, emitter, "chat_token",
                        Map.of("messageId", messageId, "delta", delta));
            }
            // chat_draft 除 reply 外携带 /chat-edit 响应全部字段（含 DB messageId/hotelOptions/changed），
            // 前端可无缝复用既有草稿与酒店卡片逻辑；reply 单独剔除（已按 token 送达）。
            Map<String, Object> draftPayload = new java.util.LinkedHashMap<>(out);
            draftPayload.remove("reply");
            sendLocal(itineraryId, emitter, "chat_draft", draftPayload);
            sendLocal(itineraryId, emitter, "chat_done", Map.of("messageId", messageId));
            emitter.complete();
        } catch (Exception e) {
            // emitter 可能已断开：error 事件发不出去也无所谓，仍要 complete 释放连接
            try {
                sendLocal(itineraryId, emitter, "error", Map.of(
                        "code", "AGENT_ERROR",
                        "message", String.valueOf(e.getMessage()),
                        "retryable", true));
            } catch (Exception ignored) {
                // 连接已死，忽略
            }
            try {
                emitter.complete();
            } catch (Exception ignored) {
                // 同上
            }
        }
    }

    /**
     * 经发布器的 publishLocal 取 seq 组信封后本地直发（不走 Redis 广播——chat 是点对点会话）。
     * sink 内把 IOException 转为 UncheckedIOException 向上传播，调用方据此停止发送。
     */
    private void sendLocal(Long itineraryId, SseEmitter emitter, String type, Map<String, Object> data) {
        eventPublisher.publishLocal(itineraryId, type, data, json -> {
            try {
                emitter.send(SseEmitter.event().data(json, MediaType.APPLICATION_JSON));
            } catch (IOException e) {
                throw new UncheckedIOException(e);
            }
        });
    }

    /**
     * reply 分片：约 size 字符一片（最后一片可能更短）。抽成静态方法便于单测
     * （工程无 MockMvc 先例，controller 里的分片逻辑以纯函数方式验证）。
     */
    static List<String> chunk(String text, int size) {
        List<String> chunks = new ArrayList<>();
        if (text == null || text.isEmpty() || size <= 0) {
            return chunks;
        }
        for (int i = 0; i < text.length(); i += size) {
            chunks.add(text.substring(i, Math.min(text.length(), i + size)));
        }
        return chunks;
    }

    /**
     * 获取当前登录用户 ID（与 ItineraryController 一致：J9 请求内记忆化，一个请求只查一次库）。
     */
    private Long currentUserId() {
        return SecurityUtils.cachedUserId(() ->
                userService.getByUsername(SecurityUtils.currentUsername()).getId());
    }
}
