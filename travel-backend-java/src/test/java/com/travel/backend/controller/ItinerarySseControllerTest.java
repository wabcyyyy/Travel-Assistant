package com.travel.backend.controller;

import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;
import com.travel.backend.common.ItineraryEventPublisher;
import com.travel.backend.common.ItinerarySseGateway;
import com.travel.backend.service.AgentService;
import com.travel.backend.service.UserService;
import com.travel.backend.service.impl.ItineraryChatService;
import com.travel.backend.service.impl.ItineraryQueryService;
import com.travel.backend.vo.UserVO;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InOrder;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.RejectedExecutionException;
import java.util.function.Consumer;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * chat-edit/stream 端点测试（工程无 MockMvc 先例，直接构造 controller 依赖 mock）：
 * 验证事件序列 chat_token* → chat_draft → chat_done、异常/拒绝转 error，
 * 以及分片纯函数 chunk() 的边界行为。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class ItinerarySseControllerTest {

    @Mock
    private ItineraryQueryService queryService;
    @Mock
    private ItineraryChatService chatService;
    @Mock
    private AgentService agentService;
    @Mock
    private ItinerarySseGateway gateway;
    @Mock
    private ItineraryEventPublisher publisher;
    @Mock
    private UserService userService;

    private ItinerarySseController controller;
    private final ObjectMapper json = JsonMapper.builder().build();

    @BeforeEach
    void setUp() {
        // 直接执行器：流式任务在测试线程内同步完成，事件序列可即时断言
        controller = new ItinerarySseController(queryService, chatService, agentService,
                gateway, publisher, userService, Runnable::run);
        // publishLocal 直接回调 sink，模拟信封即时送达
        doAnswer(invocation -> {
            Consumer<String> sink = invocation.getArgument(3);
            sink.accept("{\"type\":\"" + invocation.getArgument(1) + "\"}");
            return null;
        }).when(publisher).publishLocal(anyLong(), anyString(), any(), any());
        // currentUserId 需要 SecurityContext 中的登录态（currentUsername 解析 principal）
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken("alice", null, List.of()));
        UserVO user = new UserVO();
        user.setId(7L);
        org.mockito.Mockito.when(userService.getByUsername("alice")).thenReturn(user);
    }

    @AfterEach
    void clearSecurityContext() {
        // 防止登录态泄漏到同 JVM 的其它测试类
        SecurityContextHolder.clearContext();
    }

    private ItineraryChatService.ChatTurnContext context(String baseRevision) {
        return new ItineraryChatService.ChatTurnContext(new LinkedHashMap<>(Map.of("message", "x")), baseRevision);
    }

    /** 正常流：先按分片数发 chat_token，再 chat_draft（含落库 messageId/动作字段、不含 reply），最后 chat_done。 */
    @Test
    @SuppressWarnings("unchecked")
    void streamEmitsTokenThenDraftThenDone() throws Exception {
        when(chatService.buildChatTurnContext(eq(7L), eq(9L), contains("爬山"), any()))
                .thenReturn(context("rev-1"));
        ObjectNode node = json.createObjectNode();
        // 60 字回复按 40 分片 → 2 片（40+20）
        String reply = "好的".repeat(30);
        node.put("reply", reply);
        node.set("plans", json.createArrayNode());
        when(agentService.chatTurn(any())).thenReturn(node);
        // finalizeChatTurn 为阻塞/流式共用的收尾路径（含落库），流式测试 mock 其出参
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("reply", reply);
        out.put("messageId", 88L);
        out.put("changed", true);
        out.put("plans", List.of());
        out.put("hotelOptions", List.of(Map.of("name", "西湖酒店")));
        out.put("baseRevision", "rev-1");
        when(chatService.finalizeChatTurn(eq(7L), eq(9L), eq("把第二天换成爬山"), any(), any()))
                .thenReturn(out);

        controller.chatEditStream(9L, Map.of("message", "把第二天换成爬山"));

        InOrder order = inOrder(publisher);
        order.verify(publisher, org.mockito.Mockito.times(2)).publishLocal(
                eq(9L), eq("chat_token"), any(), any());
        // chat_draft 必须携带落库 messageId 与酒店卡片字段（前端复用既有草稿/酒店逻辑），
        // 且不含 reply（reply 已按 token 流式送达）
        var draftCaptor = org.mockito.ArgumentCaptor.forClass(Map.class);
        order.verify(publisher).publishLocal(eq(9L), eq("chat_draft"), draftCaptor.capture(), any());
        Map<String, Object> draft = draftCaptor.getValue();
        assertEquals(88L, draft.get("messageId"));
        assertEquals(true, draft.get("changed"));
        assertEquals("rev-1", draft.get("baseRevision"));
        assertTrue(draft.containsKey("hotelOptions"));
        assertTrue(!draft.containsKey("reply"));
        order.verify(publisher).publishLocal(eq(9L), eq("chat_done"), any(), any());
        verify(publisher, never()).publishLocal(eq(9L), eq("error"), any(), any());
        // chatTurn 与阻塞版 chatEdit 同参：直接复用构建出的 chatBody
        verify(agentService).chatTurn(any());
    }

    /** chatTurn 抛异常（Agent 不可用）：转 error 事件（AGENT_ERROR 可重试）而非静默断流。 */
    @Test
    void streamConvertsChatTurnFailureToErrorEvent() {
        when(chatService.buildChatTurnContext(anyLong(), anyLong(), anyString(), any()))
                .thenReturn(context("rev-1"));
        when(agentService.chatTurn(any())).thenThrow(new RuntimeException("agent down"));

        controller.chatEditStream(10L, Map.of("message", "hi"));

        verify(publisher).publishLocal(eq(10L), eq("error"), any(), any());
        verify(publisher, never()).publishLocal(eq(10L), eq("chat_draft"), any(), any());
        verify(publisher, never()).publishLocal(eq(10L), eq("chat_done"), any(), any());
    }

    /** 线程池拒绝（背压）：不发任何 token/draft，直接 error（AGENT_BUSY）收尾。 */
    @Test
    void streamRejectsWhenExecutorSaturated() {
        ItinerarySseController rejectingExecutorController = new ItinerarySseController(
                queryService, chatService, agentService, gateway, publisher, userService,
                task -> { throw new RejectedExecutionException("pool full"); });
        when(chatService.buildChatTurnContext(anyLong(), anyLong(), anyString(), any()))
                .thenReturn(context("rev-1"));

        rejectingExecutorController.chatEditStream(11L, Map.of("message", "hi"));

        verify(publisher).publishLocal(eq(11L), eq("error"), any(), any());
        verify(agentService, never()).chatTurn(any());
    }

    /** 上下文构建失败（DB 故障等）：error 后收尾，不提交流式任务。 */
    @Test
    void streamConvertsContextBuildFailureToErrorEvent() {
        when(chatService.buildChatTurnContext(anyLong(), anyLong(), anyString(), any()))
                .thenThrow(new RuntimeException("db down"));

        controller.chatEditStream(12L, Map.of("message", "hi"));

        verify(publisher).publishLocal(eq(12L), eq("error"), any(), any());
        verify(agentService, never()).chatTurn(any());
    }

    // ===== 分片纯函数（controller 内分片逻辑的可测入口） =====

    /** 95 字符按 40 分片 → 40/40/15。 */
    @Test
    void chunksLongTextIntoFixedSizePieces() {
        assertEquals(List.of("a".repeat(40), "a".repeat(40), "a".repeat(15)),
                ItinerarySseController.chunk("a".repeat(95), 40));
    }

    /** 空/null 文本无分片；短文本单分片。 */
    @Test
    void chunkHandlesEmptyNullAndShortText() {
        assertTrue(ItinerarySseController.chunk(null, 40).isEmpty());
        assertTrue(ItinerarySseController.chunk("", 40).isEmpty());
        assertEquals(List.of("短文本"), ItinerarySseController.chunk("短文本", 40));
    }

    /** 分片必须保序且完整拼接回原文（中文多字节按 char 计数不受影响）。 */
    @Test
    void chunksReassembleToOriginalText() {
        String reply = "西湖雷峰塔雷峰塔雷峰塔雷峰塔雷峰塔雷峰塔雷峰塔雷峰塔雷峰塔雷峰塔雷峰塔雷峰塔雷峰塔雷峰塔";
        List<String> chunks = ItinerarySseController.chunk(reply, 40);
        assertEquals(String.join("", chunks), reply);
        assertTrue(chunks.get(chunks.size() - 1).length() <= 40);
        assertTrue(chunks.stream().allMatch(c -> !c.isEmpty()));
        assertEquals((int) Math.ceil(reply.length() / 40.0), chunks.size());
    }

    /** 非法分片大小直接返回空列表，不抛异常。 */
    @Test
    void chunkWithInvalidSizeReturnsEmpty() {
        assertTrue(ItinerarySseController.chunk("abc", 0).isEmpty());
        assertTrue(ItinerarySseController.chunk("abc", -1).isEmpty());
    }
}
