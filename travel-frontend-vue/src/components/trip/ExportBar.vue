<template>
  <!-- 导出逻辑承载组件（M4-②a §5.4）：无自绘 UI。导出按钮位于 TripCoverHeader（保持视觉零变化），
       编排壳经模板引用调用 exportPdf / exportImage 并向其传递 exporting 状态。 -->
</template>

<script setup lang="ts">
import { ref } from 'vue'

import { createPdfExport, downloadExportFile, getExportTask } from '../../api/export'
import { useItineraryStore } from '../../store/itinerary'
import type { ItineraryStreamEvent } from '../../types/stream'
import { exportItineraryImage } from '../../utils/exportImage'

// 图片导出 + PDF 导出（createPdfExport / export_done 事件等待 / 轮询降级 / downloadPdf）原样迁出。
const props = defineProps<{
  /** 生成事件流是否已连接（决定 PDF 导出是否优先等待 export_done 事件） */
  streamConnected: boolean
  /** 事件订阅器（壳的生成事件流实例）：export_done 一次性等待挂在此通道上 */
  streamOn: (type: string, handler: (event: ItineraryStreamEvent) => void) => () => void
}>()

const emit = defineEmits<{
  download: [kind: 'pdf' | 'image']
}>()

const store = useItineraryStore()

const exportingPdf = ref(false)
const exportingImg = ref(false)

/** 等待 export_done 事件（仅当事件流已连接时使用）；超时返回 false 由调用方回退轮询。 */
function waitForExportDone(taskId: number, timeoutMs: number): Promise<boolean> {
  return new Promise((resolve) => {
    const off = props.streamOn('export_done', (event: ItineraryStreamEvent) => {
      if ((event.data as { taskId?: number } | undefined)?.taskId === taskId) {
        off()
        clearTimeout(timeoutId)
        resolve(true)
      }
    })
    const timeoutId = window.setTimeout(() => {
      off()
      resolve(false)
    }, timeoutMs)
  })
}

async function exportImage() {
  const detail = store.detail
  if (!detail) return
  exportingImg.value = true
  try {
    exportItineraryImage(detail)
    ElMessage.success('图片已导出')
    emit('download', 'image')
  } finally {
    exportingImg.value = false
  }
}

async function downloadPdf(taskId: number) {
  const blob = await downloadExportFile(taskId)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${store.detail!.title}.pdf`
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('PDF 导出完成')
  emit('download', 'pdf')
}

async function exportPdf() {
  const detail = store.detail
  if (!detail) return
  exportingPdf.value = true
  try {
    const res = await createPdfExport(detail.id)
    const taskId = res.data.id
    // 主路径：复用生成进度的事件连接收 export_done；未连接/超时回退轮询
    if (props.streamConnected) {
      const received = await waitForExportDone(taskId, 90_000)
      if (received) {
        await downloadPdf(taskId)
        return
      }
    }
    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 1500))
      const task = await getExportTask(taskId)
      if (task.data.status === 'DONE') {
        await downloadPdf(taskId)
        return
      }
      if (task.data.status === 'FAILED') {
        ElMessage.error(task.data.errorMsg || 'PDF 导出失败')
        return
      }
    }
    ElMessage.error('导出超时，请稍后在任务列表重试')
  } catch (e) {
    // 拦截器已提示
  } finally {
    exportingPdf.value = false
  }
}

defineExpose({ exportingPdf, exportingImg, exportPdf, exportImage })
</script>
