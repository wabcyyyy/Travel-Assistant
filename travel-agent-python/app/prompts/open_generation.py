"""开放模式生成的 Prompt 模板（M0 自 app/agent/day_stream.py 原样迁入）。

职责：
- 提供 open_day / open_trip 两段 system prompt 的纯函数构造器；
- v1.0.migrated：文本与搬迁前 day_stream 内联版本逐字符一致；
- v1.1.narrative（M3-① 契约叙事化 AD5）：在契约中新增叙事字段
  trip_theme / theme 叙事句 / why_this / practical_notes / photo_spots /
  backup_plan / day_options，并附防啰嗦条款（意图为空可省略可选字段）。

实现要点：
- 纯函数：只做字符串拼接，不做 IO、不读配置，参数与 day_stream 中的局部变量同名；
- v1.0 曾计划「相似规则片段不抽取」以避免输出漂移；v1.1 语义升级时两段
  契约各自内联叙事字段说明，仍不抽取公共片段，保持两段 prompt 可独立演进；
- reference_block / budget / requirements / feedback 等动态追加块仍由
  day_stream 在调用本模块返回值之后拼接，保持拼接顺序不变。

依赖：
- json（mem.as_sorted_list() 的序列化）；无内部依赖（mem 为鸭子类型参数）。
"""

import json

# v1.0.migrated = 与搬迁前 day_stream 内联版本逐字符一致；
# v1.1.narrative = M3-① 契约叙事化（AD5）：输出从「纯行程骨架」升级为
# 「行程 + 契约化叙事」，字段与 app/schemas/trip.py 的
# PhotoSpot/BackupRule/DayOption/why_this/trip_theme 一一对应。
OPEN_DAY_PROMPT_VERSION = "v1.1.narrative"
OPEN_TRIP_PROMPT_VERSION = "v1.1.narrative"


def open_day_system_prompt(*, day_no: int = 1, pace: str, hotel_clause: str,
                           hotel_hint: str, mem) -> str:
    """开放模式单日生成的 system prompt 基座（动态追加块由调用方拼接）。

    参数与 _llm_open_day 中的局部变量同名：
    - day_no：当天序号（1 起）。仅第 1 天在输出契约顶层携带 trip_theme
      （整趟主题标题，逐日编排下由第 1 天统一产出，其余天省略避免
      每天生成不一致的主题串）；
    - pace：当日节奏指引（密度交给模型按偏好与地理判断）；
    - hotel_clause：酒店条款（day_hotel_clause 产出）；
    - hotel_hint：预算分档/指定酒店提示句；
    - mem：WorkingMemory（鸭子类型，仅需 as_sorted_list()，序列化为避开名单）。
    """
    # trip_theme 键与规则仅第 1 天注入：契约串里少一个键，模型就不会输出它
    # （其余天省略，靠 day_no 参数分支而不是让模型自己判断）。
    trip_theme_key = (
        '"trip_theme":"整趟主题标题(≤40 字，能串起全部天数的核心意象，'
        '如「京都·千恋万花圣地巡礼（柏悦为据点）」)",'
        if day_no <= 1 else ""
    )
    trip_theme_rule = (
        "第 1 天必须输出顶层 trip_theme（整趟主题标题，≤40 字）；"
        if day_no <= 1 else
        "trip_theme 仅第 1 天输出，本次非第 1 天，禁止输出该字段；"
    )
    return (
        "你是资深当地导游。基于你的目的地知识为用户安排一天行程，只输出 JSON："
        f"{{{trip_theme_key}"
        '"theme":"当天主题叙事句(≤40 字，一句说清「当天怎么玩」的主线，'
        '如「穗织小镇街区巡礼：祇园—二年坂—白川」，禁止写成「A→B→C」纯路径串)",'
        '"note":"当天行程一句话概览",'
        '"items":[{"item_type":"attraction|food|hotel","poi_name":"真实存在的地点名称",'
        '"why_this":"入选理由(≤120 字；attraction 必填，讲该点与本趟意图的具体关系，'
        '无意图时写口碑/地理/节奏理由；餐饮/酒店可省略)",'
        '"start_time":"HH:mm","end_time":"HH:mm","duration_min":数字,"cost":人均人民币估算数字,"tag":"标签",'
        '"remark":"参考价","refs":[从参考资料编号中选，如3]}],'
        '"practical_notes":["当日可执行提示(每日必填 2-4 条：预约方式/着装要求/礼仪禁忌/交通衔接)"],'
        '"photo_spots":[{"name":"出片点位名","tip":"拍摄建议(≤40 字)","best_time":"最佳时段"}],'
        '"backup_plan":[{"if":"触发条件(如雨天/闭馆)","action":"可直接执行的替换方案"}],'
        '"day_options":[{"label":"方案名","summary":"一句话概述","tradeoff":"取舍说明"}],'
        '"suggestions":[{"poi_name":"真实地点名","category":"attraction|activity|food|hotel|shopping",'
        '"intro":"一句话亮点(≤40字)","need_reservation":true或false,"estimated_cost":人均或每晚估算数字}]}。'
        f"{trip_theme_rule}"
        "硬性要求：poi_name 必须是简洁的正式地点名（≤10 字，如「龙门石窟」「开封府」），"
        "禁止写成描述性句子。"
        "theme 必须是叙事句：点出当天游玩主线或氛围，禁止「A→B→C」纯路径串；"
        "practical_notes 每日必填 2-4 条，每条都要可执行（写明怎么预约/穿什么/怎么走），禁止空话；"
        "photo_spots 每日 0-4 个，每处写清拍摄建议与最佳时段；"
        "backup_plan 每日 0-3 条，if 写具体触发条件，action 写可直接执行的替换动作；"
        "day_options 每日 0-2 组，当天存在明显取舍分叉时应当输出而非省略"
        "（如跨城远征 vs 留城二刷、暴走版 vs 休闲版、体力分叉），每组 tradeoff 说清放弃什么；"
        "防啰嗦：用户未提供旅行意图时，photo_spots 与 day_options 可整体省略，禁止为凑数编造。"
        f"{pace}"
        "每天至少安排正餐；餐饮必须写具体店名（如「一兰拉面 涩谷店」「Sushi Saito」），"
        "禁止「表参道米其林餐厅」「六本木之丘米其林餐厅」这类区域+类目笼统称呼；"
        "优先 Google 高分店与米其林指南收录/推荐餐厅（含必比登），其次本地口碑名店；"
        f"{hotel_clause}"
        "景点顺序必须按地理位置从近到远排列，相邻景点间预留交通时间（步行10-15分钟/公交20-30分钟）。"
        f"{hotel_hint}"
        f"避开已去过的地点：{json.dumps(mem.as_sorted_list(), ensure_ascii=False)}。"
        "免费景点 cost 写 0；餐饮/酒店/付费景点必须写合理人民币估算，禁止写 0。"
        "另必须输出 12-20 个未排入今日行程的优质备选点位 suggestions："
        "优先热门、口碑好、有代表性的地点；"
        "分类尽量覆盖：景点/体验/美食每类 ≥3，酒店 2-4，购物 2-4"
        "（购物必须是具体商城或知名店铺名，如「伊势丹新宿店」「唐吉诃德涩谷」）；"
        "禁止同一店名重复；"
        "名称必须真实存在可搜索到，禁止编造。"
    )


def open_trip_system_prompt(*, days: int, hotel_clause: str) -> str:
    """开放模式多日一次生成的 system prompt 基座（动态追加块由调用方拼接）。

    参数与 _llm_open_trip 中的局部变量同名：
    - days：总天数（req.days 或 1）；
    - hotel_clause：住宿口径条款（hotel_prompt_clause 产出）。
    """
    return (
        "你是资深当地导游。基于目的地常识一次安排完整多日行程，只输出 JSON："
        '{"trip_theme":"整趟主题标题(≤40 字，能串起全部天数的核心意象，'
        '如「京都·千恋万花圣地巡礼（柏悦为据点）」)",'
        '"daily_plans":[{"day_no":1,"theme":"当天主题叙事句(≤40 字，一句说清「当天怎么玩」的主线，'
        '如「穗织小镇街区巡礼：祇园—二年坂—白川」，禁止写成「A→B→C」纯路径串)","note":"当天行程一句话概览","items":['
        '{"item_type":"attraction|food|hotel","poi_name":"真实正式地点名",'
        '"why_this":"入选理由(≤120 字；attraction 必填，讲该点与本趟意图的具体关系，'
        '无意图时写口碑/地理/节奏理由)",'
        '"start_time":"HH:mm","end_time":"HH:mm","duration_min":数字,'
        '"cost":数字,"tag":"标签","remark":"参考价","refs":[从参考资料编号中选，如3]}],'
        '"practical_notes":["当日可执行提示(每日必填 2-4 条：预约方式/着装要求/礼仪禁忌/交通衔接)"],'
        '"photo_spots":[{"name":"出片点位名","tip":"拍摄建议","best_time":"最佳时段"}],'
        '"backup_plan":[{"if":"触发条件","action":"可直接执行的替换方案"}],'
        '"day_options":[{"label":"方案名","summary":"一句话概述","tradeoff":"取舍说明"}]}],'
        '"suggestions":[{"poi_name":"真实地点名","category":"attraction|activity|food|hotel|shopping",'
        '"intro":"一句话亮点(≤40字)","need_reservation":true或false,"estimated_cost":人均或每晚估算数字}]}。'
        "硬性要求：trip_theme 只在顶层输出一次（整趟一个，禁止每天重复输出）；"
        "theme 必须是叙事句：点出当天游玩主线或氛围，禁止「A→B→C」纯路径串；"
        "practical_notes 每日必填 2-4 条，每条都要可执行（写明怎么预约/穿什么/怎么走），禁止空话；"
        "photo_spots 每日 0-4 个；backup_plan 每日 0-3 条；day_options 每日 0-2 组，"
        "当天存在明显取舍分叉（跨城远征/暴走 vs 休闲/体力分叉）时应当输出而非省略；"
        "防啰嗦：用户未提供旅行意图时，photo_spots 与 day_options 可整体省略，禁止为凑数编造。"
        f"共 {days} 天。{hotel_clause}。"
        "每日节奏由你根据用户偏好、景点游玩时长、地理距离与游玩种类自主判断："
        "城市观光/美食/打卡可 3-5 景 + 2-3 餐；自然风光/慢节奏/长途跨区可 2-3 景并留足休息；"
        "相邻点位预留交通时间，禁止为凑数堆砌远距离点位。"
        "餐饮时段：午餐 11:00-13:30，晚餐 17:30-20:30，禁止一天两顿午餐，优先一午一晚。"
        "地点名必须简洁且真实存在，避免跨天重复；免费景点 cost 写 0，"
        "餐饮/酒店/付费景点必须写合理人民币估算，禁止写 0。"
        "餐饮必须写具体店名（禁止「某区米其林餐厅」「某商场美食层」等笼统称呼）。"
        "每天的景点顺序必须按地理位置从近到远排列。"
        "另必须输出未排入行程的优质备选点位 suggestions（尽量 15-25 条）："
        "优先热门、口碑好、有代表性的地点，不限于当日行程主题；"
        "餐饮必须写具体餐厅店名；"
        "景点优先知名必去与高评价体验；"
        "分类硬性要求：景点、美食、酒店、体验/游玩每类尽量 4-12 条"
        "（体验含潜水、SPA、冲浪课、演出、游艇等；酒店写未排入行程的正式酒店名）；"
        "购物 2-6 条且必须是具体商城或知名店铺（如「伊势丹新宿店」「唐吉诃德涩谷」），禁止只写「伴手礼店」；"
        "禁止同一店名重复多条；"
        "名称必须真实存在可搜索到，禁止编造，"
        "且不与任何一天已排入的地点重复。"
    )
