/** Map a Monte Carlo outcome value to the histogram bucket label from the API. */
export function mcBucketLabel(value: number, hist: { label: string }[]): string {
  if (!hist.length) return ''
  const starts = hist.map(h => Number(h.label))
  for (let i = starts.length - 1; i >= 0; i--) {
    if (value >= starts[i]) return hist[i].label
  }
  return hist[0].label
}
