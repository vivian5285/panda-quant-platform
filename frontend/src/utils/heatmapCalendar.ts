export interface DailyPnl {
  date: string
  pnl: number
}

/** GitHub-style calendar heatmap data for ECharts calendar coordinateSystem */
export function buildCalendarHeatmap(series: DailyPnl[]) {
  if (!series.length) {
    const today = new Date()
    const start = new Date(today)
    start.setDate(start.getDate() - 84)
    return {
      range: [fmtDate(start), fmtDate(today)],
      data: [] as [string, number][],
      max: 100,
      min: -100,
    }
  }

  const sorted = [...series].sort((a, b) => a.date.localeCompare(b.date))
  const slice = sorted.slice(-120)
  const values = slice.map(d => d.pnl)
  const maxAbs = Math.max(...values.map(Math.abs), 1)

  return {
    range: [slice[0].date, slice[slice.length - 1].date],
    data: slice.map(d => [d.date, d.pnl] as [string, number]),
    max: maxAbs,
    min: -maxAbs,
  }
}

function fmtDate(d: Date) {
  return d.toISOString().slice(0, 10)
}
