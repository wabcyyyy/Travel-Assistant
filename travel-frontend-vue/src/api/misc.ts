import { requestGet } from './request'

/** 联调测试端点域。 */

export function getHello() {
  return requestGet<string>('/test/hello')
}

export function callAgent() {
  return requestGet<Record<string, unknown>>('/test/call-agent')
}
