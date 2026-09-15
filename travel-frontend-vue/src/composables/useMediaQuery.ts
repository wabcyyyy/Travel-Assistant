import { onBeforeUnmount, ref, type Ref } from 'vue'

/** 响应式媒体查询（v2.6 §19.3 三栏折叠）：非浏览器环境回落 false。 */
export function useMediaQuery(query: string): Ref<boolean> {
  const matches = ref(false)
  let mql: MediaQueryList | null = null

  const onChange = (event: MediaQueryListEvent): void => {
    matches.value = event.matches
  }

  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    mql = window.matchMedia(query)
    matches.value = mql.matches
    mql.addEventListener('change', onChange)
  }

  onBeforeUnmount(() => {
    mql?.removeEventListener('change', onChange)
  })

  return matches
}
