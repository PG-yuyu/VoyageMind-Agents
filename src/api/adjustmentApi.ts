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
}): Promise<ApiResponse> {
  const resp = await fetch(`${BASE}/modify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return resp.json()
}
