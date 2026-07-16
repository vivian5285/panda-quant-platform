/** Qty display unit for dual-symbol perps (ETH / XAU). */
export function qtyUnitForSymbol(symbol?: string | null): string {
  const s = String(symbol || '').toUpperCase()
  if (s.includes('XAU') || s.includes('GOLD') || s.includes('PAXG')) return 'XAU'
  if (s.includes('ETH')) return 'ETH'
  return s.replace('USDT', '') || '—'
}

export function shortSymbol(symbol?: string | null): string {
  const s = String(symbol || 'ETHUSDT').toUpperCase()
  if (s.includes('XAU')) return 'XAUUSDT'
  if (s.includes('ETH')) return 'ETHUSDT'
  return s || 'ETHUSDT'
}

export function isExchangeFillEvent(eventType?: string | null): boolean {
  const t = String(eventType || '').toUpperCase()
  return t === 'BINANCE_FILL' || t === 'EXCHANGE_FILL' || t.endsWith('_FILL')
}
