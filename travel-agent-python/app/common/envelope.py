"""统一响应信封，兼容 Java 侧 `Result<T>`。

前端 `src/api/request.ts:32-43` 的判据是 `res.code !== 200 → 报错并 reject`，
且成功时取的是**整个响应体**（调用方再写 `res.data`）。迁移期任何接口擅自换成
裸 JSON / HTTP-only 语义，都会让前端静默拿到 undefined。因此信封必须原样保留，
直到前端一并改造（本期不改）。

`ApiError.status` **既作 HTTP 状态码、也作 body.code**；归属/存在性校验失败
一律 404，不用 403 暴露资源是否存在。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

CODE_SUCCESS = 200
CODE_BAD_REQUEST = 400
CODE_ERROR = 500


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status if 400 <= status < 600 else CODE_ERROR
        self.message = message


def ok(data: Any = None, message: str = "success") -> dict[str, Any]:
    return {"code": CODE_SUCCESS, "message": message, "data": data}


def fail(status: int, message: str) -> dict[str, Any]:
    return {"code": status, "message": message, "data": None}


def install_exception_handlers(app: FastAPI) -> None:
    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(ApiError)
    async def _handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=fail(exc.status, exc.message))

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # /api/agent 是 Python 原生的内部 API，既有契约（与一批测试）按 FastAPI 的
        # 422 + detail 数组断言；只有从 Java 迁过来的业务路径才需要 400 + 单条 message。
        from fastapi.encoders import jsonable_encoder

        if request.url.path.startswith("/api/agent"):
            return JSONResponse(status_code=422, content=jsonable_encoder({"detail": exc.errors()}))
        errors = exc.errors()
        message = "请求参数不合法"
        if errors:
            message = str(errors[0].get("msg") or message).replace("Value error, ", "")
        return JSONResponse(status_code=CODE_BAD_REQUEST, content=fail(CODE_BAD_REQUEST, message))

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # 与 Java 兜底一致：不把内部异常细节回给客户端，但保留可追踪的 code
        return JSONResponse(status_code=CODE_ERROR, content=fail(CODE_ERROR, "系统繁忙，请稍后重试"))
