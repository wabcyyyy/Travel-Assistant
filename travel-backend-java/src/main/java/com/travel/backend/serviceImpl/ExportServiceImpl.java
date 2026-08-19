package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.travel.backend.common.BizException;
import com.travel.backend.entity.ExportTask;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.mapper.ExportTaskMapper;
import com.travel.backend.mapper.ItineraryMainMapper;
import com.travel.backend.service.ExportService;
import com.travel.backend.vo.ExportTaskVO;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.File;

@Service
public class ExportServiceImpl implements ExportService {

    private final ExportTaskMapper taskMapper;
    private final ItineraryMainMapper mainMapper;
    private final ExportTaskRunner taskRunner;
    private final String exportDir;

    public ExportServiceImpl(ExportTaskMapper taskMapper, ItineraryMainMapper mainMapper,
                             ExportTaskRunner taskRunner,
                             @Value("${app.export.dir:data/export}") String exportDir) {
        this.taskMapper = taskMapper;
        this.mainMapper = mainMapper;
        this.taskRunner = taskRunner;
        this.exportDir = exportDir;
    }

    @Override
    public ExportTaskVO createPdf(Long userId, Long itineraryId) {
        ItineraryMain main = mainMapper.selectById(itineraryId);
        if (main == null || !main.getUserId().equals(userId)) {
            throw new BizException(404, "行程不存在");
        }
        ExportTask task = new ExportTask();
        task.setItineraryId(itineraryId);
        task.setUserId(userId);
        task.setTaskType("PDF");
        task.setStatus("RUNNING");
        taskMapper.insert(task);
        taskRunner.renderPdf(task.getId());
        return toVO(task, false);
    }

    @Override
    public ExportTaskVO getTask(Long userId, Long taskId) {
        ExportTask task = findOwnedTask(userId, taskId);
        return toVO(task, "DONE".equals(task.getStatus()));
    }

    @Override
    public File getPdfFile(Long userId, Long taskId) {
        ExportTask task = findOwnedTask(userId, taskId);
        if (!"DONE".equals(task.getStatus())) {
            throw new BizException(400, "导出任务尚未完成");
        }
        File file = new File(task.getFilePath());
        if (!file.exists()) {
            throw new BizException(404, "导出文件不存在");
        }
        return file;
    }

    private ExportTask findOwnedTask(Long userId, Long taskId) {
        ExportTask task = taskMapper.selectById(taskId);
        if (task == null || !task.getUserId().equals(userId)) {
            throw new BizException(404, "导出任务不存在");
        }
        return task;
    }

    private ExportTaskVO toVO(ExportTask task, boolean includeDownloadUrl) {
        ExportTaskVO vo = new ExportTaskVO();
        vo.setId(task.getId());
        vo.setItineraryId(task.getItineraryId());
        vo.setTaskType(task.getTaskType());
        vo.setStatus(task.getStatus());
        vo.setErrorMsg(task.getErrorMsg());
        vo.setCreatedAt(task.getCreatedAt());
        vo.setFinishedAt(task.getFinishedAt());
        if (includeDownloadUrl) {
            vo.setDownloadUrl("/api/export/download/" + task.getId());
        }
        return vo;
    }
}