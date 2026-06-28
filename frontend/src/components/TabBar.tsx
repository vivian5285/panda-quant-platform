interface Tab {
  key: string
  label: string
}

interface Props {
  tabs: Tab[]
  active: string
  onChange: (key: string) => void
  trailing?: React.ReactNode
}

export default function TabBar({ tabs, active, onChange, trailing }: Props) {
  return (
    <div className="tab-bar-row">
      <div className="tab-bar">
        {tabs.map(t => (
          <button
            key={t.key}
            type="button"
            className={`tab-bar-item${active === t.key ? ' active' : ''}`}
            onClick={() => onChange(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {trailing}
    </div>
  )
}
