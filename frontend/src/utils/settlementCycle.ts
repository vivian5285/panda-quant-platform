/** Display label for settlement billing cycle (30d rolling periods). */
export function formatSettlementCycle(
  days: number | undefined | null,
  t: (key: string, params?: Record<string, string | number>) => string,
): string {
  const d = days ?? 30
  const periods = Math.max(1, Math.ceil(d / 30))
  if (periods > 1) return t('settlements.cycleMultiPeriod', { n: periods })
  return t('settlements.cycleMonthly')
}
