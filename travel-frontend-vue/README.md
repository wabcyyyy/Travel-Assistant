# travel-frontend-vue

Vue 3 + Vite 5 + TypeScript 前端：登录、行程生成、行程列表、行程详情（地图可视化 + 拖拽编辑 + 预算看板）、PDF/图片导出。

## 技术栈

- Vue 3.4 + Vite 5 + TypeScript（vue-tsc 类型检查）
- Element Plus 2.7 + Pinia + Vue Router
- 高德地图 JSAPI 2.0（`@amap/amap-jsapi-loader`）：Marker / InfoWindow / Driving 路线
- ECharts 6（预算饼图）+ vuedraggable（拖拽排序）

## 页面与路由

| 路由 | 页面 | 说明 |
| --- | --- | --- |
| `/login` | LoginView | 登录 / 注册 |
| `/generate` | GenerateView | 输入城市/天数/偏好/预算 → 生成行程 |
| `/trips` | TripsView | 行程列表 |
| `/trips/:id` | TripDetailView | 详情：地图联动 / 拖拽编辑 / 预算看板 / 导出 |

## 启动

```bash
cp .env.example .env   # 填入 VITE_AMAP_JS_KEY / VITE_AMAP_SECURITY_CODE
npm install
npm run dev            # http://localhost:5173，/api 代理到 8080
```

构建：`npm run build`（先跑 `vue-tsc --noEmit` 类型检查）。

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `VITE_AMAP_JS_KEY` | 高德 JS key（地图渲染必需） |
| `VITE_AMAP_SECURITY_CODE` | 高德 JS 安全密钥（`amap.ts` 中通过 `securityJsCode` 注入） |

> ⚠️ 必须在高德开放平台控制台为 JS key 配置 **`localhost:5173` 域名白名单**，否则地图无法加载（`INVALID_USER_DOMAIN`）。

## 关键模块

- `src/utils/amap.ts`：AMap 加载封装（安全码注入 + 动态加载）
- `src/utils/exportImage.ts`：静态卡片图导出（无 html2canvas 依赖）
- `src/api/index.ts` + `src/api/request.ts`：axios 封装（JWT Token 拦截、401 跳登录）
- `src/components/BaseMap.vue` / `TripMap.vue`：地图容器与行程路线渲染（Marker 点击 ↔ 列表高亮双向联动）
- `src/components/BudgetPanel.vue`：预算看板（ECharts 饼图 + 分类明细 + 每日费用）