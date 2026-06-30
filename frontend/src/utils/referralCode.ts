/** Display referral code with GEMINI branding (legacy PANDA- codes normalized). */
export function displayReferralCode(code: string | undefined | null): string {
  if (!code) return '—'
  const upper = code.trim().toUpperCase()
  if (upper.startsWith('PANDA-')) return 'GEMINI-' + upper.slice(6)
  return upper
}
