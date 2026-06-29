/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DEMO_VIDEO_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
