/** Public site media — override demo video via VITE_DEMO_VIDEO_URL at build time */
export const SITE_MEDIA = {
  demoVideo: import.meta.env.VITE_DEMO_VIDEO_URL || '/demo/console-demo.webm',
  demoPoster: '/demo/console-poster.svg',
} as const

/** 平台对外域名与邮箱（与 backend/.env 及 Hostinger 企业邮一致） */
export const SITE_DOMAIN = 'twinstar.pro'
export const SITE_URL = `https://${SITE_DOMAIN}`

export const NOREPLY_EMAIL = `noreply@${SITE_DOMAIN}`
export const SUPPORT_EMAIL = `support@${SITE_DOMAIN}`
export const PRIVACY_EMAIL = `privacy@${SITE_DOMAIN}`
export const ADMIN_EMAIL = `admin@${SITE_DOMAIN}`
