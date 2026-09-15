# AGENTS.md — travel-frontend-vue

Vue3 + Vite + TS，MapLibre + OpenFreeMap 免 key 底图。先读根 `../AGENTS.md`。

## 外观门禁（只减不增，CI 已接）

- `npm run theme:lint`：禁裸色值与野 z-index；豁免表（`scripts/theme-lint.allowlist.json`）只准变短。新颜色必须走 `src/styles/theme.css` 的令牌体系。
- `npm run ep:lint`：Element Plus 组件使用清单（`scripts/ep-allowlist.json`）只减不增——主路径交互控件一律换自研 `src/components/ui/` 层，不允许往回加 EP 组件。

## 结构惯例

- **后端只经 `src/api/` 模块访问**：URL、信封解包、类型集中在 `src/api/*.ts`；视图与组件里禁止散落裸 `fetch`/`EventSource`（`test_cutover_contract` 会扫）。
- **大组件拆分**：视图文件只做编排；可复用的区块拆到 `src/components/trip/`（工作台域）、`src/components/ui/`（交互控件层）等域目录，并用 vitest 配 `.test.ts`。改到哪个巨头组件，就把它新拆出去的部分留在拆分后的位置，不要把新功能继续堆进巨头。
- **全局状态**：Pinia store（`src/store/`）是单一数据源；组件间不互相传大块行程状态。
- **外观写入口唯一**：主题/密度/动效切换只经 `src/styles/appearance.ts`，首帧无 FOUC 靠内联引导脚本，别绕过它直接操作 DOM 样式。

## 命令

```bash
npm run dev        # 本地开发（/api 代理到 :8000）
npm run build      # vue-tsc strict + vite 构建门禁
npm run test:unit  # vitest
npm run theme:lint # 外观门禁
npm run ep:lint    # EP 使用清单门禁
```
