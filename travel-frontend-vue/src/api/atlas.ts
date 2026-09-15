import { requestGet } from './request'
import type { AtlasResponse } from '../types/atlas'

/** Atlas 行程图鉴（S3 后端；地图渲染在 S3 前端切片接入）。 */
export function getAtlas(scope?: 'all' | 'planned' | 'visited') {
  return requestGet<AtlasResponse>('/atlas', scope ? { params: { scope } } : undefined)
}
