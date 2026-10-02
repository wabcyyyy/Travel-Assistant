import { navigate } from '../router'

/**
 * 品牌标「S 路线」：司南 Sinan 的首字母 S，同时是一条弯向终点的路线——
 * 一条墨色 S 线，顶端一枚朱砂点标出「下一站」。纯几何（线+点），
 * 不描摹任何实物；favicon.svg 与 PWA 图标是同一几何的白描版（红底白线+镂空点）。
 */
export function BrandMark() {
  return (
    <span className="sinan-mark" aria-hidden="true">
      <svg viewBox="0 0 64 64" role="presentation" focusable="false">
        <g transform="rotate(6 32 32)">
          <path
            d="M41 18 C37 12.5 26 12.5 22.5 18.5 C19 24.5 25.5 28 32 32 C38.5 36 45 39.5 41.5 46 C38 52 27 52 23 46"
            fill="none"
            stroke="var(--sinan-ink)"
            strokeWidth="7.5"
            strokeLinecap="round"
          />
          <circle cx="47.5" cy="10.5" r="5" fill="var(--sinan-accent)" />
        </g>
      </svg>
    </span>
  )
}

export function Brand({ compact = false }: { compact?: boolean }) {
  return <button className={compact ? 'sinan-brand compact' : 'sinan-brand'} type="button" onClick={() => navigate('/')} aria-label="司南 Sinan 首页">
    <BrandMark />
    <span className="sinan-brand-copy"><strong>司南</strong><small>Sinan</small></span>
  </button>
}
