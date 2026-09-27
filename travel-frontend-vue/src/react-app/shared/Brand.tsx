import { navigate } from '../router'

export function BrandMark() {
  return <span className="sinan-mark" aria-hidden="true"><i /><i /><i /></span>
}

export function Brand({ compact = false }: { compact?: boolean }) {
  return <button className={compact ? 'sinan-brand compact' : 'sinan-brand'} type="button" onClick={() => navigate('/')} aria-label="司南 Sinan 首页">
    <BrandMark />
    <span className="sinan-brand-copy"><strong>司南</strong><small>Sinan</small></span>
  </button>
}
