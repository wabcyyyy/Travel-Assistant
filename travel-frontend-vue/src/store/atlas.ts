import { defineStore } from 'pinia'

import { getAtlas } from '../api/atlas'
import type { AtlasResponse } from '../types/atlas'

/**
 * Atlas 统计共享缓存（SPEC §7.3）：列表页页头 band 与首页 dashboard 复用同一份
 * stats/coverage——聚合不在 list VO 里塞，而是首屏并行请求一次后缓存。
 * 失败不抛给调用方：统计不可用时页面显示占位，不阻塞主内容。
 */
export const useAtlasStore = defineStore('atlas', {
  state: () => ({
    data: null as AtlasResponse | null,
    loaded: false,
    loading: false,
  }),
  actions: {
    async ensureLoaded(): Promise<AtlasResponse | null> {
      if (this.loaded) return this.data
      if (!this.loading) {
        this.loading = true
        try {
          const res = await getAtlas()
          this.data = res.data
          this.loaded = true
        } catch {
          /* 统计降级：不弹错，下次进入页面可重试 */
        } finally {
          this.loading = false
        }
      }
      return this.data
    },
  },
})
