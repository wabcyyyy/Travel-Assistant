import { describe, expect, it } from 'vitest'
import { externalMapLink, hasValidCoordinates, mapDirectionsUrl } from './geo'
import { toGcj02 } from './coordinates'

const stop = (latitude = 35, longitude = 139) => ({ name: '寺 & 庭', latitude, longitude })

describe('地图核实', () => {
  it.each([
    { latitude: null, longitude: 10 }, { latitude: 10, longitude: undefined },
    { latitude: NaN, longitude: 10 }, { latitude: 10, longitude: Infinity },
    { latitude: 91, longitude: 10 }, { latitude: 10, longitude: -181 },
    { latitude: 0, longitude: 0 },
  ])('无效坐标按名称搜索 %j', (coordinates) => {
    expect(hasValidCoordinates(coordinates)).toBe(false)
    expect(new URL(externalMapLink({ name: '寺 & 庭', ...coordinates }, '东京')).searchParams.get('query')).toBe('东京寺 & 庭')
  })
  it('海外坐标和国内名称保持各自口径', () => {
    expect(new URL(externalMapLink(stop(), '东京')).searchParams.get('query')).toBe('35,139')
    const domestic = new URL(externalMapLink(stop(30, 120), '杭州'))
    expect(domestic.hostname).toBe('uri.amap.com')
    expect(domestic.searchParams.get('keyword')).toBe('杭州寺 & 庭')
    expect(hasValidCoordinates(stop(0, 120))).toBe(true)
  })
})

describe('当日路线', () => {
  it('少于两个有效点无路线', () => {
    expect(mapDirectionsUrl([], '东京')).toBeNull()
    expect(mapDirectionsUrl([stop(), stop(0, 0)], '东京')).toBeNull()
  })
  it('海外保序且不把非法点加入路线', () => {
    const url = new URL(mapDirectionsUrl([stop(35, 139), stop(0, 0), stop(36, 140), stop(37, 141)], '东京')!)
    expect(url.searchParams.get('origin')).toBe('35,139')
    expect(url.searchParams.get('waypoints')).toBe('36,140')
    expect(url.searchParams.get('destination')).toBe('37,141')
  })
  it('高德最多一个途经点且转换 WGS84', () => {
    const url = new URL(mapDirectionsUrl([stop(39.9, 116.4), stop(39.91, 116.41), stop(39.92, 116.42)], '北京')!)
    const [lat, lon] = toGcj02(39.9, 116.4)
    expect(url.hostname).toBe('uri.amap.com')
    expect(url.searchParams.get('from')).toBe(`${lon},${lat}`)
    expect(url.searchParams.has('via')).toBe(true)
    expect(url.searchParams.has('coordinate')).toBe(false)
    expect(lat).toBeCloseTo(39.90140353, 6)
    expect(lon).toBeCloseTo(116.40624278, 6)
    expect(toGcj02(35, 139)).toEqual([35, 139])
  })
  it('超地图限制不静默丢弃途经点', () => {
    expect(mapDirectionsUrl(Array.from({ length: 4 }, () => stop(30, 120)), '杭州')).toBeNull()
    expect(mapDirectionsUrl(Array.from({ length: 6 }, () => stop()), '东京')).toBeNull()
    expect(mapDirectionsUrl(Array.from({ length: 5 }, () => stop()), '东京')).not.toBeNull()
  })
})
