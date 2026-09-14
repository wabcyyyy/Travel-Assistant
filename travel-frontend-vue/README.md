# travel-frontend-vue

Vue 3 + Vite 5 + TypeScript 前端：登录、行程生成、行程列表、行程详情（逐天叙事手册 + 拖拽编辑 + 预算横条）、PDF/图片导出。点位导航统一走卡片上的高德/谷歌外链（国外自动切 Google Maps），不再内嵌地图组件。

## 技术栈

- Vue 3.4 + Vite 5 + TypeScript（vue-tsc 类型检查）
- Element Plus 2.7 + Pinia + Vue Router
- ECharts 6（管理端图表，按需注册）+ vuedraggable（拖拽排序）

## 页面与路由

| 路由 | 页面 | 说明 |
| --- | --- | --- |
| `/login` | LoginView | 登录 / 注册 |
| `/generate` | GenerateView | 输入城市/天数/偏好/预算 → 生成行程 |
| `/trips` | TripsView | 行程列表 |
| `/trips/:id` | TripDetailView | 详情：逐天叙事手册 / 拖拽编辑 / 预算横条 / 发现更多 / 导出 |

## 启动

```bash
cp .env.example .env   # 填入 VITE_AMAP_JS_KEY
npm install
npm run dev            # http://localhost:5173，/api 代理到 8080
```

构建：`npm run build`（先跑 `vue-tsc --noEmit` 类型检查）。

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `VITE_AMAP_JS_KEY` | 高德 JS key（国内行程项的图片/链接行为开关与高德外链能力） |

> ⚠️ JS Key 会进入浏览器产物，必须在高德开放平台控制台配置 **`localhost:5173` 域名白名单**并限制配额。
