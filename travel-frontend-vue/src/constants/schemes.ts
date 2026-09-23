/**
 * scheme 元数据（SPEC v2.3 §7.1.3）：**只有 id 与 swatch 预览色**。
 * 真实色值在 theme.css 的 [data-scheme] / .dark 令牌块——scheme 是数据，
 * 组件只消费这里的 id（镜像 TREK 的「scheme is data」契约）。
 */
import type { SchemeId } from '../styles/appearance'

export interface SchemeMeta {
  id: SchemeId
  swatch: { light: string; dark: string }
}

// default 走「黑白灰」（v2.7 §20 R4，TREK 默认 swatch #111827 / #e4e4e7）；
// 彩色 scheme 只覆盖 accent 家族（TREK 2.5），天色相随锚点整体平移
export const SCHEMES: readonly SchemeMeta[] = [
  { id: 'default', swatch: { light: '#111827', dark: '#e4e4e7' } },
  { id: 'teal', swatch: { light: '#0f766e', dark: '#2dd4bf' } },
  { id: 'indigo', swatch: { light: '#4f46e5', dark: '#818cf8' } },
  { id: 'violet', swatch: { light: '#7c3aed', dark: '#a78bfa' } },
  { id: 'rose', swatch: { light: '#e11d48', dark: '#fb7185' } },
  { id: 'amber', swatch: { light: '#d97706', dark: '#fbbf24' } },
  { id: 'contrast', swatch: { light: '#155e75', dark: '#67e8f9' } },
]
