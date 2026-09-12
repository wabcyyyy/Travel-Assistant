// echarts 按需注册集中模块（M4-④ §5.6）。
// 约定：全项目禁止 `import * as echarts from 'echarts'` 全量引入——
// 业务组件一律 import echarts from '<相对路径>/charts'；
// 新增图表类型或组件（如 title/dataZoom）时，先在下方 echarts.use([...]) 追加注册。
// 现有使用点：BudgetPanel（pie 饼图）、AdminTokensView（bar 堆叠 + line 折线，双 Y 轴）。
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

export default echarts

export type EChartsType = ReturnType<typeof echarts.init>

export function echartsUse(): void {}
