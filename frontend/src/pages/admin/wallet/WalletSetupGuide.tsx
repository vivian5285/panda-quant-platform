import { useI18n } from '../../../i18n'

export type WalletGuideKey = 'cheatsheet' | 'hd' | 'cold' | 'hot' | 'gas' | 'platform' | 'rpc'

function pickSteps(t: (k: string) => string, prefix: string, max = 8): string[] {
  const out: string[] = []
  for (let i = 1; i <= max; i++) {
    const key = `${prefix}.step${i}`
    const val = t(key)
    if (!val || val === key) break
    out.push(val)
  }
  return out
}

function pickWallets(t: (k: string) => string, prefix: string, max = 5): string[] {
  const out: string[] = []
  for (let i = 1; i <= max; i++) {
    const key = `${prefix}.wallet${i}`
    const val = t(key)
    if (!val || val === key) break
    out.push(val)
  }
  return out
}

function pickProvides(t: (k: string) => string, prefix: string, max = 5): string[] {
  const out: string[] = []
  for (let i = 1; i <= max; i++) {
    const key = `${prefix}.provide${i}`
    const val = t(key)
    if (!val || val === key) break
    out.push(val)
  }
  return out
}

function pickCheatsheetRows(t: (k: string) => string, prefix: string, max = 8): string[] {
  const out: string[] = []
  for (let i = 1; i <= max; i++) {
    const key = `${prefix}.row${i}`
    const val = t(key)
    if (!val || val === key) break
    out.push(val)
  }
  return out
}

export default function WalletSetupGuide({ guide }: { guide: WalletGuideKey }) {
  const t = useI18n(s => s.t)
  const prefix = `admin.walletHub.setupGuides.${guide}`
  const title = t(`${prefix}.title`)

  if (guide === 'cheatsheet') {
    const rows = pickCheatsheetRows(t, prefix)
    if (!rows.length) return null
    return (
      <div className="wallet-setup-guide wallet-setup-cheatsheet section-mb-md">
        <h4 className="wallet-setup-title">{title}</h4>
        <ul className="wallet-setup-cheatsheet-list">
          {rows.map(row => <li key={row}>{row}</li>)}
        </ul>
      </div>
    )
  }

  const wallets = pickWallets(t, prefix)
  const steps = pickSteps(t, prefix)
  const provides = pickProvides(t, prefix)
  const warn = t(`${prefix}.warn`)
  const hasWarn = warn && warn !== `${prefix}.warn`
  const recommendedTitle = t(`${prefix}.recommendedTitle`)
  const stepsTitle = t(`${prefix}.stepsTitle`)
  const provideTitle = t(`${prefix}.provideTitle`)

  return (
    <div className="wallet-setup-guide section-mb-md">
      <h4 className="wallet-setup-title">{title}</h4>

      {wallets.length > 0 && (
        <div className="wallet-setup-block">
          <p className="wallet-setup-label">{recommendedTitle}</p>
          <ul className="wallet-setup-list">
            {wallets.map(w => <li key={w}>{w}</li>)}
          </ul>
        </div>
      )}

      {steps.length > 0 && (
        <div className="wallet-setup-block">
          <p className="wallet-setup-label">{stepsTitle}</p>
          <ol className="wallet-setup-steps">
            {steps.map(s => <li key={s}>{s}</li>)}
          </ol>
        </div>
      )}

      {provides.length > 0 && (
        <div className="wallet-setup-block wallet-setup-provide">
          <p className="wallet-setup-label">{provideTitle}</p>
          <ul className="wallet-setup-list">
            {provides.map(p => <li key={p}>{p}</li>)}
          </ul>
        </div>
      )}

      {hasWarn && <p className="wallet-setup-warn text-sm">{warn}</p>}
    </div>
  )
}
