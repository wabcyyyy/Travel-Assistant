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
  </div>
</template>

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