/** Display label for settlement billing cycle (monthly = 30d primary, 35d extended grace). */
export function formatSettlementCycle(
  days: number | undefined | null,
  t: (key: string) => string,
): string {
  const d = days ?? 30
  if (d >= 35) return t('settlements.cycleExtended')
  if (d >= 28) return t('settlements.cycleMonthly')
  return `${d}${t('common.days')}`
}
