/**
 * 行程 API 封装
 *
 * 基础路径: /api/v1/itineraries
 */
import type { ApiResponse } from '../types/common'

const BASE = '/api/v1/itineraries'

/** 生成初始行程 */
export async function generateItinerary(params: {
  requirements: Record<string, unknown>
  hotel?: Record<string, unknown> | null
  attractions?: Record<string, unknown>[]
  restaurants?: Record<string, unknown>[]
  max_candidates_per_day?: number
}): Promise<ApiResponse> {
  const resp = await fetch(`${BASE}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  return resp.json()
}

/** 获取行程（可指定版本） */
export async function getItinerary(
  itineraryId: string,
  version?: number,
): Promise<ApiResponse> {
  const url = version
    ? `${BASE}/${itineraryId}?version=${version}`
    : `${BASE}/${itineraryId}`
  const resp = await fetch(url)
  return resp.json()
}

/** 计算预算 */
export async function calculateBudget(data: {
  itinerary: Record<string, unknown>
  requirements: Record<string, unknown>
}): Promise<ApiResponse> {
  const resp = await fetch(`${BASE}/calculate-budget`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return resp.json()
}

/** 校验行程 */
export async function validateItinerary(data: {
  itinerary: Record<string, unknown>
  requirements: Record<string, unknown>
  places?: Record<string, unknown>[]
  routes?: Record<string, unknown>[]
}): Promise<ApiResponse> {
  const resp = await fetch(`${BASE}/validate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return resp.json()
}
