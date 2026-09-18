# 深链语义 parity 差异表(前后端地图深链)

地图深链存在前后端两份实现,用 `deeplink_cases.json`(同目录,16 个共享 case)把两侧
各自钉住,任何一侧单方面改语义都会显形:

- 后端断言:`travel-agent-python/tests/test_deeplink_parity.py`(`app.agent.places.map_search_url` / `map_directions_url`)
- 前端断言:`travel-frontend-vue/src/utils/deeplink.parity.test.ts`(`src/utils/geo.ts` 的 `externalMapLink` / `mapDirectionsUrl`)

断言粒度 = 协议 host + path 前缀 + 关键查询参数存在/缺席;`src`/`callnative`/`policy`/
`coordinate` 与坐标数值等实现细节不整串相等。两侧期望不同(协议层)的 case 在两个测试里
都必须登记说明;期望相同的 case 不允许登记——保证本表不漏记、不过期。

## 2026-09-18 统一决策记录(D1-D10 拍板,全部按推荐执行)

| # | 原分歧 | 决策 | 落点 |
|---|--------|------|------|
| D1 | 国内搜索有坐标:后端 marker(不换算)vs 前端关键词 | 后端保留 marker 但**先换算 GCJ-02**(精确且不偏移);前端维持关键词。链接形态差异保留,**已知且接受** | `places.to_gcj02`(与前端 `coordinates.toGcj02` 同式,两侧测试各钉已知值) |
| D2 | 越界坐标后端无校验、误判海外 | 后端引入与前端 `hasValidCoordinates` 同语义的 `_parse_coords`(有限值+90/180+非 0/0),判定与打点共用 | 已统一,两侧均回落关键词 |
| D3 | 汉字名海外城市判定相反 | 后端删除汉字兜底,无/无效坐标改查 **`city_geo.is_domestic`**(V4 保留字典即为判定);字典未收录/库不可用**默认海外**(谷歌链接对国内点只是体验次优,高德链接对海外点是错误国家) | `places._dict_domestic`;parity 测试把字典钉成固定映射测链接逻辑,DB 路径单独单测 |
| D4 | 海外搜索坐标 vs 名称 | 后端对齐前端:有有效坐标用 `lat,lng`,回落名称关键词 | 已统一 |
| D5 | 高德 via 上限 | 官方 URI 文明确认**最多 1 个途经点**:后端对齐前端,超出返回 None(界面提示分段) | 已统一;eval 深度指标的"全天路线达标"随之更真实(当前 fixture 指标不变) |
| D6 | 谷歌 waypoints 上限 | 官方无明示上限、实践 ~9-10:**前端维持限 3**(移动端保守),后端暂不设上限——**已知且接受** | `route_foreign_seven_stops` 两侧期望不同,已登记 |
| D7 | 0/0 哨兵后端两处不一致 | 并入 D2:统一谓词后判定/打点同口径 | 已统一 |
| D8 | 高德路线不换算 GCJ-02 | 并入 D1:from/to/via 全部先换算 | 已统一 |
| D9 | 关键词拼接无分隔(前端) | 前端改空格分隔(与后端一致),消除「New YorkTimes Square」类坏关键词 | `geo.ts` 已改,`geo.test.ts` 期望同步 |
| D10 | 谷歌路线 origin/destination 名称 vs 坐标 | 后端对齐前端:恒用坐标(停靠点已过有效性谓词) | 已统一 |

## 剩余差异(仅 2 条,均为"已知且接受")

| case | 后端 | 前端 | 定性 |
|------|------|------|------|
| search_domestic_with_coords(D1) | `uri.amap.com/marker`(GCJ-02 换算后精确打点) | `uri.amap.com/search` 名称关键词 | 已知且接受:链接形态不同、各自正确 |
| route_foreign_seven_stops(D6) | 谷歌 dir,waypoints 5 个(不设上限) | null(移动端限 3) | 已知且接受 |

## 历史记录(统一前的主要分歧,2026-09-18 之前)

- 后端无坐标按"城市名含汉字"判国内 → 巴厘岛/东京等汉字名海外地拿到错误国家的高德链接;
- 0/0 哨兵在后端判定阶段(当真坐标→误判海外)与打点阶段(当无坐标)两处口径相反;
- 越界坐标(200, -95)后端不校验,国界框落空误判海外,路线中照常纳入;
- 高德路线 via 无上限、谷歌路线 waypoints 无上限,高德坐标不换算 GCJ-02。
