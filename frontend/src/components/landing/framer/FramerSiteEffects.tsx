/** Ambient tech-blue orbs + light-line marquees (Framer.com-style depth on pure black) */
export default function FramerSiteEffects() {
  return (
    <div className="framer-site-fx" aria-hidden>
      <div className="framer-fx-orb framer-fx-orb-a" />
      <div className="framer-fx-orb framer-fx-orb-b" />
      <div className="framer-fx-orb framer-fx-orb-c" />
      <div className="framer-fx-line-wrap framer-fx-line-top">
        <div className="framer-fx-line-track" />
      </div>
      <div className="framer-fx-line-wrap framer-fx-line-mid">
        <div className="framer-fx-line-track framer-fx-line-reverse" />
      </div>
    </div>
  )
}
