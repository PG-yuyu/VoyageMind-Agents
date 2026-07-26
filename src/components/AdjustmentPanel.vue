<template>
  <div class="adjustment-panel">
    <h3 class="panel-title">自动调整说明</h3>

    <!-- 无调整 -->
    <div v-if="!hasAdjustment" class="no-adjustment">
      <div class="adjustment-icon">✅</div>
      <div class="adjustment-message">行程已通过校验，无需自动调整</div>
    </div>

    <!-- 有调整 -->
    <div v-else class="adjustment-content">
      <div class="adjustment-summary">
        <span class="summary-icon">🔄</span>
        <span class="summary-text">
          共执行 {{ adjustedCount }} 次调整
        </span>
      </div>

      <!-- 调整详情 -->
      <div class="adjustment-timeline">
        <div
          v-for="(adj, idx) in adjustments"
          :key="idx"
          class="adjustment-step"
        >
          <div class="step-number">{{ idx + 1 }}</div>
          <div class="step-content">
            <div class="step-type">{{ adj.type }}</div>
            <div class="step-reason">原因: {{ adj.reason }}</div>
            <div class="step-action">{{ adj.action }}</div>

            <!-- 变化摘要 -->
            <div v-if="adj.cost_change || adj.distance_change" class="step-impact">
              <span v-if="adj.cost_change" class="impact-item">
                费用 {{ adj.cost_change > 0 ? '+' : '' }}{{ adj.cost_change }} 元
              </span>
              <span v-if="adj.distance_change" class="impact-item">
                距离 {{ adj.distance_change > 0 ? '+' : '' }}{{ adj.distance_change }} 米
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  adjustments?: {
    type: string
    reason: string
    action: string
    cost_change?: number
    distance_change?: number
  }[]
  adjustedCount?: number
}>(), {
  adjustments: () => [],
  adjustedCount: 0,
})

const hasAdjustment = computed(() => props.adjustments.length > 0)
</script>

<style scoped>
.adjustment-panel {
  padding: 16px;
  background: #fff;
  border-radius: 8px;
}

.panel-title {
  margin: 0 0 16px;
  font-size: 18px;
  font-weight: 600;
}

.no-adjustment {
  padding: 32px;
  text-align: center;
}

.adjustment-icon {
  font-size: 32px;
  margin-bottom: 8px;
}

.adjustment-message {
  color: #52c41a;
  font-size: 14px;
}

.adjustment-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  background: #fff7e6;
  border: 1px solid #ffd591;
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 14px;
}

.summary-icon {
  font-size: 20px;
}

.adjustment-timeline {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.adjustment-step {
  display: flex;
  gap: 12px;
}

.step-number {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #1890ff;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
}

.step-content {
  flex: 1;
  padding: 10px 12px;
  background: #fafafa;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.5;
}

.step-type {
  font-weight: 600;
  color: #1890ff;
  margin-bottom: 4px;
}

.step-reason {
  color: #666;
}

.step-action {
  color: #333;
  margin-top: 2px;
}

.step-impact {
  margin-top: 6px;
  display: flex;
  gap: 12px;
}

.impact-item {
  font-size: 12px;
  padding: 2px 6px;
  background: #fff;
  border: 1px solid #f0f0f0;
  border-radius: 4px;
  color: #666;
}
</style>
