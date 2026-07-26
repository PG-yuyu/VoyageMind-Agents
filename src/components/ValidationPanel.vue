<template>
  <div class="validation-panel">
    <h3 class="panel-title">硬约束校验结果</h3>

    <!-- 加载状态 -->
    <div v-if="loading" class="panel-loading">校验中...</div>

    <!-- 空状态 -->
    <div v-else-if="!issues" class="panel-empty">暂无校验数据</div>

    <!-- 校验结果 -->
    <div v-else class="validation-content">
      <!-- 总状态 -->
      <div class="validation-status" :class="passed ? 'passed' : 'failed'">
        <span class="status-icon">{{ passed ? '✅' : '❌' }}</span>
        <span class="status-text">
          {{ passed ? '校验通过' : '存在需要处理的问题' }}
        </span>
        <span class="issue-count">{{ filteredIssues.length }} 项</span>
      </div>

      <!-- 指标卡片 -->
      <div class="metrics-row">
        <div class="metric-card" :class="timeValid ? 'ok' : 'err'">
          <div class="metric-icon">⏰</div>
          <div class="metric-info">
            <div class="metric-label">时间有效</div>
            <div class="metric-value">{{ timeValid ? '是' : '否' }}</div>
          </div>
        </div>
        <div class="metric-card" :class="walkingValid ? 'ok' : 'err'">
          <div class="metric-icon">🚶</div>
          <div class="metric-info">
            <div class="metric-label">步行合规</div>
            <div class="metric-value">{{ walkingValid ? '是' : '否' }}</div>
          </div>
        </div>
        <div class="metric-card" :class="budgetRateClass">
          <div class="metric-icon">💰</div>
          <div class="metric-info">
            <div class="metric-label">预算匹配</div>
            <div class="metric-value">{{ budgetRate }}%</div>
          </div>
        </div>
      </div>

      <!-- 问题列表 -->
      <div class="issues-section">
        <h4 class="section-title">问题列表</h4>
        <div v-if="filteredIssues.length === 0" class="no-issues">
          没有发现问题
        </div>
        <div
          v-for="issue in filteredIssues"
          :key="`${issue.code}-${issue.item_id}`"
          class="issue-item"
          :class="issue.severity"
        >
          <div class="issue-header">
            <span class="issue-severity">{{ severityLabel(issue.severity) }}</span>
            <span class="issue-code">{{ issue.code }}</span>
            <span v-if="issue.day" class="issue-day">第 {{ issue.day }} 天</span>
          </div>
          <div class="issue-message">{{ issue.message }}</div>
          <div v-if="issue.suggestion" class="issue-suggestion">
            💡 {{ issue.suggestion }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useItineraryStore } from '../stores/itineraryStore'
import type { ValidationIssue } from '../types/common'

const store = useItineraryStore()

const props = withDefaults(defineProps<{
  issues?: ValidationIssue[] | null
  loading?: boolean
  passed?: boolean
  timeValid?: boolean
  walkingValid?: boolean
  budgetRate?: number
}>(), {
  issues: null,
  loading: false,
  passed: true,
  timeValid: true,
  walkingValid: true,
  budgetRate: 100,
})

const filteredIssues = computed(() => props.issues ?? [])
const budgetRateClass = computed(() => {
  if (props.budgetRate >= 90) return 'ok'
  if (props.budgetRate >= 70) return 'warn'
  return 'err'
})

function severityLabel(s: string): string {
  const map: Record<string, string> = {
    error: '错误',
    warning: '警告',
    info: '提示',
  }
  return map[s] || s
}
</script>

<style scoped>
.validation-panel {
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

.validation-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 14px;
}

.validation-status.passed {
  background: #f6ffed;
  border: 1px solid #b7eb8f;
}

.validation-status.failed {
  background: #fff2f0;
  border: 1px solid #ffccc7;
}

.issue-count {
  margin-left: auto;
  font-size: 13px;
  color: #666;
}

.metrics-row {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.metric-card {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  border-radius: 8px;
  border: 1px solid #f0f0f0;
}

.metric-card.ok { border-color: #b7eb8f; }
.metric-card.warn { border-color: #ffe58f; }
.metric-card.err { border-color: #ffccc7; }

.metric-icon {
  font-size: 24px;
}

.metric-label {
  font-size: 12px;
  color: #999;
}

.metric-value {
  font-size: 16px;
  font-weight: 600;
}

.section-title {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 500;
}

.no-issues {
  padding: 16px;
  text-align: center;
  color: #52c41a;
  font-size: 14px;
}

.issue-item {
  padding: 8px 12px;
  margin-bottom: 8px;
  border-radius: 6px;
  border-left: 3px solid;
}

.issue-item.error {
  background: #fff2f0;
  border-color: #ff4d4f;
}

.issue-item.warning {
  background: #fffbe6;
  border-color: #faad14;
}

.issue-item.info {
  background: #e6f7ff;
  border-color: #1890ff;
}

.issue-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
  font-size: 12px;
}

.issue-severity {
  padding: 0 4px;
  border-radius: 2px;
  font-size: 11px;
  font-weight: 500;
}

.issue-item.error .issue-severity { background: #ffccc7; color: #cf1322; }
.issue-item.warning .issue-severity { background: #ffe58f; color: #d48806; }
.issue-item.info .issue-severity { background: #bae7ff; color: #096dd9; }

.issue-code {
  color: #666;
  font-family: monospace;
}

.issue-day {
  color: #999;
  margin-left: auto;
}

.issue-message {
  font-size: 13px;
  margin-bottom: 2px;
}

.issue-suggestion {
  font-size: 12px;
  color: #1890ff;
}
</style>
