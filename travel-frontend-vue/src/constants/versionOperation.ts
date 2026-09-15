/**
 * 版本快照 operation → 中文标签（SPEC §7.4 / A5）。
 *
 * 已知值来自后端 create_snapshot 的**实际调用点**（13 种）；**未知值回落原文**——
 * DDL 注释与真实取值不同步（v2.3 E20 已证明），不允许硬编码白名单把新值吞成「快照」。
 */
const OPERATION_LABELS: Record<string, string> = {
  create: '创建行程',
  generate: '生成完成',
  add_item: '新增点位',
  update_item: '编辑点位',
  move_item: '跨天移动',
  delete_item: '删除点位',
  reorder: '调整顺序',
  nl_edit: '自然语言编辑',
  delete: '删除行程',
  apply_plans: '应用方案',
  apply_hotel: '替换酒店',
  snapshot: '手动快照',
  restore: '回滚恢复',
  optimize: '优化路线',
  update_day: '编辑日标题',
}

export function versionOperationLabel(operation: string | null | undefined): string {
  const op = (operation ?? '').trim()
  return OPERATION_LABELS[op] ?? (op || '快照')
}
