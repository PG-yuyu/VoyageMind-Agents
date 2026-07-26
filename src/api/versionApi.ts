/**
 * 版本管理 API 封装
 */
import type { ApiResponse } from '../types/common'

const BASE = '/api/v1/itineraries'

/** 获取版本列表 */
export async function listVersions(
  itineraryId: string,
): Promise<ApiResponse> {
  const resp = await fetch(`${BASE}/${itineraryId}/versions`)
  return resp.json()
}

/** 获取指定版本 */
export async function getVersion(
  itineraryId: string,
  version: number,
): Promise<ApiResponse> {
  const resp = await fetch(`${BASE}/${itineraryId}/versions/${version}`)
  return resp.json()
}

/** 获取版本差异 */
export async function getDiff(
  itineraryId: string,
  fromVersion: number,
  toVersion: number,
): Promise<ApiResponse> {
  const resp = await fetch(
    `${BASE}/${itineraryId}/diff?from_version=${fromVersion}&to_version=${toVersion}`,
  )
  return resp.json()
}
