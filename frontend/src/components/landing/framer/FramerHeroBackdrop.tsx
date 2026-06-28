/** Framer-style hero ambient background — grid drift + soft orbs */
export default function FramerHeroBackdrop() {
  return (
    <div className="framer-hero-backdrop" aria-hidden>
      <div className="framer-hero-grid" />
      <div className="framer-hero-orb framer-hero-orb-a" />
      <div className="framer-hero-orb framer-hero-orb-b" />
      <div className="framer-hero-orb framer-hero-orb-c" />
      <div className="framer-hero-vignette" />
    </div>
  )
}
