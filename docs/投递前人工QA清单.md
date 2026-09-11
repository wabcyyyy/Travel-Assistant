# 投递前人工 QA 清单

> 用途：开源 GitHub / 校招投递 / 现场演示前的自检。  
> 原则：**宁可少吹一句，不要被当场打穿一句。**  
> 建议按顺序执行；未完成项不要在简历/README 里当「已完成」写。

---

## 0. 密钥与账号（必做，5–15 分钟）

| # | 检查项 | 通过标准 |
|---|--------|----------|
| 0.1 | 阿里云百炼 / DashScope Key 已 rotate | 控制台旧 Key 已禁用；本地 `.env` 为新 Key |
| 0.2 | 高德 **Web** Key 已 rotate | 同上 |
| 0.3 | 高德 **JS** Key + 安全密钥已 rotate | 控制台配置了演示域名白名单 + 配额 |
| 0.4 | Unsplash Access Key 已 rotate | 本地 `.env` 更新 |
| 0.5 | `JWT_SECRET` ≥32 位随机（非示例值） | 两端/根目录 `.env` 已改 |
| 0.6 | `AGENT_INTERNAL_TOKEN` 两端一致且非示例值 | Java `.env` = Python `.env` |
| 0.7 | MySQL 非 root 或强口令 | 勿再用弱口令演示库对外 |
| 0.8 | 跑密钥扫描 | `powershell -File scripts/check-secrets.ps1` 输出 OK |
| 0.9 | 删除本地 token dump | `%TEMP%\travel-assistant-local-artifacts\` 已删 |
| 0.10 | 确认历史未提交 `.env` | `git ls-files \| findstr /i ".env token test-report"` 无敏感输出 |

---

## 1. 仓库卫生

| # | 检查项 | 通过标准 |
|---|--------|----------|
| 1.1 | `.gitignore` 含 `.env`、`.test-report/`、`*.token`、`dist/`、`target/` | 已确认 |
| 1.2 | 仓库无真实密钥、无 JWT dump | 扫描 OK |
| 1.3 | `.env.example` 仅占位符 | 打开确认无真实 Key |
| 1.4 | 不截图含 Key 的终端/Network 面板 | 录屏/截图前先检查 |
| 1.5 | 作品集/网盘打包前再扫一遍 | 打包目录 ≠ 本地开发全量 |

---

## 2. 启动与健康检查（本机）

| # | 步骤 | 通过标准 |
|---|------|----------|
| 2.1 | MySQL / Redis 已启动 | 端口可连 |
| 2.2 | `start-all.cmd` 或分端启动 | Java :8080、Agent :8000、前端 :5173 |
| 2.3 | 健康接口 | `GET /api/test/hello`、`GET /api/agent/hello` 正常 |
| 2.4 | 缺 `JWT_SECRET` 时 Java 拒绝启动 | 可临时验证 fail-fast（测完改回） |
| 2.5 | 离线单测 | `uv run pytest --ignore=tests/api --ignore=tests/perf --ignore=tests/agent_eval -q` → **235 passed** |

---

## 3. 黄金路径（人工点一遍，约 10 分钟）

| # | 场景 | 通过标准 |
|---|------|----------|
| 3.1 | 注册新用户 | 密码 8–32 且含字母+数字；弱口令被拒 |
| 3.2 | 登录 | 进入首页；F12 → Application → Cookies 有 **HttpOnly** `TA_AUTH` |
| 3.3 | 生成行程（如 杭州 2 天） | 渐进出现日行程；无 500 白屏 |
| 3.4 | 详情页 | 列表 ↔ 地图联动；预算分类合理 |
| 3.5 | 来源标签 | 知识库项有 source/核验；模型自选点「待确认」 |
| 3.6 | 附近推荐 | 返回真实近邻或空；**不编造距离** |
| 3.7 | 对话/自然语言编辑 | 能删/改；版本冲突时拒绝旧草稿 |
| 3.8 | PDF 导出 | 轮询完成并能下载；中文字体正常 |
| 3.9 | 管理端（admin） | 普通用户进不去；admin 能看用户/行程/Token 看板 |
| 3.10 | 登出 | Cookie 被清除；再访问需鉴权接口 401；旧 Cookie 不可用 |

---

## 4. 安全抽查（演示加分项）

| # | 检查项 | 通过标准 |
|---|--------|----------|
| 4.1 | 未登录调 `/api/amap/geocode` | 401 |
| 4.2 | 未登录调 `/api/amap/staticmap` | 仍可显示缩略图（有意 permitAll，有限流/白名单） |
| 4.3 | 伪造 `X-Forwarded-For` 爆破登录 | 仍被限速（默认不信未受信代理的 XFF） |
| 4.4 | 登出后重放旧 Bearer/Cookie | 被吊销（若 Redis 可用） |
| 4.5 | 前端 localStorage 无 JWT | 仅有 username/role |
| 4.6 | 错误响应无 SQL/内部堆栈 | 生成失败只见通用文案 |

---

## 5. 文档与简历口径对齐

| # | 检查项 | 通过标准 |
|---|--------|----------|
| 5.1 | README 含「已知局限」 | 有非生产系统说明 |
| 5.2 | README 链到合规文档 | `docs/合规与开源安全.md` |
| 5.3 | 项目介绍架构描述与代码一致 | 统一图 `trip_graph`，非「三套图」 |
| 5.4 | 简历/简历项目描述无禁用词 | 见下表 |
| 5.5 | 演示脚本与真实功能一致 | 不宣称默认关闭的能力 |

### 5.4 禁用词 → 可用表述

| 不要写 | 改成 |
|--------|------|
| 生产级安全 / 企业级架构 | 演示级安全基线 + 已知短板 |
| 联网实时酒店报价 | 知识库基准价 × 季节系数估算 |
| 行程 100% 准确 / 零幻觉 | 引用落地有 source；自选点待复核 |
| 完全自主多 Agent | 三域研究 Agent + Supervisor 证据整合 |
| 高并发 / 高可用 | 有界线程池背压；未做集群验证 |
| 223+ 测试证明质量 | 离线 235 passed + 真实 LLM 评测分开报告 |

---

## 6. 演示录制 / 截图前

| # | 检查项 |
|---|--------|
| 6.1 | 浏览器无其它标签的账号/密钥 |
| 6.2 | Network 面板不录到 `Authorization` / Cookie 值 |
| 6.3 | 终端不显示完整 LLM Key（启动日志） |
| 6.4 | 使用专用演示账号，不用个人/含隐私行程 |
| 6.5 | 准备 1 个失败降级样例（如无 Key 时的待研究草案）——比全成功更有说服力 |

---

## 7. 面试/投递材料包

| # | 内容 | 建议 |
|---|------|------|
| 7.1 | GitHub 链接 | 指向干净提交历史 |
| 7.2 | README 首屏 | 30 秒讲清「解决 LLM 编造」+ 架构一图 |
| 7.3 | `docs/代码审计报告.md` | 可附，展示自审能力 |
| 7.4 | `docs/校招面试审查报告.md` | **不要**原样给面试官；仅自查 |
| 7.5 | 3 分钟口述稿 | 问题 → 方案 → tradeoff → 未做 |

---

## 8. 最终 Go / No-Go

**全部勾选才 Go：**

- [ ] 0.x 密钥全部 rotate + 扫描 OK  
- [ ] 1.x 仓库无敏感文件  
- [ ] 2.x 本机可启动 + 235 测试绿  
- [ ] 3.1–3.10 黄金路径走通  
- [ ] 4.1 / 4.3 / 4.5 / 4.10（登出吊销）抽查通过  
- [ ] 5.x 文档与简历无禁用词  
- [ ] 6.x 截图/录屏已脱敏  

**任一失败 → No-Go**，先修再投。

---

## 附：一分钟命令速查

```powershell
# 密钥扫描
powershell -File scripts/check-secrets.ps1

# 离线测试
cd travel-agent-python
.\.venv\Scripts\python.exe -m pytest tests/ --ignore=tests/api --ignore=tests/perf --ignore=tests/agent_eval -q

# 确认 git 未跟踪敏感文件
git ls-files | findstr /i ".env token test-report secret"

# 健康检查
curl http://127.0.0.1:8080/api/test/hello
curl http://127.0.0.1:8000/api/agent/hello
```

---

相关文档：`docs/合规与开源安全.md` · `README.md` → 已知局限 · `docs/项目介绍.md` → 已知局限与安全边界
