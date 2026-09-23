import { defineStore } from 'pinia'

/** 页内浮层状态：新建行程改走弹窗，不再跳独立 /generate 页。 */
export const useUiStore = defineStore('ui', {
  state: () => ({
    createTripOpen: false,
    createTripCity: '' as string,
  }),
  actions: {
    openCreateTrip(city = '') {
      this.createTripCity = city
      this.createTripOpen = true
    },
    closeCreateTrip() {
      this.createTripOpen = false
      this.createTripCity = ''
    },
  },
})
