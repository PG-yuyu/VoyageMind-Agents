# schemas - 城市自由行智能规划系统 · 公共数据模型
# 三个成员共用，禁止各自定义同名对象
#
# v2 拆分（按领域）:
#   common         - ApiResponse, PaginatedResponse, 枚举, ExplicitConstraint
#   itinerary      - ItineraryItem, ItineraryDay, Itinerary
#   budget         - BudgetSummary
#   evaluation     - HardConstraintEvaluation, ValidationIssue, EvaluationMetrics
#   modification   - ModificationRequest
#   version        - TripChange, TripDiff
#   planning_policy     - ItineraryPlanningPolicy (LLM 规划策略)
#   preference_evaluation - SoftPreferenceEvaluation (LLM 软偏好评价)
