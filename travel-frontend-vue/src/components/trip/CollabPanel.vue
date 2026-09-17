<template>
  <div class="collab-panel">
    <!-- 成员列表（成员可读） -->
    <section class="members">
      <div class="section-head">
        <h3>成员</h3>
        <span v-if="!isOwner" class="hint">仅行程所有者可管理成员</span>
      </div>
      <p v-if="loadError" class="error">{{ loadError }} <button type="button" @click="load">重试</button></p>
      <p v-else-if="loading" class="hint">加载中…</p>
      <ul v-else class="member-list">
        <li v-for="member in members" :key="member.id" class="member-row">
          <span class="name">{{ member.username || `用户 ${member.userId}` }}</span>
          <select
            v-if="isOwner"
            class="role-select"
            :value="member.role"
            :aria-label="`修改 ${member.username || member.userId} 的角色`"
            @change="onRoleChange(member, ($event.target as HTMLSelectElement).value as MemberVO['role'])"
          >
            <option value="editor">可编辑</option>
            <option value="viewer">仅查看</option>
          </select>
          <span v-else class="role-tag">{{ member.role === 'editor' ? '可编辑' : '仅查看' }}</span>
          <button v-if="isOwner" type="button" class="remove" @click="onRemove(member)">移除</button>
        </li>
      </ul>
    </section>

    <!-- 邀请（仅 owner）：生成链接 → 复制即达 -->
    <section v-if="isOwner" class="invitations">
      <div class="section-head">
        <h3>邀请协作</h3>
        <select v-model="inviteRole" class="role-select" aria-label="邀请角色">
          <option value="editor">可编辑</option>
          <option value="viewer">仅查看</option>
        </select>
        <button type="button" class="primary" :disabled="creating" @click="onInvite">
          {{ creating ? '生成中…' : '生成邀请链接' }}
        </button>
      </div>

      <div v-if="lastToken" class="invite-result">
        <p class="link">{{ inviteLink }}</p>
        <button type="button" class="primary" @click="copyInvite">复制链接</button>
        <p class="hint">链接 7 天有效、单次使用；明文仅展示这一次。</p>
      </div>

      <template v-if="invitations.length">
        <h4 class="pending-head">未过期的邀请</h4>
        <ul class="invitation-list">
          <li v-for="invitation in activeInvitations" :key="invitation.id" class="invitation-row">
            <span>{{ invitation.role === 'editor' ? '可编辑' : '仅查看' }}</span>
            <span class="hint">至 {{ shortTime(invitation.expiresAt) }}</span>
            <button type="button" class="remove" @click="onRevoke(invitation)">撤销</button>
          </li>
        </ul>
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
/** 协作面板（C2.3）：成员列表/邀请生成与撤销。owner 管理权以后端为准，这里只做入口显隐。 */
import { computed, onMounted, ref } from 'vue'
import {
  createInvitation,
  listInvitations,
  listMembers,
  removeMember,
  revokeInvitation,
  updateMemberRole,
  type InvitationVO,
  type MemberVO,
} from '../../api/collaboration'
import { toast } from '../ui/toast'

const props = defineProps<{
  itineraryId: number | string
  /** 调用者是否行程所有者（detail.myRole === 'owner'） */
  isOwner: boolean
}>()

const members = ref<MemberVO[]>([])
const invitations = ref<InvitationVO[]>([])
const loading = ref(false)
const loadError = ref('')
const creating = ref(false)
const inviteRole = ref<MemberVO['role']>('editor')
const lastToken = ref('')

const activeInvitations = computed(() => invitations.value.filter((item) => item.status === 'pending'))
const inviteLink = computed(() =>
  lastToken.value ? `${window.location.origin}/trips?invite=${encodeURIComponent(lastToken.value)}` : '',
)

onMounted(load)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    members.value = (await listMembers(props.itineraryId)).data
    if (props.isOwner) invitations.value = (await listInvitations(props.itineraryId)).data
  } catch {
    loadError.value = '成员加载失败'
  } finally {
    loading.value = false
  }
}

async function onInvite() {
  creating.value = true
  try {
    const created = (await createInvitation(props.itineraryId, inviteRole.value)).data
    lastToken.value = created.token
    invitations.value = (await listInvitations(props.itineraryId)).data
  } catch {
    toast.error('邀请生成失败，请重试')
  } finally {
    creating.value = false
  }
}

async function copyInvite() {
  try {
    await navigator.clipboard.writeText(inviteLink.value)
    toast.success('已复制，发给对方即可加入')
  } catch {
    toast.error('复制失败，请手动选择链接复制')
  }
}

async function onRevoke(invitation: InvitationVO) {
  try {
    await revokeInvitation(props.itineraryId, invitation.id)
    invitations.value = (await listInvitations(props.itineraryId)).data
    toast.success('已撤销')
  } catch {
    toast.error('撤销失败')
  }
}

async function onRoleChange(member: MemberVO, role: MemberVO['role']) {
  try {
    await updateMemberRole(props.itineraryId, member.id, role)
    toast.success('角色已更新')
  } catch {
    toast.error('角色修改失败')
  } finally {
    await load()
  }
}

async function onRemove(member: MemberVO) {
  try {
    await removeMember(props.itineraryId, member.id)
    toast.success('已移除，对方将无法访问本行程')
    await load()
  } catch {
    toast.error('移除失败')
  }
}

function shortTime(value: string | null): string {
  return value ? value.slice(0, 16).replace('T', ' ') : ''
}
</script>

<style scoped>
.collab-panel {
  display: flex;
  flex-direction: column;
  gap: 20px;
  font-size: 14px;
  color: var(--lp-text-body);
}
.section-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.section-head h3 {
  margin: 0;
  font-size: 15px;
  color: var(--lp-text-title);
}
.hint {
  color: var(--lp-text-muted);
  font-size: 12px;
}
.member-list,
.invitation-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.member-row,
.invitation-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.member-row .name {
  flex: 1;
}
.role-select {
  border: 1px solid var(--lp-border);
  border-radius: var(--lp-radius-xs);
  padding: 4px 6px;
  background: var(--lp-bg);
  color: var(--lp-text-body);
}
.role-tag {
  color: var(--lp-text-muted);
}
button.primary {
  border: 1px solid var(--lp-accent);
  background: var(--lp-accent);
  color: var(--lp-accent-on-fill);
  border-radius: var(--lp-radius-sm);
  padding: 6px 12px;
  cursor: pointer;
}
button.primary:disabled {
  opacity: 0.6;
  cursor: default;
}
button.remove {
  border: none;
  background: none;
  color: var(--lp-danger);
  cursor: pointer;
  font-size: 13px;
}
.invite-result {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px;
  border: 1px dashed var(--lp-border);
  border-radius: var(--lp-radius-sm);
}
.invite-result .link {
  margin: 0;
  word-break: break-all;
  font-size: 12px;
}
.pending-head {
  margin: 12px 0 6px;
  font-size: 13px;
  color: var(--lp-text-subtitle);
}
.error {
  color: var(--lp-danger);
}
.error button {
  border: none;
  background: none;
  color: inherit;
  text-decoration: underline;
  cursor: pointer;
}
</style>
