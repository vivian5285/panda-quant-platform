import LegalLayout from '../components/LegalLayout'

const SECTIONS = ['intro', 'collect', 'use', 'security', 'cookies', 'rights', 'contact'] as const

export default function Privacy() {
  return (
    <LegalLayout
      ns="privacy"
      titleKey="legal.privacy.title"
      updatedKey="legal.privacy.updated"
      sectionKeys={SECTIONS}
    />
  )
}
