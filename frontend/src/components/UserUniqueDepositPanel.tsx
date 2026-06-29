import { useEffect, useState } from 'react'
import QRCode from 'qrcode'
import { Copy, Check } from 'lucide-react'
import GlassCard from './GlassCard'
import { useI18n } from '../i18n'

type Addr = { chain: string; address: string; address_group?: string }

export default function UserUniqueDepositPanel({ addresses }: { addresses: Addr[] }) {
  const t = useI18n(s => s.t)
  const [qrMap, setQrMap] = useState<Record<string, string>>({})
  const [copied, setCopied] = useState('')

  useEffect(() => {
    const chains = [...new Set(addresses.map(a => a.chain))]
    chains.forEach(chain => {
      const addr = addresses.find(a => a.chain === chain)?.address
      if (!addr) return
      QRCode.toDataURL(addr, { width: 160, margin: 2, color: { dark: '#0f172a', light: '#ffffff' } })
        .then(url => setQrMap(prev => ({ ...prev, [chain]: url })))
        .catch(() => {})
    })
  }, [addresses])

  const copy = (text: string, key: string) => {
    navigator.clipboard.writeText(text)
    setCopied(key)
    setTimeout(() => setCopied(''), 2000)
  }

  const shown = addresses.filter((a, i, arr) => arr.findIndex(x => x.chain === a.chain) === i)

  return (
    <GlassCard className="p-6 section-mb-lg">
      <h3 className="panel-title-sm mb-xs">{t('settlements.myUniqueAddr')}</h3>
      <p className="text-muted text-sm section-mb-md">{t('settlements.uniqueAddrHint')}</p>
      {shown.length === 0 ? (
        <p className="text-muted">{t('settlements.noUniqueAddr')}</p>
      ) : (
        <div className="log-list-stack">
          {shown.map(a => (
            <div key={a.chain} className="panel-muted-lg addr-panel-row">
              <div className="addr-panel-main">
                <div>
                  <span className="badge badge-green">{a.chain}</span>
                  {a.address_group === 'EVM' && (
                    <span className="text-muted label-inline">{t('settlements.evmSharedNote')}</span>
                  )}
                  <p className="mono-text-sm">{a.address}</p>
                </div>
                {qrMap[a.chain] && (
                  <img className="deposit-qr-settlement" src={qrMap[a.chain]} alt={a.chain} />
                )}
              </div>
              <button type="button" className="btn btn-ghost" onClick={() => copy(a.address, a.chain)}>
                {copied === a.chain ? <Check size={14} /> : <Copy size={14} />}
                {copied === a.chain ? t('settlements.copied') : t('settlements.copyAddr')}
              </button>
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  )
}
