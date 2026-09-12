package com.travel.backend.controller;

import com.travel.backend.common.Result;
import com.travel.backend.common.SecurityUtils;
import com.travel.backend.service.ExportService;
import com.travel.backend.service.UserService;
import com.travel.backend.vo.ExportTaskVO;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.io.File;

@RestController
@RequestMapping("/api/export")
public class ExportController {

    private final ExportService exportService;
    private final UserService userService;

    public ExportController(ExportService exportService, UserService userService) {
        this.exportService = exportService;
        this.userService = userService;
    }

    @PostMapping("/pdf/{itineraryId}")
    public Result<ExportTaskVO> createPdf(@PathVariable Long itineraryId) {
        return Result.ok(exportService.createPdf(currentUserId(), itineraryId));
    }

    @GetMapping("/tasks/{taskId}")
    public Result<ExportTaskVO> getTask(@PathVariable Long taskId) {
        return Result.ok(exportService.getTask(currentUserId(), taskId));
    }

    @GetMapping("/download/{taskId}")
    public ResponseEntity<Resource> download(@PathVariable Long taskId) {
        File file = exportService.getPdfFile(currentUserId(), taskId);
        FileSystemResource resource = new FileSystemResource(file);
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION,
                        "attachment; filename=itinerary_" + taskId + ".pdf")
                .contentType(MediaType.APPLICATION_PDF)
                .contentLength(file.length())
                .body(resource);
    }

    /**
     * 获取当前登录用户 ID（从 JWT 中解析）。
     * J9：包一层请求内记忆化——一个请求多次调用 currentUserId 只 getByUsername 查一次库。
     */
    private Long currentUserId() {
        return SecurityUtils.cachedUserId(() ->
                userService.getByUsername(SecurityUtils.currentUsername()).getId());
    }
}