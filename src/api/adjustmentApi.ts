/**
 * 调整 & 重规划 API 封装
 */
import type { ApiResponse } from '../types/common'

const BASE = '/api/v1/itineraries'

/** 用户主动修改行程 */
export async function modifyItinerary(data: {
  session_id: string
  itinerary_id: string
  base_version: number
  target_day?: number | null
  target_item_id?: string | null
  action: string
  new_constraints?: Record<string, unknown>
  original_text?: string | null
  current_itinerary?: Record<string, unknown> | null
}): Promise<ApiResponse> {
  const resp = await fetch(`${BASE}/modify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return resp.json()
}

/** 智能体生成修改建议预览：只分析，不直接替换当前行程 */
export async function previewItineraryAdjustment(data: {
  session_id: string
  target_day?: number | null
  action: string
  original_text: string
  current_itinerary: Record<string, unknown>
}): Promise<ApiResponse> {
  const resp = await fetch(`${BASE}/adjustment-preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return resp.json()
}
