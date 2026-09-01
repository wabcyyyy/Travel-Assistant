package com.travel.backend.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 异步导出任务表实体。
 *
 * <p>对应表 {@code export_task}，存储 PDF/图片导出的异步任务状态。</p>
 *
 * <p>状态流转：RUNNING → DONE / FAILED</p>
 *
 * <p>前端通过轮询 GET /export/tasks/{id} 查看任务状态，
 * 完成后通过 GET /export/download/{id} 下载文件。</p>
 *
 * @see com.travel.backend.controller.ExportController
 */
@Data
@TableName("export_task")
public class ExportTask {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long itineraryId;
    private Long userId;
    private String taskType;
    private String status;
    private String filePath;
    private String errorMsg;
    private LocalDateTime createdAt;
    private LocalDateTime finishedAt;
    @TableLogic
    private Integer deleted;
}