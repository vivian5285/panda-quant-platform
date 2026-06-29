/** Public site media — override demo video via VITE_DEMO_VIDEO_URL at build time */
export const SITE_MEDIA = {
  demoVideo: import.meta.env.VITE_DEMO_VIDEO_URL || '/demo/console-demo.webm',
  demoPoster: '/demo/console-poster.svg',
} as const
