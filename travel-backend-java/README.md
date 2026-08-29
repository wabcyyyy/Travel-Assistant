# travel-backend-java

Spring Boot 3.2.5 后端服务：认证、行程管理、预算引擎、高德地图封装、Redis 缓存、异步 PDF 导出。

## 技术栈

- Java 17 + Spring Boot 3.2.5 + Maven
- MyBatis-Plus 3.5.5（逻辑删除、自动填充）
- Spring Security + JJWT 0.12.5（无状态 JWT 认证）
- Spring Data Redis（`amap:poi` 1h / `itinerary:detail` 10m 缓存）
- Thymeleaf + OpenPDF（PDF 导出，内嵌 simhei.ttf 中文字体）

## 目录结构

```
src/main/java/com/travel/
├── controller/     # Auth / Itinerary / Export / Amap / Test
├── serviceImpl/    # 业务实现（BudgetEngineImpl 预算引擎核心）
├── mapper/         # MyBatis-Plus Mapper
├── entity/ vo/ dto/ # 实体与出入参
├── config/         # Security / Redis / MyBatisPlus / RestTemplate
└── common/         # Result 统一响应 / 全局异常 / JWT 工具
src/main/resources/
├── application.yml   # 全部配置走环境变量占位
└── templates/export/itinerary.html  # PDF 模板
```

## 启动

```bash
cp .env.example .env   # 填入 AMAP_WEB_KEY、MYSQL_PASSWORD（spring-dotenv 自动读取，勿提交）
mvn spring-boot:run "-Dspring-boot.run.jvmArguments=-Dfile.encoding=UTF-8"

# 8081 测试实例（连接 travel_test 库）：.env 中加 MYSQL_DB=travel_test 后另开终端执行
mvn spring-boot:run "-Dspring-boot.run.jvmArguments=-Dfile.encoding=UTF-8" "-Dspring-boot.run.arguments=--server.port=8081"
```

> - Windows 下务必加 `-Dfile.encoding=UTF-8`，否则中文乱码。
> - `.env` 通过 `spring-dotenv` 加载，也可改用系统环境变量（优先级更高）。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MYSQL_HOST/PORT` | `localhost:3306` | MySQL 地址 |
| `MYSQL_USER` | `root` | 数据库用户 |
| `MYSQL_PASSWORD` | 必填 | 数据库密码，不使用仓库内置默认值 |
| `MYSQL_DB` | `travel_assistant` | 数据库名（测试实例用 `travel_test`） |
| `REDIS_HOST/PORT/PASSWORD` | `localhost:6380/空` | Redis |
| `JWT_SECRET` | 空（进程级随机密钥） | 建议显式配置至少 32 位随机字符串；未配置时重启会使旧登录失效 |
| `AGENT_SERVICE_URL` | `http://localhost:8000` | Agent 服务地址 |
| `AGENT_INTERNAL_TOKEN` | 空 | 与 Agent 服务配置相同后启用内部调用认证 |
| `AMAP_WEB_KEY` | 空 | 高德 Web 服务 key，未配置时 POI 接口返回 400 |
| `EXPORT_DIR` | `data/export` | PDF 导出目录 |

## 核心接口

| 接口 | 说明 |
| --- | --- |
| `POST /api/auth/register` / `login` / `GET /api/user/info` | 注册 / 登录（JWT）/ 用户信息 |
| `POST /api/itinerary/generate` | 调 Agent 生成行程（含预算） |
| `GET /api/itinerary` / `GET /api/itinerary/{id}` / `DELETE /api/itinerary/{id}` | 列表 / 详情（缓存）/ 删除 |
| `POST /api/itinerary/{id}/items` | 新增行程项（触发预算重算） |
| `PUT /api/itinerary/items/{itemId}` / `DELETE /api/itinerary/items/{itemId}` | 修改 / 删除行程项（触发预算重算） |
| `PUT /api/itinerary/{id}/days/{dayId}/order` | 调整当日行程顺序（触发预算重算） |
| `GET /api/amap/geocode` / `GET /api/amap/poi` | 地理编码 / POI 搜索（Redis 缓存） |
| `POST /api/export/pdf/{itinId}` / `GET /api/export/tasks/{taskId}` / `GET /api/export/download/{taskId}` | 异步 PDF 导出：创建 / 轮询 / 下载 |
| `GET /api/test/hello` / `GET /api/test/call-agent` | 联通性测试 |

除 `/api/auth/**` 与 `/api/test/**` 外均需 `Authorization: Bearer <token>`。

## 测试

```bash
mvn -q test   # BudgetEngineImpl 6 用例（JUnit5 + Mockito）
```

## 设计要点

- **预算引擎（D1）**：数据源仅 `poi_knowledge`（门票）+ `city_consumption`（消费系数），生成/编辑后统一 `recalculate()` 写 `budget_detail`
- **高德调用**：`getForObject(java.net.URI, ...)` 直接传 URI，避免 RestTemplate 二次编码导致中文关键词失效
- **逻辑删除**：`deleted` 字段逻辑删除，导出任务归属校验防止越权访问
