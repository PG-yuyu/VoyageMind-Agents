<template>
  <div class="budget-panel">
    <h3 class="panel-title">预算明细</h3>

    <!-- 加载状态 -->
    <div v-if="loading" class="panel-loading">计算中...</div>

    <!-- 空状态 -->
    <div v-else-if="!budget" class="panel-empty">暂无预算数据</div>

    <!-- 预算详情 -->
    <div v-else class="budget-content">
      <!-- 预算环图示意 -->
      <div class="budget-chart">
        <div
          class="budget-ring"
          :style="{ background: ringGradient }"
        >
          <div class="ring-center">
            <div class="ring-total">¥{{ budget.total_cost.toFixed(0) }}</div>
            <div class="ring-label">总花费</div>
          </div>
        </div>

        <div class="budget-status" :class="{ over: budget.over_budget }">
          <template v-if="budget.over_budget">
            ⚠️ 超预算 ¥{{ Math.abs(budget.remaining_budget).toFixed(0) }}
          </template>
          <template v-else-if="budget.total_budget > 0">
            ✅ 剩余 ¥{{ budget.remaining_budget.toFixed(0) }}
          </template>
          <template v-else>
            💰 不限预算模式
          </template>
        </div>
      </div>

      <!-- 费用分类 -->
      <div class="budget-items">
        <div class="budget-item">
          <div class="item-label">
            <span class="color-dot hotel"></span>
            酒店
          </div>
          <div class="item-bar">
            <div
              class="item-bar-fill hotel"
              :style="{ width: itemPercent(budget.hotel_cost) }"
            ></div>
          </div>
          <div class="item-value">¥{{ budget.hotel_cost.toFixed(0) }}</div>
        </div>

        <div class="budget-item">
          <div class="item-label">
            <span class="color-dot ticket"></span>
            门票
          </div>
          <div class="item-bar">
            <div
              class="item-bar-fill ticket"
              :style="{ width: itemPercent(budget.ticket_cost) }"
            ></div>
          </div>
          <div class="item-value">¥{{ budget.ticket_cost.toFixed(0) }}</div>
        </div>

        <div class="budget-item">
          <div class="item-label">
            <span class="color-dot meal"></span>
            餐饮
          </div>
          <div class="item-bar">
            <div
              class="item-bar-fill meal"
              :style="{ width: itemPercent(budget.meal_cost) }"
            ></div>
          </div>
          <div class="item-value">¥{{ budget.meal_cost.toFixed(0) }}</div>
        </div>

        <div class="budget-item">
          <div class="item-label">
            <span class="color-dot transport"></span>
            交通
          </div>
          <div class="item-bar">
            <div
              class="item-bar-fill transport"
              :style="{ width: itemPercent(budget.transport_cost) }"
            ></div>
          </div>
          <div class="item-value">¥{{ budget.transport_cost.toFixed(0) }}</div>
        </div>
      </div>

      <!-- 关键指标 -->
      <div class="budget-metrics">
        <div class="metric">
          <div class="metric-label">预算匹配率</div>
          <div class="metric-value" :class="matchRateClass">
            {{ (store.hardEvaluation?.metrics.budget_match_rate ?? 1) * 100 }}%
          </div>
        </div>
        <div class="metric">
          <div class="metric-label">预算限额</div>
          <div class="metric-value">
            ¥{{ budget.total_budget > 0 ? budget.total_budget.toFixed(0) : '不限' }}
          </div>
        </div>
      </div>
    </div>
  </div>
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

const ringGradient = computed(() => {
  if (!props.budget || props.budget.total_budget === 0) {
    return 'conic-gradient(#e8e8e8 0deg, #e8e8e8 360deg)'
  }
  const pct = Math.min(props.budget.total_cost / props.budget.total_budget, 1)
  const deg = pct * 360
  return `conic-gradient(#1890ff 0deg, #1890ff ${deg}deg, #f0f0f0 ${deg}deg, #f0f0f0 360deg)`
})

const matchRateClass = computed(() => {
  const rate = store.hardEvaluation?.metrics.budget_match_rate ?? 1
  if (rate >= 0.9) return 'good'
  if (rate >= 0.7) return 'ok'
  return 'poor'
})

function itemPercent(cost: number): string {
  if (!props.budget || props.budget.total_cost === 0) return '0%'
  return `${(cost / props.budget.total_cost) * 100}%`
}
</script>

<style scoped>
.budget-panel {
  padding: 16px;
  background: #fff;
  border-radius: 8px;
}

.panel-title {
  margin: 0 0 16px;
  font-size: 18px;
  font-weight: 600;
}

.panel-loading,
.panel-empty {
  padding: 32px;
  text-align: center;
  color: #999;
}

.budget-chart {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 20px;
}

.budget-ring {
  width: 140px;
  height: 140px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 8px;
}

.ring-center {
  width: 90px;
  height: 90px;
  background: #fff;
  border-radius: 50%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.ring-total {
  font-size: 20px;
  font-weight: 700;
  color: #333;
}

.ring-label {
  font-size: 12px;
  color: #999;
}

.budget-status {
  font-size: 14px;
  font-weight: 500;
  color: #52c41a;
}

.budget-status.over {
  color: #ff4d4f;
}

.budget-items {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.budget-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.item-label {
  width: 50px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.color-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.color-dot.hotel { background: #faad14; }
.color-dot.ticket { background: #1890ff; }
.color-dot.meal { background: #52c41a; }
.color-dot.transport { background: #722ed1; }

.item-bar {
  flex: 1;
  height: 8px;
  background: #f0f0f0;
  border-radius: 4px;
  overflow: hidden;
}

.item-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s;
}

.item-bar-fill.hotel { background: #faad14; }
.item-bar-fill.ticket { background: #1890ff; }
.item-bar-fill.meal { background: #52c41a; }
.item-bar-fill.transport { background: #722ed1; }

.item-value {
  width: 80px;
  text-align: right;
  font-weight: 500;
}

.budget-metrics {
  display: flex;
  justify-content: space-around;
  padding: 12px;
  background: #fafafa;
  border-radius: 8px;
}

.metric {
  text-align: center;
}

.metric-label {
  font-size: 12px;
  color: #999;
  margin-bottom: 4px;
}

.metric-value {
  font-size: 16px;
  font-weight: 600;
}

.metric-value.good { color: #52c41a; }
.metric-value.ok { color: #faad14; }
.metric-value.poor { color: #ff4d4f; }
</style>
