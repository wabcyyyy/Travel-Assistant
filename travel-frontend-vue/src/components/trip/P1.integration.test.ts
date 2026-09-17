import { mount, shallowMount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'
import DayListCard from './DayListCard.vue'
import HeadStatusPanel from './HeadStatusPanel.vue'
import GenerateView from '../../views/GenerateView.vue'
import VerificationNotice from './VerificationNotice.vue'
import EvidenceBadge from './EvidenceBadge.vue'
import { useItineraryStore } from '../../store/itinerary'
import type { DayPlan, ItineraryDetail } from '../../types/itinerary'

vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ query: {} }),
}))

function setup(city = '东京') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useItineraryStore()
  const detail = { id: 1, city, status: 2, days: 1, dayList: [], budgetList: [] } as unknown as ItineraryDetail
  store.setDetail(detail)
  return { pinia, store, detail }
}
const makeDay = (count: number): DayPlan => ({ dayId: 1, dayNo: 1, items: Array.from({ length: count }, (_, i) => ({
  id: i + 1, itemType: 'attraction', poiName: `点${i}`, latitude: 35 + i / 100, longitude: 139,
})) } as DayPlan)

describe('P1 集成', () => {
  it('日卡显示路线且点击不折叠；超上限不生成假全天路线', async () => {
    const { pinia, store } = setup()
    const wrapper = shallowMount(DayListCard, { props: { day: makeDay(3), streamState: store.streamState,
      collapsed: false, highlightId: null, selectedIds: [] }, global: { plugins: [pinia] } })
    const link = wrapper.get('a.diy-tool')
    expect(link.text()).toContain('全天路线')
    expect(new URL(link.attributes('href')!).searchParams.get('waypoints')).toBe('35.01,139')
    await link.trigger('click')
    expect(wrapper.emitted('toggle')).toBeUndefined()
    await wrapper.setProps({ day: makeDay(6) })
    expect(wrapper.find('a.diy-tool').exists()).toBe(false)
    expect(wrapper.text()).toContain('超出地图途经点上限')
    await wrapper.setProps({ day: makeDay(1) })
    expect(wrapper.find('a.diy-tool').exists()).toBe(false)
    wrapper.unmount()
  })
  it('完成后的头部渲染真实核实说明组件', () => {
    const { detail, store } = setup()
    const wrapper = shallowMount(HeadStatusPanel, { props: { detail, doneDays: 1, streamState: store.streamState },
      global: { stubs: { VerificationNotice: false } } })
    expect(wrapper.findComponent(VerificationNotice).exists()).toBe(true)
    expect(wrapper.text()).toContain('营业时间待核实')
    wrapper.unmount()
  })
  it('生成页提交区渲染核实说明而不只注册组件', () => {
    const { pinia } = setup()
    const wrapper = shallowMount(GenerateView, { global: { plugins: [pinia], renderStubDefaultSlot: true,
      stubs: { VerificationNotice: false } } })
    expect(wrapper.findComponent(VerificationNotice).exists()).toBe(true)
    expect(wrapper.text()).toContain('费用为参考估算')
    wrapper.unmount()
  })
  it('徽标展示来源边界并支持无证据旧行程', async () => {
    const wrapper = mount(EvidenceBadge, { props: { item: { itemType: 'food', poiName: '餐厅', valueKind: 'observed' } } })
    expect(wrapper.text()).toBe('地点有来源')
    expect(wrapper.attributes('title')).toContain('不代表票价或营业时间已核实')
    await wrapper.setProps({ item: { itemType: 'food', poiName: '餐厅' } })
    expect(wrapper.find('span').exists()).toBe(false)
  })
})
