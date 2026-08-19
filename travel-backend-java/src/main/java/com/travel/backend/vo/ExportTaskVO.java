package com.travel.backend.vo;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class ExportTaskVO {

    private Long id;
    private Long itineraryId;
    private String taskType;
    private String status;
    private String errorMsg;
    private String downloadUrl;
    private LocalDateTime createdAt;
    private LocalDateTime finishedAt;
}