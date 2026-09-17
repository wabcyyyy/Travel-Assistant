# 深链语义 parity 差异表（Y4 产物）

地图深链存在前后端两份实现，用 `deeplink_cases.json`（同目录，16 个共享 case）把两侧
各自钉住，任何一侧单方面改语义都会显形：

- 后端断言：`travel-agent-python/tests/test_deeplink_parity.py`（`app.agent.places.map_search_url` / `map_directions_url`）
- 前端断言：`travel-frontend-vue/src/utils/deeplink.parity.test.ts`（`src/utils/geo.ts` 的 `externalMapLink` / `mapDirectionsUrl`）

断言粒度 = 协议 host + path 前缀 + 关键查询参数存在/缺席；`src`/`callnative`/`policy`/
`coordinate` 与坐标数值（GCJ-02 换算）等实现细节不整串相等。两侧期望不同（协议层）
的 case 在两个测试里都必须登记说明；期望相同的 case 不允许登记——保证本表不漏记、不过期。

## 差异清单

| # | 场景 | 后端（places.py） | 前端（geo.ts） | 定性 |
|---|------|-------------------|----------------|------|
| D1 | 国内搜索·有坐标 | `uri.amap.com/marker`，原始坐标直接打点 | `uri.amap.com/search` 关键词（顾虑 WGS84≠GCJ-02，拒绝坐标打点） | **待统一** |
| D2 | 越界坐标（200, -95） | 无范围校验：国界框判定落空 → 误判海外 → 谷歌关键词搜索 | 90/180 校验拒绝 → 回落关键词搜索 | **待统一** |
| D3 | 汉字名海外城市·无坐标（巴厘岛） | 城市名含汉字兜底 → 判国内 → 高德（**错误链接**） | 国内城市白名单 → 判海外 → 谷歌（正确） | **待统一**（判定策略相反的边界类：东京/巴厘岛/首尔等无坐标时后端会给出高德链接） |
| D4 | 海外搜索·有坐标 | `query=名称 城市`（不用坐标） | `query=lat,lng`（坐标定位） | 已知且接受（低于断言粒度；语义同为“在地图搜这个点”） |
| D5 | 高德路线·途经点数 | `via` 无上限（`;` 连接任意多个） | 限 1 个，超出返回 null（界面提示分段核实） | **待统一**（超出时两者产品行为不同：后端给超限链接 vs 前端拒绝） |
| D6 | 谷歌路线·途经点数 | `waypoints` 无上限 | 限 3 个（移动端浏览器），超出返回 null | 已知且接受（移动端限制是硬约束；后端链接偏桌面核实场景） |
| D7 | 0/0 哨兵坐标 | 判定阶段当真坐标 → 国界框落空 → 误判海外走谷歌；打点阶段又当无坐标（**后端内部两处不一致**） | 明确当无坐标 → 关键词搜索 | **待统一** |
| D8 | 高德路线坐标基准 | 直接传 WGS-84 原始坐标（高德按 GCJ-02 解释，有数百米偏移风险） | `toGcj02` 换算后传入 | **待统一** |
| D9 | 关键词拼接 | `名称 城市`（空格分隔） | `城市名称`（无分隔） | 已知且接受（实现细节） |
| D10 | 谷歌路线 origin/destination | 名称优先（无名称回落坐标） | 恒用坐标 | 已知且接受（实现细节） |

> 「待统一」需要用户拍板统一方向（涉及行为改动，本批次不修任何一侧）；
> 「已知且接受」记录在案即可。夜班会话推荐供参考：D3/D7 以前端口径（白名单 + 显式
> 哨兵处理）更接近正确；D8 前端换算更正确；D1/D2/D5 取决于产品想给“生成侧参考链接”
> 还是“出发前核实链接”定位。

## 两侧真实输出对照（2026-09-18 由临时 dump 脚本采集，两份 parity 测试为证）

| case | 后端输出 | 前端输出 |
|------|----------|----------|
| search_domestic_with_coords | `https://uri.amap.com/marker?position=120.15,30.24&name=%E8%A5%BF%E6%B9%96&src=travel-assistant&callnative=0` | `https://uri.amap.com/search?keyword=%E6%9D%AD%E5%B7%9E%E8%A5%BF%E6%B9%96` |
| search_domestic_no_coords | `https://uri.amap.com/search?keyword=%E5%A4%96%E6%BB%A9%20%E4%B8%8A%E6%B5%B7&src=travel-assistant&callnative=0` | `https://uri.amap.com/search?keyword=%E4%B8%8A%E6%B5%B7%E5%A4%96%E6%BB%A9` |
| search_foreign_with_coords | `https://www.google.com/maps/search/?api=1&query=Eiffel%20Tower%20Paris` | `https://www.google.com/maps/search/?api=1&query=48.8584%2C2.2945` |
| search_foreign_no_coords | `https://www.google.com/maps/search/?api=1&query=Times%20Square%20New%20York` | `https://www.google.com/maps/search/?api=1&query=New%20YorkTimes%20Square` |
| search_zero_sentinel | `https://www.google.com/maps/search/?api=1&query=...%20...`（谷歌，见 D7） | `https://uri.amap.com/search?keyword=%E6%9D%AD%E5%B7%9E%E6%96%AD%E6%A1%A5%E6%AE%8B%E9%9B%AA` |
| search_out_of_range_coords | `https://www.google.com/maps/search/?api=1&query=...%20...`（谷歌，见 D2） | `https://uri.amap.com/search?keyword=%E6%9D%AD%E5%B7%9E%E6%96%AD%E6%A1%A5` |
| search_hanzi_foreign_city_no_coords | `https://uri.amap.com/search?keyword=...&src=travel-assistant&callnative=0`（高德，见 D3） | `https://www.google.com/maps/search/?api=1&query=%E5%B7%B4%E5%8E%98%E5%B2%9B...`（谷歌） |
| route_domestic_two_stops | `https://uri.amap.com/navigation?from=120.15,30.24&to=120.0972,30.2407&mode=car&policy=1&src=travel-assistant&coordinate=gaode&callnative=0` | `https://uri.amap.com/navigation?from=120.1547...,30.2376...&to=120.1020...,30.2384...&mode=car&callnative=0`（GCJ-02，见 D8） |
| route_foreign_two_stops | `https://www.google.com/maps/dir/?api=1&origin=Eiffel%20Tower&destination=Louvre`（名称，见 D10） | `https://www.google.com/maps/dir/?api=1&origin=48.8584%2C2.2945&destination=48.8606%2C2.3376` |
| route_single_point | null | null |
| route_domestic_three_stops | amap navigation + `via=120.0972,30.2407` | amap navigation + `via=...`（GCJ-02） |
| route_domestic_four_stops | amap navigation + `via=...;...`（2 途经点，见 D5） | null（超 1 途经点） |
| route_foreign_five_stops | google dir + `waypoints=...%7C...%7C...`（3 途经点） | google dir + `waypoints=...%7C...%7C...`（3 途经点） |
| route_foreign_seven_stops | google dir + `waypoints=...`（5 途经点，见 D6） | null（超 3 途经点） |
| route_mixed_validity_stops | amap navigation，0/0 与缺坐标点被剔除（2 有效点，无 via） | 同左（无 via） |
| route_out_of_range_stop | amap navigation + `via=200,-95` 越界点照常纳入（见 D2） | amap navigation 无 via（越界点被剔除） |
