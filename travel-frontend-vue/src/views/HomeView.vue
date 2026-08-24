<template>
  <div class="home">
    <el-card class="hero" shadow="never">
      <p class="kicker">AI TRAVEL PLANNER</p>
      <h1>把下一次旅行，<br />交给一次生成。</h1>
      <p class="lede">提交目的地与偏好，Agent 自动规划每日行程、预算与地图路线</p>
      <el-button type="primary" size="large" class="cta" @click="$router.push('/generate')">
        开始生成行程
      </el-button>
    </el-card>

    <el-card class="conn">
      <template #header>
        <span>服务连通性自检</span>
      </template>
      <el-space direction="vertical" :size="12" style="width: 100%">
        <el-alert
          v-if="helloMsg"
          :title="`Java 后端：${helloMsg}`"
          type="success"
          :closable="false"
        />
        <el-alert
          v-if="agentMsg"
          :title="`Python Agent：${agentMsg}`"
          type="success"
          :closable="false"
        />
        <el-alert
          v-else-if="failed"
          title="自检失败，请确认 MySQL / Java 后端 / Python Agent 均已启动"
          type="error"
          :closable="false"
        />
        <el-button :loading="checking" @click="checkConnectivity">重新自检</el-button>
      </el-space>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { callAgent, getHello } from '../api'

const checking = ref(false)
const helloMsg = ref('')
const agentMsg = ref('')
const failed = ref(false)

async function checkConnectivity() {
  checking.value = true
  failed.value = false
  helloMsg.value = ''
  agentMsg.value = ''
  try {
    const hello = await getHello()
    helloMsg.value = hello.data
  } catch {
    failed.value = true
  }
  try {
    const agent = await callAgent()
    agentMsg.value = JSON.stringify(agent.data)
  } catch {
    failed.value = true
  }
  checking.value = false
}

onMounted(checkConnectivity)
</script>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 960px;
  margin: 0 auto;
}

.hero {
  text-align: center;
  padding: 64px 24px;
}

.kicker {
  margin: 0 0 12px;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.28em;
  color: var(--lp-accent);
}

.hero h1 {
  margin: 0 0 14px;
  font-size: 40px;
  line-height: 1.25;
  font-weight: 800;
  letter-spacing: 0.01em;
}

.lede {
  color: var(--lp-muted);
  margin: 0 0 28px;
  font-size: 15px;
}

.cta {
  min-width: 200px;
  font-weight: 700;
}
</style>