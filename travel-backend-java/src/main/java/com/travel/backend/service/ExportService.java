package com.travel.backend.service;

import com.travel.backend.vo.ExportTaskVO;

import java.io.File;

public interface ExportService {

    ExportTaskVO createPdf(Long userId, Long itineraryId);

    ExportTaskVO getTask(Long userId, Long taskId);

    File getPdfFile(Long userId, Long taskId);
}