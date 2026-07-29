<template>
  <section class="budget-panel">
    <div class="budget-panel__head">
      <div>
        <p class="budget-kicker">Budget Overview</p>
        <h3>预算明细</h3>
      </div>
      <span class="budget-badge" :class="{ over: budget?.over_budget }">
        {{ statusText }}
      </span>
    </div>

    <div v-if="loading" class="panel-loading">计算中...</div>
    <div v-else-if="!budget" class="panel-empty">暂无预算数据</div>

    <div v-else class="budget-content">
      <div class="budget-hero">
        <div class="budget-ring-wrap">
          <div class="budget-ring" :style="{ background: ringGradient }">
            <div class="ring-center">
              <span>已用</span>
              <strong>{{ usedPercent }}%</strong>
            </div>
          </div>
        </div>

        <div class="budget-summary">
          <div>
            <span>预计总花费</span>
            <strong>¥{{ money(budget.total_cost) }}</strong>
          </div>
          <div>
            <span>预算限额</span>
            <strong>{{ budget.total_budget > 0 ? `¥${money(budget.total_budget)}` : '不限' }}</strong>
          </div>
          <div>
            <span>{{ budget.over_budget ? '超出预算' : '预算余额' }}</span>
            <strong :class="{ danger: budget.over_budget }">¥{{ money(Math.abs(budget.remaining_budget)) }}</strong>
          </div>
        </div>
      </div>

      <div class="budget-progress">
        <div class="budget-progress__top">
          <span>预算使用进度</span>
          <strong>{{ budget.total_budget > 0 ? `${usedPercent}%` : '不限额' }}</strong>
        </div>
        <div class="budget-track">
          <span :class="{ over: budget.over_budget }" :style="{ width: progressWidth }"></span>
        </div>
      </div>

      <div class="budget-category-grid">
        <article
          v-for="item in categoryItems"
          :key="item.key"
          class="budget-category"
        >
          <div class="category-top">
            <span class="category-icon" :class="item.key">{{ item.short }}</span>
            <div>
              <h4>{{ item.label }}</h4>
              <p>{{ itemPercent(item.value) }}%</p>
            </div>
          </div>
          <strong>¥{{ money(item.value) }}</strong>
          <div class="category-track">
            <span :class="item.key" :style="{ width: `${itemPercent(item.value)}%` }"></span>
          </div>
        </article>
      </div>

      <div class="budget-note">
        <div>
          <span>预算匹配率</span>
          <strong :class="matchRateClass">{{ matchRate }}%</strong>
        </div>
        <p>费用来自当前行程卡片汇总，并按同行人数换算。</p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useItineraryStore } from '../stores/itineraryStore'
import type { BudgetSummary } from '../types/common'

const store = useItineraryStore()

const props = withDefaults(defineProps<{
  budget?: BudgetSummary | null
  loading?: boolean
}>(), {
  budget: null,
  loading: false,
})

const usedPercent = computed(() => {
  if (!props.budget) return 0
  if (props.budget.total_budget <= 0) return props.budget.total_cost > 0 ? 100 : 0
  return Math.min(999, Math.round((props.budget.total_cost / props.budget.total_budget) * 100))
})

const progressWidth = computed(() => `${Math.min(100, usedPercent.value)}%`)

const ringGradient = computed(() => {
  if (!props.budget) {
    return 'conic-gradient(#e5e7eb 0deg, #e5e7eb 360deg)'
  }
  const deg = Math.min(360, usedPercent.value * 3.6)
  const mainColor = props.budget.over_budget ? '#ef4444' : '#16a394'
  return `conic-gradient(${mainColor} 0deg, ${mainColor} ${deg}deg, #e7eef6 ${deg}deg, #e7eef6 360deg)`
})

const statusText = computed(() => {
  if (!props.budget) return '待计算'
  if (props.budget.total_budget <= 0) return '不限预算'
  return props.budget.over_budget ? '已超预算' : '预算内'
})

const matchRate = computed(() => {
  const rate = store.hardEvaluation?.metrics.budget_match_rate ?? 1
  return Math.round(rate * 100)
})

const matchRateClass = computed(() => {
  if (matchRate.value >= 90) return 'good'
  if (matchRate.value >= 70) return 'ok'
  return 'poor'
})

const categoryItems = computed(() => {
  const budget = props.budget
  if (!budget) return []
  return [
    { key: 'hotel', short: '住', label: '酒店住宿', value: budget.hotel_cost },
    { key: 'ticket', short: '票', label: '门票项目', value: budget.ticket_cost },
    { key: 'meal', short: '餐', label: '餐饮消费', value: budget.meal_cost },
    { key: 'transport', short: '行', label: '市内交通', value: budget.transport_cost },
  ]
})

function itemPercent(cost: number): number {
  if (!props.budget || props.budget.total_cost <= 0) return 0
  return Math.round((cost / props.budget.total_cost) * 100)
}

function money(value: number): string {
  return Math.round(Number.isFinite(value) ? value : 0).toLocaleString('zh-CN')
}
</script>

<style scoped>
.budget-panel {
  display: grid;
  gap: 22px;
  padding: clamp(22px, 3vw, 34px);
  border: 1px solid rgba(218, 228, 238, 0.92);
  border-radius: 28px;
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.96), rgba(240, 251, 248, 0.92)),
    #fff;
  box-shadow: 0 26px 70px rgba(31, 41, 55, 0.09);
}

.budget-panel__head,
.budget-hero,
.budget-summary,
.budget-progress__top,
.category-top,
.budget-note {
  display: flex;
  align-items: center;
}

.budget-panel__head {
  justify-content: space-between;
  gap: 18px;
}

.budget-kicker {
  margin: 0 0 6px;
  color: #4f65ff;
  font-size: 13px;
  font-weight: 900;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.budget-panel h3 {
  margin: 0;
  color: #071225;
  font-size: clamp(24px, 3vw, 34px);
  line-height: 1.15;
}

.budget-badge {
  min-width: 86px;
  padding: 10px 14px;
  border-radius: 999px;
  background: #e9fbf5;
  color: #078272;
  font-size: 14px;
  font-weight: 900;
  text-align: center;
}

.budget-badge.over {
  background: #fff1f2;
  color: #dc2626;
}

.panel-loading,
.panel-empty {
  padding: 48px 16px;
  border: 1px dashed #cbd7e6;
  border-radius: 20px;
  color: #69778d;
  text-align: center;
}

.budget-content {
  display: grid;
  gap: 22px;
}

.budget-hero {
  gap: clamp(18px, 4vw, 34px);
  align-items: stretch;
}

.budget-ring-wrap {
  display: grid;
  min-width: 190px;
  place-items: center;
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.74);
  box-shadow: inset 0 0 0 1px rgba(218, 228, 238, 0.9);
}

.budget-ring {
  display: grid;
  width: 156px;
  height: 156px;
  place-items: center;
  border-radius: 50%;
  box-shadow: 0 18px 44px rgba(22, 163, 148, 0.13);
}

.ring-center {
  display: grid;
  width: 104px;
  height: 104px;
  place-items: center;
  align-content: center;
  border-radius: 50%;
  background: #fff;
  box-shadow: inset 0 0 0 1px rgba(218, 228, 238, 0.9);
}

.ring-center span {
  color: #69778d;
  font-size: 13px;
  font-weight: 800;
}

.ring-center strong {
  color: #071225;
  font-size: 30px;
  line-height: 1.1;
}

.budget-summary {
  flex: 1;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.budget-summary > div {
  display: grid;
  align-content: center;
  min-height: 128px;
  padding: 18px;
  border: 1px solid rgba(218, 228, 238, 0.88);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.82);
}

.budget-summary span,
.budget-progress__top span,
.budget-note span,
.budget-category p {
  color: #69778d;
  font-size: 14px;
  font-weight: 800;
}

.budget-summary strong {
  margin-top: 8px;
  color: #071225;
  font-size: clamp(24px, 3vw, 34px);
  line-height: 1.1;
}

.budget-summary strong.danger {
  color: #dc2626;
}

.budget-progress {
  display: grid;
  gap: 10px;
}

.budget-progress__top {
  justify-content: space-between;
}

.budget-progress__top strong {
  color: #071225;
  font-size: 16px;
}

.budget-track,
.category-track {
  height: 12px;
  overflow: hidden;
  border-radius: 999px;
  background: #e7eef6;
}

.budget-track span,
.category-track span {
  display: block;
  height: 100%;
  min-width: 4px;
  border-radius: inherit;
  background: linear-gradient(90deg, #4f65ff, #16a394);
  transition: width 0.28s ease;
}

.budget-track span.over {
  background: linear-gradient(90deg, #f59e0b, #ef4444);
}

.budget-category-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.budget-category {
  display: grid;
  gap: 14px;
  min-height: 150px;
  padding: 16px;
  border: 1px solid rgba(218, 228, 238, 0.9);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.82);
}

.category-top {
  gap: 10px;
}

.category-icon {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: 14px;
  color: #fff;
  font-size: 15px;
  font-weight: 900;
}

.category-icon.hotel,
.category-track .hotel {
  background: #f59e0b;
}

.category-icon.ticket,
.category-track .ticket {
  background: #4f65ff;
}

.category-icon.meal,
.category-track .meal {
  background: #16a394;
}

.category-icon.transport,
.category-track .transport {
  background: #7c3aed;
}

.budget-category h4,
.budget-category p {
  margin: 0;
}

.budget-category h4 {
  color: #071225;
  font-size: 16px;
}

.budget-category strong {
  color: #071225;
  font-size: 26px;
  line-height: 1.1;
}

.budget-note {
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
  border-radius: 20px;
  background: #f6f9fc;
  color: #69778d;
}

.budget-note > div {
  display: grid;
  gap: 4px;
  min-width: 116px;
}

.budget-note strong {
  color: #071225;
  font-size: 22px;
}

.budget-note strong.good {
  color: #078272;
}

.budget-note strong.ok {
  color: #b45309;
}

.budget-note strong.poor {
  color: #dc2626;
}

.budget-note p {
  margin: 0;
  color: #69778d;
  font-size: 14px;
  line-height: 1.7;
  text-align: right;
}

@media (max-width: 980px) {
  .budget-hero,
  .budget-note {
    align-items: stretch;
    flex-direction: column;
  }

  .budget-summary,
  .budget-category-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .budget-ring-wrap {
    min-height: 190px;
  }

  .budget-note p {
    text-align: left;
  }
}

@media (max-width: 640px) {
  .budget-panel__head {
    align-items: flex-start;
    flex-direction: column;
  }

  .budget-summary,
  .budget-category-grid {
    grid-template-columns: 1fr;
  }

  .budget-summary > div {
    min-height: 96px;
  }
}
</style>
