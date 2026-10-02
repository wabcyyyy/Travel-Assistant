import { useRef } from 'react'
import type { ChangeEvent } from 'react'
import { isOfflineError, isUnauthorized, ReactApiError } from '../../api/sinan'
import { Icon } from './Icon'
import { useSpeechInput } from './useSpeechInput'

/** 对话输入共用件：ChatIntake（首页）与 ChatPanel（详情）的 composer 结构同构，
 * 各自的 className/maxLength/placeholder/locked 语义经 props 保留。
 * 麦克风（浏览器不支持 Web Speech 时整个不渲染）与图片按钮长在这里；
 * 文本提交仍是受控 input + form onSubmit——两个入口的 clarify/chat-edit 语义不变。 */

const IMAGE_MAX_BYTES = 5 * 1024 * 1024
const IMAGE_ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp']

export function ChatComposer({
  value,
  onChange,
  onSend,
  placeholder,
  ariaLabel,
  maxLength,
  className,
  disabled = false,
  onImage,
  imageBusy = false,
  onNotice,
}: {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  placeholder: string
  ariaLabel: string
  maxLength: number
  className: string
  disabled?: boolean
  /** 拿到已通过本地预检（类型/大小）的图片文件；上传与失败反馈由调用方经各自提示通道处理 */
  onImage?: (file: File) => void
  /** 图片识别进行中：图片按钮出 loading 态并禁用 */
  imageBusy?: boolean
  /** 本地预检失败（类型不符/超 5MB）的就地提示，调用方接到自己现有的提示通道 */
  onNotice?: (message: string) => void
}) {
  const fileRef = useRef<HTMLInputElement | null>(null)
  const speech = useSpeechInput({ getBase: () => value, onResult: onChange })
  const locked = disabled || imageBusy

  const onFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    // 清空选择值：同一张图（识别失败后重选）也要能再次触发 onChange
    event.target.value = ''
    if (!file) return
    if (!IMAGE_ACCEPTED_TYPES.includes(file.type)) {
      onNotice?.('只支持 JPG / PNG / WebP 图片。')
      return
    }
    if (file.size > IMAGE_MAX_BYTES) {
      onNotice?.('图片超过 5MB 了，换一张小一点的试试。')
      return
    }
    onImage?.(file)
  }

  return (
    <>
      <form
        className={className}
        onSubmit={(event) => {
          event.preventDefault()
          // 文本已发出，输入框即将清空：丢弃识别会话，迟到的定稿回填不该把旧底稿写回来
          speech.cancel()
          if (!disabled) onSend()
        }}
      >
        <input
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          aria-label={ariaLabel}
          maxLength={maxLength}
          disabled={disabled || speech.listening}
        />
        {speech.supported && (
          <button
            type="button"
            className={speech.listening ? 'composer-mic is-listening' : 'composer-mic'}
            aria-label={speech.listening ? '停止语音输入' : '语音输入'}
            aria-pressed={speech.listening}
            disabled={disabled}
            onClick={speech.toggle}
          >
            <Icon name="mic" size={16} />
          </button>
        )}
        {onImage && (
          <>
            <input ref={fileRef} type="file" hidden accept="image/jpeg,image/png,image/webp" onChange={onFileChange} />
            <button
              type="button"
              className={imageBusy ? 'composer-image is-busy' : 'composer-image'}
              aria-label={imageBusy ? '正在识别图片' : '识别图片'}
              disabled={locked || speech.listening}
              onClick={() => fileRef.current?.click()}
            >
              <Icon name="image" size={16} />
            </button>
          </>
        )}
        <button type="submit" className="button button-primary" disabled={disabled || !value.trim()}>
          发送<Icon name="arrow" size={15} />
        </button>
      </form>
      {speech.error
        ? <p className="composer-note" role="alert">{speech.error}</p>
        : speech.listening && <p className="composer-note" role="status">正在听你说，说完再点一下麦克风。</p>}
    </>
  )
}

/** 把图片识别出的建议消息并进当前底稿：空底稿直接采用，非空以空格相接，超长截断。
 * 回填不自动发送——用户编辑后照常走原提交流程。 */
export function composeDraft(base: string, suggestion: string, maxLength: number): string {
  const head = base.trim()
  const add = suggestion.trim()
  if (!add) return base
  if (!head) return add.slice(0, maxLength)
  return `${head} ${add}`.slice(0, maxLength)
}

/** 图片识别失败的统一文案：401 给登录引导、413 给换图指引、离线给重试提示，
 * 其余透传后端 message（后端异常文案本身已脱敏）。 */
export function imageFeedbackText(error: unknown): string {
  if (isUnauthorized(error)) return '登录后才能识别图片。'
  if (error instanceof ReactApiError && error.status === 413) return '图片太大了，换一张 5MB 以内的试试。'
  if (isOfflineError(error)) return '暂时连不上识别服务，稍后再试。'
  return error instanceof Error && error.message ? error.message : '这张图没能识别出来，换一张试试。'
}
