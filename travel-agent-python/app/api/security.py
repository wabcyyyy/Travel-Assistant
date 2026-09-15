"""业务路由的默认拒绝鉴权（对齐 Spring Security 的 `anyRequest().authenticated()`）。

为什么不是"每条路由自己写 Depends(require_user)"：那是**允许即安全**的反面——
新增端点时忘记加依赖就是匿名暴露，而且不会有任何报错。Java 侧是白名单式放行、
其余一律要鉴权，这里保持同样的默认方向。

agent 路由不在此列：它是 Java→Python 的内部调用面，走 `X-Agent-Token` 内部令牌
（`app/api/agent.py:require_internal_token`），不是用户会话。
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.api.deps import AuthUser, authenticate, extract_token

# 与 Java SecurityConfig 现有 permitAll 白名单逐条对应；只增不删。
# `/api/pois`（本地知识库检索）**不在**此列：它是登录用户的加点数据源，需要身份。
# 已移除的高德域端点（staticmap/poi-photo/image）随之从白名单删除，改由 media 路由承载。
PUBLIC_PATHS: tuple[str, ...] = (
    "/api/test/hello",
    "/api/auth/",
    "/error",
    "/api/poi-photo",
    "/api/image-proxy",
    # 迁移后新增（v2.2 §5.3/§6.4）：分享页与上传图必须匿名可读，否则分享链接 401
    "/api/uploads/",
    "/api/share/",
)

ADMIN_PATHS: tuple[str, ...] = ("/api/admin",)


def is_public_path(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in PUBLIC_PATHS)


def enforce_business_auth(request: Request) -> AuthUser | None:
    """router 级依赖：**总是**尝试解析身份，公开路径允许匿名，受保护路径无身份才 401。

    `permitAll` 不等于"不看票"。Spring 的 `JwtAuthenticationFilter` 对每个请求都会
    尝试认证，授权规则只决定"没有身份时能不能放行"。把它实现成"公开路径直接短路"
    会让 `/api/auth/logout-all` 这类"公开但需要知道是谁"的端点拿不到用户。
    """
    path = request.url.path
    token, _source = extract_token(request.headers.get("Authorization"), request.cookies)
    user = authenticate(token)

    if user is None and not is_public_path(path):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    if path.startswith(ADMIN_PATHS) and (user is None or not user.is_admin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return user
