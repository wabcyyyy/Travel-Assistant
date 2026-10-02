/** 语音输入的纯函数层（确定性与单测）：浏览器特性检测 + 底稿/识别文本的增量合并。
 * Web Speech API 的构造器与事件类型 lib.dom 未收编，最小声明在 useSpeechInput.ts。 */

type SpeechCapableWindow = Window & { SpeechRecognition?: unknown; webkitSpeechRecognition?: unknown }

/** 浏览器是否带 Web Speech 识别实现（Chrome/Edge/Safari 可用）。
 * Firefox 等不支持的环境返回 false——麦克风按钮整个不渲染，降级路径就是打字。 */
export function speechSupported(win: Window = window): boolean {
  const w = win as SpeechCapableWindow
  return Boolean(w.SpeechRecognition || w.webkitSpeechRecognition)
}

/** ASCII 词元相接需要空格隔开；中文转写之间直接拼接（zh-CN 转写本身不带空格）。 */
function needsSpaceBetween(left: string, right: string): boolean {
  return /[A-Za-z0-9]$/.test(left) && /^[A-Za-z0-9]/.test(right)
}

/** 底稿 + 进行中转写（interim）+ 已定稿转写（final）→ 输入框应显示的完整文本。
 * base 是按下麦克风那一刻的底稿（识别期间不变）；final 是已定稿段的累计追加；
 * interim 是当前未定稿片段，每次识别事件**整体替换**而不是追加。空段不参与拼接，
 * 段间衔接按词元补空格（转写自带的首尾空格会被裁掉，不能靠原文空格）。 */
export function mergeTranscript(base: string, interim: string, final: string): string {
  const head = base.trimEnd()
  const finalPart = final.trim()
  const interimPart = interim.trim()
  let spoken = finalPart
  if (interimPart) {
    spoken = spoken ? spoken + (needsSpaceBetween(spoken, interimPart) ? ' ' : '') + interimPart : interimPart
  }
  if (!head) return spoken
  if (!spoken) return base
  return head + (needsSpaceBetween(head, spoken) ? ' ' : '') + spoken
}
