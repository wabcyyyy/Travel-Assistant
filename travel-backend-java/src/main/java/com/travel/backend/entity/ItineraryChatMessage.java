package com.travel.backend.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

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
