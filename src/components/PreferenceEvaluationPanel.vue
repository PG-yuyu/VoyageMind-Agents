<template>
  <div class="preference-panel">
    <h3 class="panel-title">软偏好评价</h3>

    <!-- 加载状态 -->
    <div v-if="loading" class="panel-loading">评价中...</div>

    <!-- 空状态 -->
    <div v-else-if="!evaluation" class="panel-empty">
      暂无软偏好数据
    </div>

    <!-- 评价内容 -->
    <div v-else class="preference-content">
      <!-- 总状态 -->
      <div
        class="preference-status"
        :class="evaluation.soft_preference_passed ? 'passed' : 'failed'"
      >
        <span class="status-icon">
          {{ evaluation.soft_preference_passed ? '😊' : '🤔' }}
        </span>
        <span class="status-text">
          {{ evaluation.soft_preference_passed ? '行程符合偏好' : '部分偏好未充分满足' }}
        </span>
      </div>

      <!-- 总体评价 -->
      <div v-if="evaluation.overall_assessment" class="overall-assessment">
        {{ evaluation.overall_assessment }}
      </div>

      <!-- 具体评价列表 -->
      <div v-if="evaluation.issues.length > 0" class="issues-section">
        <h4 class="section-title">改进建议</h4>
        <div
          v-for="(issue, idx) in evaluation.issues"
          :key="idx"
          class="preference-issue"
        >
          <div class="issue-preference">
            <span class="pref-label">偏好</span>
            {{ issue.preference }}
          </div>
          <div class="issue-assessment">
            <span class="pref-label">评估</span>
            {{ issue.assessment }}
          </div>
          <div class="issue-suggestion">
            <span class="pref-label">建议</span>
            {{ issue.suggestion }}
          </div>
          <div class="issue-confidence">
            置信度: {{ (issue.confidence * 100).toFixed(0) }}%
          </div>
        </div>
      </div>

      <!-- 全部满足 -->
      <div v-else class="all-satisfied">🎉 所有隐含偏好均得到满足</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { SoftPreferenceEvaluation } from '../types/common'

defineProps<{
  evaluation?: SoftPreferenceEvaluation | null
  loading?: boolean
}>()
</script>

<style scoped>
.preference-panel {
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

.preference-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  border-radius: 8px;
  margin-bottom: 12px;
  font-size: 14px;
}

.preference-status.passed {
  background: #f6ffed;
  border: 1px solid #b7eb8f;
}

.preference-status.failed {
  background: #fffbe6;
  border: 1px solid #ffe58f;
}

.overall-assessment {
  padding: 12px;
  background: #fafafa;
  border-radius: 6px;
  margin-bottom: 16px;
  font-size: 14px;
  color: #555;
  line-height: 1.5;
}

.section-title {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 500;
}

.preference-issue {
  padding: 10px 12px;
  margin-bottom: 8px;
  background: #fafafa;
  border-radius: 6px;
  border-left: 3px solid #faad14;
  font-size: 13px;
  line-height: 1.6;
}

.pref-label {
  display: inline-block;
  font-size: 11px;
  color: #999;
  background: #f0f0f0;
  padding: 0 4px;
  border-radius: 2px;
  margin-right: 4px;
}

.issue-confidence {
  margin-top: 4px;
  font-size: 12px;
  color: #aaa;
}

.all-satisfied {
  padding: 24px;
  text-align: center;
  font-size: 16px;
  color: #52c41a;
}
</style>
