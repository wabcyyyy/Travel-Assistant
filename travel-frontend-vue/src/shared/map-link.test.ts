import { describe, expect, it } from 'vitest'
import { safeMapLink } from './map-link'

describe('外部地图深链白名单', () => {
  it('放行后端 map_link 的两个出口', () => {
    expect(safeMapLink('https://uri.amap.com/marker?position=120.1,30.2&name=x')).toContain('uri.amap.com')
    expect(safeMapLink('https://www.google.com/maps/search/?api=1&query=Tokyo')).toContain('google.com/maps')
  })
  it('拒绝非白名单主机、非 https 与垃圾输入', () => {
    expect(safeMapLink('https://evil.example.com/maps?x=1')).toBe('')
    expect(safeMapLink('http://uri.amap.com/marker?position=1,2')).toBe('')
    expect(safeMapLink('javascript:alert(1)')).toBe('')
    expect(safeMapLink('not a url')).toBe('')
    expect(safeMapLink(null)).toBe('')
  })
  it('谷歌主机只放行 /maps 路径', () => {
    expect(safeMapLink('https://www.google.com/search?q=hotel')).toBe('')
    expect(safeMapLink('https://google.com/maps/place/x')).toContain('google.com/maps')
  })
})