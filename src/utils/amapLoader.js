let amapLoadPromise = null

export function getAmapJsConfig() {
  return {
    key: import.meta.env.VITE_AMAP_JS_KEY || '',
    securityJsCode: import.meta.env.VITE_AMAP_SECURITY_CODE || ''
  }
}

export function loadAmapJsApi() {
  const { key, securityJsCode } = getAmapJsConfig()

  if (window.AMap) {
    return Promise.resolve(window.AMap)
  }

  if (!key) {
    return Promise.reject(new Error('未配置高德 JS API Key'))
  }

  if (amapLoadPromise) {
    return amapLoadPromise
  }

  if (securityJsCode) {
    window._AMapSecurityConfig = {
      securityJsCode
    }
  }

  amapLoadPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(key)}&plugin=AMap.Scale,AMap.ToolBar`
    script.async = true
    script.onload = () => {
      if (window.AMap) {
        resolve(window.AMap)
      } else {
        reject(new Error('高德 JS API 加载完成但 AMap 对象不可用'))
      }
    }
    script.onerror = () => reject(new Error('高德 JS API 加载失败'))
    document.head.appendChild(script)
  })

  return amapLoadPromise
}
