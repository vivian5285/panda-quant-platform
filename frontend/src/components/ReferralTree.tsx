import { useEffect, useState } from 'react'
import { useI18n } from '../i18n'
import { referralApi } from '../api'
import GlassCard from './GlassCard'

interface TreeNode {
  id: number
  uid?: string
  label: string
  level: number
  children?: TreeNode[]
}

function Node({ node, depth = 0 }: { node: TreeNode; depth?: number }) {
  return (
    <div className={`ref-tree-node depth-${depth}`}>
      <div className="ref-tree-card glass">
        <span className="ref-tree-level">L{node.level}</span>
        <strong>{node.label}</strong>
        {node.uid && <small>{node.uid}</small>}
      </div>
      {node.children && node.children.length > 0 && (
        <div className="ref-tree-children">
          {node.children.map(c => <Node key={c.id} node={c} depth={depth + 1} />)}
        </div>
      )}
    </div>
  )
}

export default function ReferralTree() {
  const t = useI18n(s => s.t)
  const [tree, setTree] = useState<TreeNode | null>(null)

  useEffect(() => {
    referralApi.tree().then(r => setTree(r.root)).catch(() => {})
  }, [])

  if (!tree) return null

  return (
    <GlassCard className="p-6 section-mb-lg">
      <h3 className="card-heading">{t('referrals.treeTitle')}</h3>
      <p className="text-muted text-sm mb-md">{t('referrals.treeSubtitle')}</p>
      <div className="ref-tree-root">
        <Node node={tree} />
      </div>
    </GlassCard>
  )
}
