import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles/design-tokens.css'
import './styles/global.css'
import './styles/framer-landing.css'
import { initI18n } from './i18n'
import { initTheme } from './store/theme'

initI18n()
initTheme()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
