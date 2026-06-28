import axios from 'axios'

const api = axios.create({ baseURL: '/api', timeout: 30000 })

function requestLocale(): string {
  const saved = localStorage.getItem('locale')
  return saved === 'en' ? 'en' : 'zh-CN'
}

api.interceptors.request.use((config) => {
  config.headers['Accept-Language'] = requestLocale()
  return config
})

export default api
