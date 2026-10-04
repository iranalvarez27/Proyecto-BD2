export function layoutBPlus(tree) {
  if (!tree || !tree.nodes || !tree.nodes.length) {
    return { nodes: [], edges: [], width: 420, height: 160 };
  }
  const byId = Object.fromEntries(tree.nodes.map((n) => [n.id, n]));
  const levels = [];
  const walk = (id, depth) => {
    if (!levels[depth]) levels[depth] = [];
    levels[depth].push(id);
    (byId[id]?.children || []).forEach((child) => walk(child, depth + 1));
  };
  walk(tree.root, 0);

  const NODE_H = 38;
  const GAP_Y = 82;
  const keyWidth = (node) => Math.min(560, Math.max(120, Math.min(node.keys?.length || 0, 16) * 30 + 48));

  const pos = {};
  const leaves = levels[levels.length - 1] || [];
  let cursor = 24;
  leaves.forEach((id) => {
    const node = byId[id];
    const w = keyWidth(node);
    pos[id] = { x: cursor, y: (levels.length - 1) * GAP_Y + 18, w, h: NODE_H };
    cursor += w + 18;
  });

  for (let depth = levels.length - 2; depth >= 0; depth -= 1) {
    levels[depth].forEach((id) => {
      const node = byId[id];
      const kids = node.children || [];
      const w = keyWidth(node);
      const placed = kids.map((cid) => pos[cid]).filter(Boolean);
      if (placed.length) {
        const left = placed[0].x;
        const right = placed[placed.length - 1].x + placed[placed.length - 1].w;
        pos[id] = { x: (left + right) / 2 - w / 2, y: depth * GAP_Y + 18, w, h: NODE_H };
      } else {
        pos[id] = { x: 24, y: depth * GAP_Y + 18, w, h: NODE_H };
      }
    });
  }

  const minX = Math.min(...Object.values(pos).map((p) => p.x), 16);
  if (minX < 16) {
    const dx = 16 - minX;
    Object.values(pos).forEach((p) => { p.x += dx; });
  }

  const nodes = tree.nodes.map((n) => ({ ...n, ...pos[n.id] }));
  const edges = [];
  tree.nodes.forEach((n) => {
    (n.children || []).forEach((cid) => edges.push({ from: n.id, to: cid }));
  });
  const width = Math.max(420, ...nodes.map((n) => (n.x || 0) + (n.w || 0))) + 28;
  const height = Math.max(160, levels.length * GAP_Y + 36);
  return { nodes, edges, width, height };
}

export function bitsOf(index, depth) {
  if (depth <= 0) return '0';
  return index.toString(2).padStart(depth, '0');
}

export function formatKey(key) {
  if (key === null || key === undefined) return '∅';
  const text = String(key);
  return text.length > 18 ? `${text.slice(0, 16)}…` : text;
}
