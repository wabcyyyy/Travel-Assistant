import { useEffect } from 'react'
import type { GenerateInput } from '../../api/sinan'
import { navigate } from '../router'
import { ChatIntake } from './ChatIntake'
import { TripPreview } from './TripPreview'
import { useHomePlanning } from './useHomePlanning'

/** 创建区组合：左对话、右实时预览（窄屏上下堆叠）；生成完成跳详情页继续编排。 */
export function HomeStudio({ query }: { query: URLSearchParams }) {
  const planning = useHomePlanning()

  useEffect(() => {
    if (planning.status !== 'ready' || !planning.draft) return
    const timer = window.setTimeout(() => navigate(`/trips/${planning.draft!.id}`), 900)
    return () => window.clearTimeout(timer)
  }, [planning.status, planning.draft])

  return <div className="home-studio" id="planning">
    <ChatIntake query={query} disabled={planning.busy} onStart={(input: GenerateInput) => void planning.submit(input)} />
    <TripPreview planning={planning} />
  </div>
}
