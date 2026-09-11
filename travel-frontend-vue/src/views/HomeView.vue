<template>
  <div class="home">
    <!-- Hero：左文案 + 右行程手册切片（展示产品本身） -->
    <section class="hero">
      <div class="hero-copy">
        <p class="eyebrow">AI TRAVEL PLANNER</p>
        <h1>下一次旅行，<br />一次生成<span class="hero-em">可信</span>行程。</h1>
        <p class="lede">
          知识库溯源 · 地图联动 · 预算实时核算。<br />
          提交目的地与偏好，Agent 规划每日行程、路线与花费。
        </p>
        <div class="cta-row">
          <el-button type="primary" size="large" @click="$router.push('/generate')">
            开始生成行程
          </el-button>
          <el-button size="large" text @click="$router.push('/trips')">查看我的行程</el-button>
        </div>
        <ul class="trust-row">
          <li><span class="dot verified"></span>已核实</li>
          <li><span class="dot estimated"></span>参考估算</li>
          <li><span class="dot pending"></span>出发前复核</li>
        </ul>
      </div>

      <!-- 行程手册切片：静态但像真产品 -->
      <div class="hero-visual" aria-hidden="false">
        <div class="slice">
          <div class="slice-head">
            <div>
              <p class="slice-city">杭州</p>
              <p class="slice-meta">2 天 · 2 人 · 预算 ¥3,000</p>
            </div>
            <span class="slice-badge">已核实 4/5</span>
          </div>
          <hr class="lp-rule" />
          <ol class="slice-days">
            <li v-for="item in DEMO_ITEMS" :key="item.name" class="slice-row">
              <span class="lp-ordinal slice-idx">{{ item.idx }}</span>
              <div class="slice-main">
                <div class="slice-name">{{ item.name }}</div>
                <div class="slice-sub">
                  <span class="slice-time">{{ item.time }}</span>
                  <span v-if="item.cost" class="slice-cost">{{ item.cost }}</span>
                </div>
              </div>
              <el-tag :type="item.tagType" size="small" effect="light">
                {{ item.tag }}
              </el-tag>
            </li>
          </ol>
          <div class="slice-foot">
            <span>来源：知识库 / 高德 POI</span>
            <span class="slice-link">导出 PDF →</span>
          </div>
        </div>
      </div>
    </section>

    <!-- 手册纸色三栏：能力说明 -->
    <section class="bento">
      <h2 class="bento-title">它能帮你做什么</h2>
      <div class="bento-grid">
        <article class="cell">
          <div class="cell-icon">
            <el-icon :size="28" color="var(--lp-accent)"><Document /></el-icon>
          </div>
          <div class="cell-title">引用式生成</div>
          <div class="cell-desc">
            知识库条目以参考资料注入 Prompt，行程项标注来源与更新时间，开放选点显式标记「待复核」。
          </div>
        </article>
        <article class="cell">
          <div class="cell-icon">
            <el-icon :size="28" color="var(--lp-accent)"><MapLocation /></el-icon>
          </div>
          <div class="cell-title">地图路线</div>
          <div class="cell-desc">
            每日点位自动连线，拖拽排序实时同步地图；附近推荐只用真实坐标。
          </div>
        </article>
        <article class="cell">
          <div class="cell-icon">
            <el-icon :size="28" color="var(--lp-accent)"><Coin /></el-icon>
          </div>
          <div class="cell-title">预算看板</div>
          <div class="cell-desc">
            门票、餐饮、住宿逐项核算，编辑后实时重算，超支一目了然。
          </div>
        </article>
      </div>
    </section>

    <!-- 目的地封面墙 -->
    <section class="dest-wall">
      <div class="dest-head">
        <h2 class="bento-title">热门目的地</h2>
        <p class="dest-sub">点击城市，直接带着目的地去生成</p>
      </div>
      <div class="dest-grid">
        <button
          v-for="c in DESTINATIONS"
          :key="c.name"
          type="button"
          class="dest-card"
          @click="goGenerate(c.name)"
        >
          <img :src="c.img" :alt="c.name" loading="lazy" />
          <div class="lp-cover-fade" aria-hidden="true"></div>
          <span class="dest-name">{{ c.name }}</span>
        </button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { Coin, Document, MapLocation } from '@element-plus/icons-vue'

import coverBeijing from '../assets/img/cover-beijing.jpg'
import coverChengdu from '../assets/img/cover-chengdu.jpg'
import coverChongqing from '../assets/img/cover-chongqing.jpg'
import coverHangzhou from '../assets/img/cover-hangzhou.jpg'
import coverShanghai from '../assets/img/cover-shanghai.jpg'
import coverXian from '../assets/img/cover-xian.jpg'

const router = useRouter()

const DEMO_ITEMS = [
  { idx: '01', name: '西湖断桥', time: '09:00', cost: '免费', tag: '已核实', tagType: 'success' as const },
  { idx: '02', name: '知味观·味庄', time: '12:30', cost: '¥86/人', tag: '已核实', tagType: 'success' as const },
  { idx: '03', name: '灵隐寺', time: '15:00', cost: '¥75/人', tag: '参考估算', tagType: 'warning' as const },
  { idx: '04', name: '河坊街', time: '18:30', cost: '自由消费', tag: '已核实', tagType: 'success' as const },
  { idx: '05', name: '楼外楼', time: '19:30', cost: '¥120/人', tag: '待复核', tagType: 'info' as const },
]

const DESTINATIONS = [
  { name: '杭州', img: coverHangzhou },
  { name: '成都', img: coverChengdu },
  { name: '西安', img: coverXian },
  { name: '重庆', img: coverChongqing },
  { name: '北京', img: coverBeijing },
  { name: '上海', img: coverShanghai },
]

function goGenerate(city: string) {
  router.push({ path: '/generate', query: { city } })
}
</script>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  gap: 48px;
  max-width: var(--lp-content, 1120px);
  margin: 0 auto;
}

/* ---------- Hero：左文右手册切片 ---------- */
.hero {
  display: grid;
  grid-template-columns: 1.05fr 1fr;
  gap: 40px;
  align-items: center;
  padding: 8px 0 0;
}

.eyebrow {
  margin: 0 0 14px;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.28em;
  color: var(--lp-accent);
}

.hero h1 {
  margin: 0 0 14px;
  font-family: var(--lp-font-display);
  font-size: clamp(32px, 4.2vw, 46px);
  line-height: 1.22;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--lp-ink-deep);
}

.hero-em {
  color: var(--lp-accent);
}

.lede {
  color: var(--lp-muted);
  margin: 0 0 28px;
  font-size: 16px;
  line-height: 1.75;
  max-width: 34em;
}

.cta-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.trust-row {
  display: flex;
  flex-wrap: wrap;
  gap: 14px 20px;
  margin: 22px 0 0;
  padding: 0;
  list-style: none;
  font-size: 12.5px;
  color: var(--lp-muted);
}

.trust-row .dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: 1px;
}

.trust-row .dot.verified {
  background: var(--lp-success);
}

.trust-row .dot.estimated {
  background: var(--lp-warning);
}

.trust-row .dot.pending {
  background: var(--lp-muted);
}

/* 手册切片卡 */
.hero-visual {
  min-width: 0;
}

.slice {
  background: var(--lp-surface);
  border: 1px solid var(--lp-border);
  border-radius: 16px;
  box-shadow: var(--lp-shadow-md);
  overflow: hidden;
}

.slice-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 20px 22px 16px;
  background: var(--lp-cover-gradient);
  color: #fffdf8;
}

.slice-city {
  margin: 0;
  font-family: var(--lp-font-display);
  font-size: 24px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.slice-meta {
  margin: 4px 0 0;
  font-size: 12px;
  color: rgb(255 253 248 / 78%);
  font-variant-numeric: tabular-nums;
}

.slice-badge {
  flex: none;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid rgb(255 255 255 / 35%);
  background: rgb(255 255 255 / 12%);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.slice-days {
  margin: 0;
  padding: 4px 0;
  list-style: none;
}

.slice-row {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 11px 22px;
  border-bottom: 1px solid var(--lp-rule);
}

.slice-row:last-child {
  border-bottom: none;
}

.slice-idx {
  font-size: 15px;
  font-style: italic;
}

.slice-name {
  font-family: var(--lp-font-display);
  font-size: 15px;
  font-weight: 500;
  color: var(--lp-ink);
}

.slice-sub {
  display: flex;
  gap: 10px;
  margin-top: 2px;
  font-size: 12px;
  color: var(--lp-muted);
  font-variant-numeric: tabular-nums;
}

.slice-time {
  font-family: var(--lp-font-data);
  font-weight: 600;
  color: var(--lp-ink-soft);
}

.slice-foot {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 22px 14px;
  background: var(--lp-paper);
  font-size: 11.5px;
  color: var(--lp-muted);
}

.slice-link {
  color: var(--lp-accent);
  font-weight: 600;
}

/* ---------- 能力三栏：纸色手册卡 ---------- */
.bento-title {
  margin: 0 0 18px;
  font-family: var(--lp-font-display);
  font-size: 26px;
  font-weight: 600;
  color: var(--lp-ink-deep);
}

.bento-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.cell {
  border-radius: 16px;
  padding: 22px 20px;
  background: var(--lp-surface);
  border: 1px solid var(--lp-border);
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease,
    transform 0.2s ease;
}

.cell:hover {
  border-color: var(--lp-accent);
  box-shadow: var(--lp-shadow-sm);
  transform: translateY(-2px);
}

.cell-icon {
  margin-bottom: 12px;
}

.cell-title {
  font-family: var(--lp-font-display);
  font-size: 17px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--lp-ink);
}

.cell-desc {
  font-size: 13px;
  line-height: 1.75;
  color: var(--lp-muted);
}

/* ---------- 目的地封面墙 ---------- */
.dest-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}

.dest-head .bento-title {
  margin: 0;
}

.dest-sub {
  margin: 0;
  font-size: 13px;
  color: var(--lp-muted);
}

.dest-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

.dest-card {
  position: relative;
  height: 140px;
  padding: 0;
  border: 1px solid var(--lp-border);
  border-radius: 14px;
  overflow: hidden;
  cursor: pointer;
  background: var(--lp-sand);
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease,
    transform 0.2s ease;
}

.dest-card img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 0.4s ease;
}

.dest-card:hover {
  border-color: var(--lp-accent);
  box-shadow: var(--lp-shadow-sm);
  transform: translateY(-2px);
}

.dest-card:hover img {
  transform: scale(1.04);
}

.dest-card:focus-visible {
  outline: 2px solid var(--lp-accent);
  outline-offset: 2px;
}

.dest-name {
  position: absolute;
  left: 14px;
  bottom: 12px;
  z-index: 1;
  font-family: var(--lp-font-display);
  font-size: 20px;
  font-weight: 600;
  color: #fffdf8;
  letter-spacing: 0.04em;
  text-shadow: 0 1px 8px rgb(0 0 0 / 35%);
}

/* ---------- 移动端 ---------- */
@media (max-width: 860px) {
  .hero {
    grid-template-columns: 1fr;
    gap: 28px;
  }

  .bento-grid {
    grid-template-columns: 1fr;
  }

  .dest-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .dest-card {
    height: 120px;
  }

  .cta-row {
    flex-wrap: wrap;
  }

  .cta-row .el-button {
    width: 100%;
  }
}

@media (max-width: 480px) {
  .dest-card {
    height: 100px;
  }

  .dest-name {
    font-size: 17px;
  }

  .hero h1 {
    font-size: 28px;
  }
}
</style>
