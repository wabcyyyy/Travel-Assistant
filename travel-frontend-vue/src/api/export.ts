import axios from 'axios'
import { requestGet, requestPost } from './request'
import { useUserStore } from '../store/user'

/** 导出域：PDF 导出任务创建/查询/文件下载。 */

export interface ExportTaskInfo {
  id: number
  itineraryId: number
  taskType: string
  status: 'RUNNING' | 'DONE' | 'FAILED'
  errorMsg: string | null
  downloadUrl: string | null
  createdAt: string
  finishedAt: string | null
}

export function createPdfExport(itineraryId: number | string) {
  return requestPost<ExportTaskInfo>(`/export/pdf/${itineraryId}`)
}

export function getExportTask(taskId: number) {
  return requestGet<ExportTaskInfo>(`/export/tasks/${taskId}`)
}

/** 文件下载用独立实例：blob 响应 + 更短超时，凭据策略与主实例一致。 */
const downloadClient = axios.create({ baseURL: '/api', timeout: 60000, withCredentials: true })

downloadClient.interceptors.request.use((config) => {
  const memToken = useUserStore().token
  if (memToken) {
    config.headers.Authorization = `Bearer ${memToken}`
  }
  return config
})

export async function downloadExportFile(taskId: number): Promise<Blob> {
  const resp = await downloadClient.get(`/export/download/${taskId}`, { responseType: 'blob' })
  return resp.data as Blob
}
