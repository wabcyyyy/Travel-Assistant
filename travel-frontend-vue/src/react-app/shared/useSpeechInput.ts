import { useCallback, useEffect, useRef, useState } from 'react'
import { mergeTranscript, speechSupported } from './speechText'

/** lib.dom 未收编 SpeechRecognition：本地最小结构声明（只列用到的成员）。 */

interface SpeechAlternativeLike {
  transcript: string
}

interface SpeechResultLike {
  readonly length: number
  readonly isFinal: boolean
  [index: number]: SpeechAlternativeLike
}

interface SpeechResultListLike {
  readonly length: number
  [index: number]: SpeechResultLike
}

interface SpeechRecognitionEventLike {
  readonly resultIndex: number
  readonly results: SpeechResultListLike
}

interface SpeechRecognitionErrorEventLike {
  readonly error: string
}

interface SpeechRecognitionLike {
  lang: string
  continuous: boolean
  interimResults: boolean
  start(): void
  stop(): void
  abort(): void
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null
  onend: (() => void) | null
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike

function recognitionCtor(win: Window): SpeechRecognitionCtor | null {
  const w = win as Window & { SpeechRecognition?: SpeechRecognitionCtor; webkitSpeechRecognition?: SpeechRecognitionCtor }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

const SPEECH_ERROR_TEXT: Record<string, string> = {
  'not-allowed': '麦克风权限被拒绝了，请在浏览器设置里允许后重试。',
  'service-not-allowed': '语音服务被浏览器拒绝了，请检查麦克风权限。',
  'no-speech': '没听到内容，再点一次试试。',
  'network': '语音服务暂时连不上，稍后再试。',
  'audio-capture': '没有找到可用的麦克风设备。',
  'language-not-supported': '当前浏览器不支持中文语音识别。',
}

export interface SpeechInputOptions {
  /** 按下麦克风那一刻的输入框底稿（识别期间作为合并基线，不随打字变化） */
  getBase: () => string
  /** 识别期间持续回调：参数是应显示的完整文本（底稿 + 转写），实时上屏 */
  onResult: (text: string) => void
}

/** Web Speech 语音输入 hook：zh-CN + interimResults + 单击单句模式（continuous=false），
 * 单击开始、再击停止；识别结束/失败自动复位。文本经 speechText.mergeTranscript 增量回填。
 * 浏览器不支持时 supported=false，调用方据此不渲染麦克风按钮。 */
export function useSpeechInput({ getBase, onResult }: SpeechInputOptions) {
  const [listening, setListening] = useState(false)
  const [error, setError] = useState('')
  const recRef = useRef<SpeechRecognitionLike | null>(null)
  const baseRef = useRef('')
  const finalRef = useRef('')
  const committedRef = useRef(-1)
  const discardRef = useRef(false)
  // 回调走 ref：识别会话横跨多次渲染，事件闭包必须总是拿到最新的回调
  const getBaseRef = useRef(getBase)
  const onResultRef = useRef(onResult)
  getBaseRef.current = getBase
  onResultRef.current = onResult

  const emitFinal = useCallback(() => {
    onResultRef.current(mergeTranscript(baseRef.current, '', finalRef.current))
  }, [])

  const stop = useCallback(() => {
    try {
      recRef.current?.stop()
    } catch {
      // 未在识别态调 stop 会抛 InvalidStateError：静默即可
    }
  }, [])

  /** 丢弃本次识别并掐断会话：用于「识别途中用户已把文本发出去」——收尾的定稿回填
   * 会把刚清空的输入框写回旧底稿，必须跳过。 */
  const cancel = useCallback(() => {
    discardRef.current = true
    try {
      recRef.current?.abort()
    } catch {
      // 同上：静默
    }
  }, [])

  const toggle = useCallback(() => {
    if (recRef.current) {
      stop()
      return
    }
    const Ctor = recognitionCtor(window)
    if (!Ctor) return
    const rec = new Ctor()
    rec.lang = 'zh-CN'
    rec.continuous = false
    rec.interimResults = true
    baseRef.current = getBaseRef.current()
    finalRef.current = ''
    committedRef.current = -1
    discardRef.current = false
    rec.onresult = (event) => {
      let interim = ''
      for (let i = 0; i < event.results.length; i += 1) {
        const result = event.results[i]
        if (result.isFinal) {
          // results 只增不改写：按索引去重，已累计的定稿段不重复追加
          if (i > committedRef.current) {
            finalRef.current += result[0]?.transcript ?? ''
            committedRef.current = i
          }
        } else {
          interim += result[0]?.transcript ?? ''
        }
      }
      onResultRef.current(mergeTranscript(baseRef.current, interim, finalRef.current))
    }
    rec.onerror = (event) => {
      // aborted 是主动停止/取消的伴生事件，不算失败
      if (event.error !== 'aborted') setError(SPEECH_ERROR_TEXT[event.error] ?? '语音识别失败了，请再试一次。')
    }
    rec.onend = () => {
      recRef.current = null
      setListening(false)
      if (!discardRef.current) emitFinal()
    }
    recRef.current = rec
    setError('')
    try {
      rec.start()
      setListening(true)
    } catch {
      recRef.current = null
      setError('语音识别没能启动，请再点一次试试。')
    }
  }, [stop, emitFinal])

  // 卸载时掐掉在途识别；discard 让迟到的 onend 不再回填
  useEffect(
    () => () => {
      discardRef.current = true
      try {
        recRef.current?.abort()
      } catch {
        // 静默
      }
    },
    [],
  )

  return { supported: speechSupported(), listening, error, toggle, stop, cancel }
}

export type SpeechInput = ReturnType<typeof useSpeechInput>
