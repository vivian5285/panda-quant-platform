import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

function leafPaths(filePath) {
  const text = fs.readFileSync(filePath, 'utf8')
  const lines = text.split('\n')
  const paths = []
  const stack = []
  for (const line of lines) {
    const m = line.match(/^(\s*)([\w]+):\s*(.+)$/)
    if (!m) continue
    const indent = m[1].length
    const key = m[2]
    const val = m[3].trim()
    while (stack.length && stack[stack.length - 1].indent >= indent) stack.pop()
    stack.push({ indent, key })
    if (val.startsWith('"') || val.startsWith("'")) {
      paths.push(stack.map(s => s.key).join('.'))
    }
  }
  return paths
}

const zhPath = path.join(__dirname, '../src/i18n/locales/framer-zh.ts')
const enPath = path.join(__dirname, '../src/i18n/locales/framer-en.ts')
const zh = new Set(leafPaths(zhPath))
const en = new Set(leafPaths(enPath))
const missingEn = [...zh].filter(k => !en.has(k)).sort()
const missingZh = [...en].filter(k => !zh.has(k)).sort()
console.log('framer zh keys:', zh.size, 'en keys:', en.size)
console.log('Missing in en:', missingEn.length)
missingEn.forEach(k => console.log('  -', k))
console.log('Missing in zh:', missingZh.length)
missingZh.forEach(k => console.log('  -', k))
