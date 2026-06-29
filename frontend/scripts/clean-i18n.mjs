import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const localesDir = path.join(__dirname, '../src/i18n/locales')
const removeTopKeys = new Set(['logs', 'billing', 'hero', 'strategies', 'signals', 'saas', 'landing'])
const removeFramerKeys = new Set(['bento', 'shipped', 'partners', 'testimonials', 'cases', 'devices'])

function formatValue(v, indent) {
  const pad = '  '.repeat(indent)
  const padIn = '  '.repeat(indent + 1)
  if (v === null || typeof v !== 'object') {
    if (typeof v === 'string') return JSON.stringify(v)
    return String(v)
  }
  if (Array.isArray(v)) return JSON.stringify(v)
  const keys = Object.keys(v)
  if (keys.length === 0) return '{}'
  const inner = keys.map(k => `${padIn}${k}: ${formatValue(v[k], indent + 1)}`).join(',\n')
  return `{\n${inner}\n${pad}}`
}

function rebuild(obj, framerKey) {
  const lines = ['export default {']
  const entries = Object.entries(obj)
  entries.forEach(([k, v], i) => {
    const comma = i < entries.length - 1 ? ',' : ''
    if (k === 'framer') {
      lines.push(`  framer: ${framerKey},`)
      return
    }
    lines.push(`  ${k}: ${formatValue(v, 1)}${comma}`)
  })
  lines.push('} as const', '')
  return lines.join('\n')
}

function pruneFramer(file) {
  const s = fs.readFileSync(file, 'utf8')
  const m = s.match(/export default (\{[\s\S]*\})\s*$/)
  if (!m) throw new Error(`parse fail: ${file}`)
  const obj = new Function(`return ${m[1]}`)()
  for (const k of removeFramerKeys) delete obj[k]
  const lines = ['export default ' + formatValue(obj, 0) + '\n']
  fs.writeFileSync(file, lines.join(''))
  console.log('pruned framer orphans in', path.basename(file))
}

for (const name of ['zh.ts', 'en.ts']) {
  const file = path.join(localesDir, name)
  const s = fs.readFileSync(file, 'utf8')
  const importLine = s.match(/^import[^\n]+\n/)?.[0] || ''
  const m = s.match(/export default (\{[\s\S]*\})\s*as const/)
  if (!m) throw new Error(`parse fail: ${file}`)
  const body = m[1].replace(/framer:\s*framerZh/g, 'framer: null').replace(/framer:\s*framerEn/g, 'framer: null')
  const obj = new Function(`return ${body}`)()
  for (const k of removeTopKeys) delete obj[k]
  const framerKey = name === 'zh.ts' ? 'framerZh' : 'framerEn'
  fs.writeFileSync(file, importLine + rebuild(obj, framerKey))
  console.log('cleaned', name)
}

for (const name of ['framer-zh.ts', 'framer-en.ts']) {
  pruneFramer(path.join(localesDir, name))
}
