package com.travel.backend.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 行程对话记忆表实体。
 *
 * <p>对应表 {@code itinerary_chat_message}，存储对话编辑过程中的消息历史。</p>
 *
 * <p>关键字段：</p>
 * <ul>
 *   <li>{@code role} — 消息角色：user(用户) / ai(Agent)</li>
 *   <li>{@code plansJson} — AI 消息携带的草稿方案 JSON（供 apply-plans 读取）</li>
 *   <li>{@code hotelOptionsJson} — AI 消息携带的酒店候选 JSON</li>
 *   <li>{@code changed} — 是否有实质变更（0=无变更 / 1=有变更）</li>
 * </ul>
 *
 * <p>对话历史按 itinerary_id + user_id 维度存储，前端可加载历史恢复对话。</p>
 *
 * @see ItineraryMain
 */
@Data
@TableName("itinerary_chat_message")
public class ItineraryChatMessage {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long itineraryId;
    private Long userId;
    private String role;
    private String content;
    private String plansJson;
    private String hotelOptionsJson;
    private Integer changed;
    private LocalDateTime createdAt;
}
