package com.travel.backend.common;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.resource.NoResourceFoundException;
import org.springframework.http.ResponseEntity;
import org.springframework.http.HttpStatus;

@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(BizException.class)
    public ResponseEntity<Result<Void>> handleBizException(BizException e) {
        log.warn("business exception: {}", e.getMessage());
        return ResponseEntity.status(httpStatus(e.getCode()))
                .body(Result.fail(e.getCode(), e.getMessage()));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Result<Void>> handleValidationException(MethodArgumentNotValidException e) {
        FieldError fieldError = e.getBindingResult().getFieldError();
        String message = fieldError == null ? "参数校验失败" : fieldError.getDefaultMessage();
        return ResponseEntity.badRequest().body(Result.fail(400, message));
    }

    @ExceptionHandler(MissingServletRequestParameterException.class)
    public ResponseEntity<Result<Void>> handleMissingParam(MissingServletRequestParameterException e) {
        return ResponseEntity.badRequest().body(Result.fail(400, "缺少必填参数：" + e.getParameterName()));
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<Result<Void>> handleMessageNotReadable(HttpMessageNotReadableException e) {
        return ResponseEntity.badRequest().body(Result.fail(400, "请求体格式错误"));
    }

    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<Result<Void>> handleNoResourceFound(NoResourceFoundException e) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Result.fail(404, "接口不存在"));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Result<Void>> handleException(Exception e) {
        log.error("unexpected error", e);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(Result.fail("系统繁忙，请稍后重试"));
    }

    private HttpStatus httpStatus(int code) {
        try {
            return HttpStatus.valueOf(code);
        } catch (IllegalArgumentException e) {
            return HttpStatus.INTERNAL_SERVER_ERROR;
        }
    }
}
