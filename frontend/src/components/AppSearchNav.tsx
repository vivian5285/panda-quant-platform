import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search } from 'lucide-react'
import { useI18n } from '../i18n'

export interface SearchNavItem {
  to: string
  label: string
  keywords?: string
}

interface Props {
  items: SearchNavItem[]
  onNavigate?: () => void
}

export default function AppSearchNav({ items, onNavigate }: Props) {
  const t = useI18n(s => s.t)
  const navigate = useNavigate()
  const wrapRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [activeIdx, setActiveIdx] = useState(0)

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return items.slice(0, 8)
    return items.filter(item => {
      const hay = `${item.label} ${item.keywords || ''} ${item.to}`.toLowerCase()
      return hay.includes(q)
    }).slice(0, 10)
  }, [query, items])

  useEffect(() => {
    setActiveIdx(0)
  }, [query])

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const go = (to: string) => {
    navigate(to)
    setQuery('')
    setOpen(false)
    onNavigate?.()
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open && e.key !== 'Escape') setOpen(true)
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx(i => Math.min(i + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter' && results[activeIdx]) {
      e.preventDefault()
      go(results[activeIdx].to)
    } else if (e.key === 'Escape') {
      setOpen(false)
      inputRef.current?.blur()
    }
  }

  return (
    <div className="app-search-wrap" ref={wrapRef}>
      <Search size={16} className="app-search-icon" />
      <input
        ref={inputRef}
        className="app-search input"
        placeholder={t('app.search')}
        value={query}
        onChange={e => { setQuery(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        autoComplete="off"
        spellCheck={false}
      />
      {open && (
        <div className="app-search-dropdown glass">
          {results.length === 0 ? (
            <p className="app-search-empty">{t('app.searchEmpty')}</p>
          ) : results.map((item, i) => (
            <button
              key={item.to}
              type="button"
              className={`app-search-item${i === activeIdx ? ' active' : ''}`}
              onMouseEnter={() => setActiveIdx(i)}
              onClick={() => go(item.to)}
            >
              <span>{item.label}</span>
              <small>{item.to}</small>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
