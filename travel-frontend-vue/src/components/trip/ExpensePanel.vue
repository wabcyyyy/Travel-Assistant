<template>
  <section class="expense-panel" aria-label="实际花费">
    <header><h3>实际花费</h3><button v-if="readOnly !== true" type="button" :disabled="busy" @click="edit()">记一笔</button></header>
    <p v-if="error" role="alert">{{ error }} <button type="button" @click="load">重试</button></p>
    <p v-if="loading">正在读取账目…</p>
    <template v-else>
      <p v-if="!ledger.expenses.length">还没有账目，记下旅途中的第一笔花费。</p>
      <ul class="totals">
        <li v-for="total in ledger.totals" :key="`${total.currency}-${total.category}`" :class="{ over: isOver(total) }">
          {{ labels[total.category] || total.category }}：{{ total.currency }} {{ total.amount }}
          <span v-if="total.currency === 'CNY'"> / 预估 ¥{{ estimate(total.category).toFixed(2) }}</span>
          <span v-else>（不与人民币预算换算）</span>
        </li>
      </ul>
      <article v-for="expense in ledger.expenses" :key="expense.id" class="expense-row">
        <div><strong>{{ labels[expense.category] || expense.category }} · {{ expense.currency }} {{ expense.amount }}</strong>
          <p>{{ expense.spentAt || '日期未填' }}<template v-if="expense.dayNo"> · 第 {{ expense.dayNo }} 天</template><template v-if="expense.paymentMethod"> · {{ expense.paymentMethod }}</template></p>
          <p v-if="expense.note">{{ expense.note }}</p>
          <button v-if="linkedItem(expense.itemId)" type="button" @click="emit('select-item', expense.itemId!)">{{ linkedItem(expense.itemId)?.poiName }}</button>
          <span v-else-if="expense.itemId">关联点位已移除</span>
        </div>
        <div v-if="readOnly !== true" class="actions"><button type="button" :disabled="busy" @click="edit(expense)">编辑</button><button type="button" :disabled="busy" @click="remove(expense)">删除</button></div>
      </article>
    </template>
    <AppDialog v-model="dialog" :title="editingId ? '修改账目' : '记一笔'" width="min(440px, calc(100vw - 24px))">
      <form class="expense-form" @submit.prevent="save">
        <label>类目<select v-model="draft.category"><option v-for="(label, value) in labels" :key="value" :value="value">{{ label }}</option></select></label>
        <label>金额<input v-model="amount" inputmode="decimal" required pattern="[0-9]+(\.[0-9]{1,2})?" placeholder="0.00" /></label>
        <label>币种<input v-model="draft.currency" required pattern="[A-Za-z]{3}" maxlength="3" /></label>
        <label>日期<input v-model="spentAt" type="date" /></label>
        <label>行程日<select v-model="draft.dayNo"><option :value="null">未指定</option><option v-for="day in detail.dayList" :key="day.dayId" :value="day.dayNo">第 {{ day.dayNo }} 天</option></select></label>
        <label>关联点位<select v-model="draft.itemId"><option :value="null">不关联</option><optgroup v-for="day in detail.dayList" :key="day.dayId" :label="`第 ${day.dayNo} 天`"><option v-for="item in day.items" :key="item.id" :value="item.id">{{ item.poiName }}</option></optgroup></select></label>
        <label>支付方式<input v-model="payment" maxlength="24" placeholder="现金／银行卡等" /></label>
        <label>备注<textarea v-model="note" maxlength="255" rows="3"></textarea></label>
        <p v-if="formError" role="alert">{{ formError }}</p>
        <button type="submit" :disabled="busy">{{ busy ? '保存中…' : '保存' }}</button>
      </form>
    </AppDialog>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import AppDialog from '../ui/AppDialog.vue'
import { confirmDialog } from '../ui/confirm'
import { listExpenses, createExpense, updateExpense, deleteExpense } from '../../api/expenses'
import type { ExpenseCreate, ExpenseListVO, ExpenseVO, ExpenseCategoryTotal } from '../../types/generated/contracts'
import type { ItineraryDetail } from '../../types/itinerary'
const props = defineProps<{ detail: ItineraryDetail; /** 协作（C2.3）：viewer 只读——隐藏记账/改删入口 */ readOnly?: boolean }>()
const emit = defineEmits<{ 'select-item': [id: number] }>()
const labels: Record<string, string> = { attraction: '景点', food: '餐饮', hotel: '住宿', transport: '交通', shopping: '购物', other: '其他' }
const ledger = ref<ExpenseListVO>({ expenses: [], totals: [] })
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const formError = ref('')
const dialog = ref(false)
const editingId = ref<number | null>(null)
const blank = (): ExpenseCreate => ({ category: 'food', amount: '0', currency: 'CNY', dayNo: null, itemId: null, spentAt: null, paymentMethod: null, note: null })
const draft = ref(blank())
const amount = ref('')
const spentAt = ref('')
const payment = ref('')
const note = ref('')
let requestId = 0
async function load() {
  const id = ++requestId
  loading.value = true
  error.value = ''
  try {
    const result = await listExpenses(props.detail.id)
    if (id === requestId) ledger.value = result.data
  } catch { if (id === requestId) error.value = '账目读取失败，请重试。' }
  finally { if (id === requestId) loading.value = false }
}
watch(() => props.detail.id, () => { ledger.value = { expenses: [], totals: [] }; dialog.value = false; void load() }, { immediate: true })
function linkedItem(id: number | null) { return props.detail.dayList.flatMap(d => d.items).find(item => item.id === id) }
function estimate(category: string) { return props.detail.budgetList.filter(b => b.category === category).reduce((n, b) => n + Number(b.amount || 0), 0) }
function isOver(total: ExpenseCategoryTotal) { return total.currency === 'CNY' && Number(total.amount) > estimate(total.category) }
function edit(expense?: ExpenseVO) {
  editingId.value = expense?.id ?? null
  draft.value = expense ? { ...blank(), category: expense.category as ExpenseCreate['category'], currency: expense.currency, dayNo: expense.dayNo, itemId: expense.itemId } : blank()
  amount.value = expense?.amount ?? ''
  spentAt.value = expense?.spentAt ?? ''
  payment.value = expense?.paymentMethod ?? ''
  note.value = expense?.note ?? ''
  formError.value = ''
  dialog.value = true
}
async function save() {
  if (busy.value) return
  if (!/^\d+(\.\d{1,2})?$/.test(amount.value) || Number(amount.value) <= 0 || Number(amount.value) > 99999999.99) {
    formError.value = '请输入大于 0、最多两位小数的金额。'; return
  }
  busy.value = true
  formError.value = ''
  const body: ExpenseCreate = { ...draft.value, amount: amount.value, currency: draft.value.currency.toUpperCase(), spentAt: spentAt.value || null, paymentMethod: payment.value || null, note: note.value || null }
  try {
    if (editingId.value) await updateExpense(editingId.value, body)
    else await createExpense(props.detail.id, body)
    dialog.value = false
    await load()
  } catch { formError.value = '保存失败，请检查账目与关联点位后重试。' }
  finally { busy.value = false }
}
async function remove(expense: ExpenseVO) {
  if (!await confirmDialog(`删除 ${expense.currency} ${expense.amount} 这笔账目？`, { title: '删除账目', confirmText: '删除' })) return
  busy.value = true
  try { await deleteExpense(expense.id); await load() }
  catch { error.value = '删除失败，请重试。' }
  finally { busy.value = false }
}
</script>

<style scoped>
.expense-panel { padding: 12px; color: var(--lp-text); }
header, .expense-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
h3 { margin: 0; font-size: 16px; }
button, input, select, textarea { font: inherit; color: var(--lp-text); background: var(--lp-bg); border: 1px solid var(--lp-border); border-radius: var(--lp-radius-xs); padding: 6px 8px; }
button { cursor: pointer; }
button:disabled { opacity: 0.5; cursor: wait; }
.totals { padding: 12px 0; list-style: none; font-size: 12px; line-height: 1.8; }
.over, [role='alert'] { color: var(--lp-danger); }
.expense-row { border-top: 1px solid var(--lp-border); padding: 12px 0; font-size: 12px; }
.expense-row p { margin: 4px 0; overflow-wrap: anywhere; color: var(--lp-text-muted); }
.actions { display: flex; gap: 4px; }
.expense-form { display: grid; gap: 10px; }
.expense-form label { display: grid; gap: 4px; }
input, select, textarea { width: 100%; box-sizing: border-box; }
</style>
