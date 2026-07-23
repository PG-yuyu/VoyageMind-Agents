/**
 * 行程状态管理 (Pinia Store)
 *
 * 管理行程的完整状态: 行程数据、预算、校验结果、版本等
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  Itinerary,
  ItineraryDay,
  HardConstraintEvaluation,
  SoftPreferenceEvaluation,
  BudgetSummary,
  TripDiff,
} from '../types/common'

export const useItineraryStore = defineStore('itinerary', () => {
  // ── 状态 ────────────────────────────────────────
  const itinerary = ref<Itinerary | null>(null)
  const budget = ref<BudgetSummary | null>(null)
  const hardEvaluation = ref<HardConstraintEvaluation | null>(null)
  const softEvaluation = ref<SoftPreferenceEvaluation | null>(null)
  const tripDiff = ref<TripDiff | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  // ── 计算属性 ────────────────────────────────────
  const currentVersion = computed(() => itinerary.value?.version ?? 0)
  const totalDays = computed(() => itinerary.value?.days.length ?? 0)
  const hasItinerary = computed(() => itinerary.value !== null)
  const totalCost = computed(() => itinerary.value?.total_cost ?? 0)
  const isOverBudget = computed(() => budget.value?.over_budget ?? false)
  const validationPassed = computed(() => hardEvaluation.value?.passed ?? true)
  const softPreferencePassed = computed(
    () => softEvaluation.value?.soft_preference_passed ?? true,
  )

  /** 当天行程 */
  function getDay(dayNum: number): ItineraryDay | undefined {
    return itinerary.value?.days.find((d) => d.day === dayNum)
  }

  /** 当天的校验问题 */
  function getDayIssues(dayNum: number) {
    return hardEvaluation.value?.issues.filter((i) => i.day === dayNum) ?? []
  }

  // ── 操作 ────────────────────────────────────────
  function setItinerary(data: Itinerary) {
    itinerary.value = data
    error.value = null
  }

  function setBudget(data: BudgetSummary) {
    budget.value = data
  }

  function setHardEvaluation(data: HardConstraintEvaluation) {
    hardEvaluation.value = data
  }

  function setSoftEvaluation(data: SoftPreferenceEvaluation) {
    softEvaluation.value = data
  }

  function setTripDiff(data: TripDiff) {
    tripDiff.value = data
  }

  function setLoading(val: boolean) {
    loading.value = val
  }

  function setError(msg: string | null) {
    error.value = msg
  }

  function reset() {
    itinerary.value = null
    budget.value = null
    hardEvaluation.value = null
    softEvaluation.value = null
    tripDiff.value = null
    loading.value = false
    error.value = null
  }

  return {
    // 状态
    itinerary,
    budget,
    hardEvaluation,
    softEvaluation,
    tripDiff,
    loading,
    error,
    // 计算
    currentVersion,
    totalDays,
    hasItinerary,
    totalCost,
    isOverBudget,
    validationPassed,
    softPreferencePassed,
    getDay,
    getDayIssues,
    // 操作
    setItinerary,
    setBudget,
    setHardEvaluation,
    setSoftEvaluation,
    setTripDiff,
    setLoading,
    setError,
    reset,
  }
})
