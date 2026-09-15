import { computed, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'

const MIN_SIDEBAR = 200
const MAX_SIDEBAR = 520
/** 无论面板拖多宽，地图保底这么宽（TREK 原文 MIN_MAP）。 */
const MIN_MAP = 360
/** 面板浮在走廊里的边距（TREK 面板 left/right:10）。 */
const PANEL_MARGIN = 10
const DEFAULT_LEFT = 340
const DEFAULT_RIGHT = 300
const STORAGE_LEFT = 'ta-panel-left'
const STORAGE_RIGHT = 'ta-panel-right'
/**
 * 两栏同屏会把地图压成一条缝的内容宽档（TREK 的 768–1023 窗口档等价物：
 * 我们左侧还有 84px 导航栏，所以量的是工作台自身宽度而不是 window）。
 */
const NARROW_WIDTH = 1024

function readStored(key: string, fallback: number): number {
  const value = Number.parseInt(localStorage.getItem(key) || '')
  return Number.isFinite(value) ? value : fallback
}

/**
 * 两栏宽度 / 折叠 / 拖拽（v2.7 §20 R1-R2，语义照抄 TREK `hooks/useResizablePanels.ts`）：
 * - 存储值只记「拖出来的宽」，展示值再按窄带夹紧——回宽屏复原，不丢用户设定；
 * - 折叠在宽屏是 leftCollapsed/rightCollapsed 意图态，窄带是独立的 narrowPanel（left|right|null=纯地图），
 *   两者互不污染：窄带里点开右栏不会改宽屏的折叠记忆。
 * - 拖拽在面板内缘 4px 热区，宽度按指针位移；左栏以工作台左缘 + 边距为原点（含 84px 导航栏偏移）。
 */
export function useResizablePanels(rootEl: Ref<HTMLElement | null>) {
  const leftWidth = ref(readStored(STORAGE_LEFT, DEFAULT_LEFT))
  const rightWidth = ref(readStored(STORAGE_RIGHT, DEFAULT_RIGHT))
  const leftCollapsed = ref(false)
  const rightCollapsed = ref(false)
  const narrow = ref(false)
  const narrowPanel = ref<'left' | 'right' | null>('left')
  const maxPanel = ref(Number.POSITIVE_INFINITY)
  const resizing = ref<'left' | 'right' | null>(null)

  function workbenchWidth(): number {
    return rootEl.value?.clientWidth ?? window.innerWidth
  }

  // 窄带判定与夹紧都只看工作台宽度：这是唯一夹得动的地方，其余档位不装 resize 监听
  function measure(): void {
    const width = workbenchWidth()
    narrow.value = width < NARROW_WIDTH
    maxPanel.value = narrow.value
      ? Math.max(MIN_SIDEBAR, width - MIN_MAP - 2 * PANEL_MARGIN)
      : Number.POSITIVE_INFINITY
  }

  function onMove(event: MouseEvent): void {
    if (!resizing.value) return
    const rect = rootEl.value?.getBoundingClientRect()
    if (!rect) return
    const raw =
      resizing.value === 'left'
        ? event.clientX - (rect.left + PANEL_MARGIN)
        : rect.right - PANEL_MARGIN - event.clientX
    const width = Math.max(MIN_SIDEBAR, Math.min(MAX_SIDEBAR, Math.round(raw)))
    if (resizing.value === 'left') {
      leftWidth.value = width
      localStorage.setItem(STORAGE_LEFT, String(width))
    } else {
      rightWidth.value = width
      localStorage.setItem(STORAGE_RIGHT, String(width))
    }
  }

  function onUp(): void {
    resizing.value = null
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }

  // 工作台是 v-if 挂载的（详情到达后才出现），onMounted 时 rootEl 可能还是 null——
  // 那种情况下 measure 只能退到 window 宽度，会漏掉「视口 1024–1108 但工作台 <1024」这一档。
  // 用 ResizeObserver + ref 监听补齐：元素一出现/一变宽就重测。
  let observer: ResizeObserver | null = null
  let stopWatchRoot: (() => void) | null = null

  onMounted(() => {
    measure()
    window.addEventListener('resize', measure)
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(() => measure())
      stopWatchRoot = watch(
        rootEl,
        (el) => {
          if (!el) return
          measure()
          observer?.observe(el)
        },
        { immediate: true },
      )
    }
  })

  onBeforeUnmount(() => {
    window.removeEventListener('resize', measure)
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    stopWatchRoot?.()
    observer?.disconnect()
  })

  function startResizeLeft(event: MouseEvent): void {
    event.preventDefault()
    resizing.value = 'left'
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }

  function startResizeRight(event: MouseEvent): void {
    event.preventDefault()
    resizing.value = 'right'
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }

  // 布局实际显示的：折叠意图态只在宽屏生效，窄带看 narrowPanel
  const leftHidden = computed(() => (narrow.value ? narrowPanel.value !== 'left' : leftCollapsed.value))
  const rightHidden = computed(() =>
    narrow.value ? narrowPanel.value !== 'right' : rightCollapsed.value,
  )

  function toggleLeft(): void {
    if (narrow.value) narrowPanel.value = narrowPanel.value === 'left' ? null : 'left'
    else leftCollapsed.value = !leftCollapsed.value
  }

  function toggleRight(): void {
    if (narrow.value) narrowPanel.value = narrowPanel.value === 'right' ? null : 'right'
    else rightCollapsed.value = !rightCollapsed.value
  }

  return {
    // 展示值夹紧、存储值不动（TREK 语义）：窄带拖窄的值回宽屏原样回来
    leftWidth: computed(() => Math.min(leftWidth.value, maxPanel.value)),
    rightWidth: computed(() => Math.min(rightWidth.value, maxPanel.value)),
    leftCollapsed,
    rightCollapsed,
    leftHidden,
    rightHidden,
    toggleLeft,
    toggleRight,
    narrow,
    resizing,
    startResizeLeft,
    startResizeRight,
  }
}
