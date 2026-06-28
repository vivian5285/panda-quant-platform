import LegalLayout from '../components/LegalLayout'

const SECTIONS = ['intro', 'service', 'api', 'fees', 'risk', 'referral', 'termination', 'law'] as const

export default function Terms() {
  return (
    <LegalLayout
      ns="terms"
      titleKey="legal.terms.title"
      updatedKey="legal.terms.updated"
      sectionKeys={SECTIONS}
    />
  )
}
