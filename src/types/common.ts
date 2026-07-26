/**
 * 前端共用类型定义
 *
 * 与后端 Pydantic Schema 保持一致
 */

/** 统一响应格式 */
export interface ApiResponse<T = unknown> {
  success: boolean
  code: string
  message: string
  data: T | null
  trace_id?: string
  timestamp?: string
}

/** 分页响应 */
export interface PaginatedResponse<T> {
  items: T[]
  page: number
  page_size: number
  total: number
  has_more: boolean
}

// ── 枚举 ──────────────────────────────────────────

export type ItemType = 'departure' | 'transport' | 'attraction' | 'lunch' | 'dinner' | 'hotel' | 'rest' | 'return'
export type PlaceType = 'attraction' | 'hotel' | 'restaurant' | 'custom_location'
export type Severity = 'info' | 'warning' | 'error'
export type ItineraryStatus = 'draft' | 'routing' | 'validating' | 'adjusting' | 'passed' | 'failed'

// ── 行程模型 ──────────────────────────────────────

export interface ItineraryItem {
  item_id: string
  day: number
  item_type: ItemType
  place_id: string | null
  start_time: string
  end_time: string
  duration_minutes: number
  route_from_previous_id: string | null
  cost_per_person: number
  total_cost: number
  locked: boolean
  note: string | null
}

export interface ItineraryDay {
  day: number
  date: string
  items: ItineraryItem[]
  daily_cost: number
  walking_distance_m: number
  start_time: string
  end_time: string
}

export interface Itinerary {
  itinerary_id: string
  session_id: string
  version: number
  parent_version: number | null
  requirements_snapshot: Record<string, unknown>
  days: ItineraryDay[]
  hotel_place_id: string | null
  total_cost: number
  status: ItineraryStatus
  created_at: string | null
}

// ── 校验模型 ──────────────────────────────────────

export interface ValidationIssue {
  code: string
  severity: Severity
  day: number | null
  item_id: string | null
  message: string
  suggestion: string | null
}

export interface HardConstraintEvaluation {
  passed: boolean
  issues: ValidationIssue[]
  metrics: {
    budget_match_rate: number
    interest_coverage_rate: number
    must_visit_coverage_rate: number
    time_valid: boolean
    walking_limit_valid: boolean
  }
}

export interface SoftPreferenceIssue {
  preference: string
  assessment: string
  suggestion: string
  confidence: number
}

export interface SoftPreferenceEvaluation {
  soft_preference_passed: boolean
  issues: SoftPreferenceIssue[]
  overall_assessment: string | null
}

// ── 预算模型 ──────────────────────────────────────

export interface BudgetSummary {
  hotel_cost: number
  ticket_cost: number
  meal_cost: number
  transport_cost: number
  other_cost: number
  total_cost: number
  total_budget: number
  remaining_budget: number
  over_budget: boolean
}

// ── 对比模型 ──────────────────────────────────────

export interface TripChange {
  change_type: 'replace' | 'delete' | 'add' | 'reorder'
  before_item_id: string | null
  after_item_id: string | null
  before_place_id: string | null
  after_place_id: string | null
  reason: string | null
  cost_change: number
  distance_change_m: number
}

export interface TripDiff {
  from_version: number
  to_version: number
  affected_days: number[]
  changes: TripChange[]
  unchanged_item_ids: string[]
}

// ── 评价系统统一输出模型 ─────────────────────────

/** 重规划指导指令 */
export interface ReplanDirective {
  target_day: number
  target_item_ids: string[]
  action: 'replace' | 'remove' | 'reschedule' | 'add_buffer' | 'reduce_intensity' | 'change_mode' | 'adjust_time' | 'split_day' | 'merge_day'
  reason: string
  suggestion: string
  priority: number  // 1=高(阻断) 2=中(建议) 3=低(可忽略)
}

/** 综合评价结果 —— EvaluationAgent 统一输出 */
export interface OverallEvaluationResult {
  passed: boolean
  soft_preference_passed: boolean
  overall_score: number  // 0.0 ~ 1.0
  hard_issues: ValidationIssue[]
  soft_issues: SoftPreferenceIssue[]
  metrics: {
    budget_match_rate: number
    interest_coverage_rate: number
    must_visit_coverage_rate: number
    time_valid: boolean
    walking_limit_valid: boolean
  }
  time_reasonableness_score: number
  replan_directives: ReplanDirective[]
  hard_evaluation_raw?: Record<string, unknown> | null
  soft_evaluation_raw?: Record<string, unknown> | null
}
