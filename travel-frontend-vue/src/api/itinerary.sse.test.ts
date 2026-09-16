/**
 * SSE 帧解析与 chat 编辑流的健壮性用例（P1-4）：
 * - parseSseFrame：心跳帧 / 脏帧 / 合法帧的判定（脏帧不抛异常）；
 * - chatEditStreamItinerary：脏帧被跳过且不中断流，error 事件仍向上抛。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'

// api → request 链路会引入 router（其 import 图含 views/element-plus，单测无需）：
// mock 掉 router 让本文件只加载被测的纯逻辑模块。
vi.mock('../router', () => ({
  default: {
    currentRoute: { value: { path: '/', name: 'home' } },
    push: vi.fn(),
  },
}))

import { chatEditStreamItinerary, parseSseFrame } from './itinerary'

function streamFrom(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
}

describe('parseSseFrame', () => {
  it('无 data 行（心跳/注释帧）判为 empty', () => {
    expect(parseSseFrame(': keep-alive')).toEqual({ kind: 'empty' })
    expect(parseSseFrame('event: ping')).toEqual({ kind: 'empty' })
  })

  it('非法 JSON 判为 dirty，而不是抛异常', () => {
    expect(parseSseFrame('data: {not-json').kind).toBe('dirty')
    expect(parseSseFrame('data: {"type":"x"').kind).toBe('dirty')
  })

  it('合法帧返回信封', () => {
    const parsed = parseSseFrame('data: {"type":"chat_token","data":{"delta":"你好"}}')
    expect(parsed).toEqual({
      kind: 'envelope',
      envelope: { type: 'chat_token', data: { delta: '你好' } },
    })
  })

  it('多行 data 按 SSE 规则以换行拼接', () => {
    const parsed = parseSseFrame('data: {"type":"chat_token",\ndata: "data":{"delta":"A"}}')
    expect(parsed.kind).toBe('envelope')
    if (parsed.kind === 'envelope') {
      expect(parsed.envelope.data).toEqual({ delta: 'A' })
    }
  })
})

describe('chatEditStreamItinerary', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('脏帧被跳过且不中断流（后续合法帧照常生效）', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            streamFrom([
              'data: {"type":"chat_token","data":{"delta":"A"}}\n\n',
              'data: {broken-frame\n\n',
              'data: {"type":"chat_token","data":{"delta":"B"}}\n\n',
              'data: {"type":"chat_done"}\n\n',
            ]),
            { status: 200 },
          ),
      ),
    )
    const tokens: string[] = []
    await chatEditStreamItinerary(1, { message: 'hi', history: [] }, {
      onToken: (delta) => tokens.push(delta),
    })
    expect(tokens).toEqual(['A', 'B'])
    expect(warn).toHaveBeenCalledTimes(1)
    expect(String(warn.mock.calls[0][0])).toContain('1 个无法解析的 SSE 帧')
  })

  it('error 事件仍向上抛（调用方回退阻塞端点）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            streamFrom(['data: {"type":"error","data":{"message":"生成失败"}}\n\n']),
            { status: 200 },
          ),
      ),
    )
    await expect(
      chatEditStreamItinerary(1, { message: 'hi', history: [] }, {}),
    ).rejects.toThrow('生成失败')
  })

  it('HTTP 不可用时抛出连接错误', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 503 })))
    await expect(
      chatEditStreamItinerary(1, { message: 'hi', history: [] }, {}),
    ).rejects.toThrow('流式连接不可用')
  })
})

// ---------- 幂等键（X-Idempotency-Key） ----------

import { newIdempotencyKey } from './itinerary'

describe('newIdempotencyKey', () => {
  it('返回非空字符串', () => {
    expect(newIdempotencyKey()).toBeTruthy()
    expect(typeof newIdempotencyKey()).toBe('string')
  })

  it('两次调用生成不同的键（同键 = 同一次操作，键必须唯一）', () => {
    const seen = new Set(Array.from({ length: 50 }, () => newIdempotencyKey()))
    expect(seen.size).toBe(50)
  })
})
