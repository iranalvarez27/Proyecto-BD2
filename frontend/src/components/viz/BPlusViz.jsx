import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Cpu, HardDrive, Route } from 'lucide-react';
import PlayerBar, { eventLabel } from './PlayerBar';

const STRUCTURAL = new Set(['split', 'merge', 'borrow', 'new_root', 'shrink_root']);

// Geometría del dibujo (px)
const CELL_H = 28;
const PAD = 6;
const LABEL_H = 16;
const LEVEL_GAP = 100;
const SIBLING_GAP = 26;
const MAX_CELLS = 10;
const MARGIN = 20;
const BASE_DELAY = { didactic: 1600, disk: 1800 };

function shortKey(key) {
  if (key === null || key === undefined) return '∅';
  const text = String(key);
  return text.length > 10 ? `${text.slice(0, 9)}…` : text;
}

function highlightedPages(events) {
  const ids = new Set();
  (events || []).forEach((event) => {
    ['page_id', 'new_page_id', 'old_root', 'kept', 'absorbed', 'from_id', 'to_id', 'parent']
      .forEach((key) => {
        if (event?.[key] != null) ids.add(event[key]);
      });
  });
  return ids;
}

function buildFrames(animation, staticView, viewMode) {
  const diskAfter = animation?.disk || staticView?.disk;
  if (!diskAfter) return { frames: [], fallback: null, didactic: false };

  if (viewMode === 'didactic' && animation?.didactic) {
    const model = animation.didactic;
    const frames = [];
    if (model.before) frames.push({ event: null, events: [], tree: model.before });
    (model.frames || []).forEach((frame) => frames.push({
      ...frame,
      events: frame.event ? [frame.event] : [],
    }));
    return { frames, fallback: model.after, didactic: true };
  }

  const diskBefore = animation?.disk_before;
  const events = animation?.disk_events || [];
  const changed = animation?.changed || [];
  if (!diskBefore && !events.length) return { frames: [], fallback: diskAfter, didactic: false };

  const frames = [];
  if (diskBefore) frames.push({ event: null, events: [], tree: diskBefore });
  const fallbackEvent = {
    type: changed.length ? 'insert' : 'update',
    key: changed[0],
    page_id: diskAfter.root,
  };
  const primary = [...events].reverse().find((event) => STRUCTURAL.has(event.type))
    || events.at(-1)
    || fallbackEvent;
  frames.push({
    event: primary,
    events: events.length ? events : [fallbackEvent],
    tree: diskAfter,
  });
  return { frames, fallback: diskAfter, didactic: false };
}

/* ---------- Layout: nodos con una celda por clave ---------- */

function layoutTree(tree) {
  if (!tree?.nodes?.length) return { nodes: [], cells: [], byId: {}, width: 420, height: 160, cellW: 34 };
  const maxKeys = tree.order ? tree.order - 1 : null;
  const raw = Object.fromEntries(tree.nodes.map((node) => [node.id, node]));
  const levels = [];
  const depthOf = {};
  const walk = (id, depth) => {
    const node = raw[id];
    if (!node || depthOf[id] != null) return;
    depthOf[id] = depth;
    (levels[depth] ||= []).push(id);
    (node.children || []).forEach((child) => walk(child, depth + 1));
  };
  walk(tree.root, 0);
  if (!levels.length) return { nodes: [], cells: [], byId: {}, width: 420, height: 160, cellW: 34 };

  const longest = Math.max(1, ...tree.nodes.flatMap((node) => (node.keys || []).map((key) => shortKey(key).length)));
  const cellW = Math.max(30, Math.round(longest * 7 + 12));
  const slotsOf = (node) => {
    const count = node.keys?.length || 0;
    return Math.min(MAX_CELLS, Math.max(count, maxKeys || 1, 1));
  };
  const widthOf = (node) => slotsOf(node) * cellW + PAD * 2;
  const yOf = (depth) => MARGIN + LABEL_H + depth * LEVEL_GAP;

  const pos = {};
  const deepest = levels.length - 1;
  let cursor = MARGIN;
  levels[deepest].forEach((id) => {
    const w = widthOf(raw[id]);
    pos[id] = { x: cursor, y: yOf(deepest), w };
    cursor += w + SIBLING_GAP;
  });
  for (let depth = deepest - 1; depth >= 0; depth -= 1) {
    let minX = MARGIN;
    levels[depth].forEach((id) => {
      const node = raw[id];
      const w = widthOf(node);
      const kids = (node.children || []).map((child) => pos[child]).filter(Boolean);
      let x = kids.length
        ? (kids[0].x + kids[kids.length - 1].x + kids[kids.length - 1].w) / 2 - w / 2
        : minX;
      x = Math.max(x, minX);
      pos[id] = { x, y: yOf(depth), w };
      minX = x + w + SIBLING_GAP;
    });
  }

  const minX = Math.min(...Object.values(pos).map((p) => p.x));
  if (minX < MARGIN) Object.values(pos).forEach((p) => { p.x += MARGIN - minX; });

  const nodes = levels.flat().map((id) => ({
    ...raw[id],
    ...pos[id],
    h: CELL_H,
    depth: depthOf[id],
    slots: slotsOf(raw[id]),
    isRoot: id === tree.root,
  }));
  const byId = Object.fromEntries(nodes.map((node) => [node.id, node]));

  // Cada clave es un elemento propio con id estable: así, cuando una clave
  // cambia de página (split, merge, borrow), se desliza hasta su nuevo lugar.
  const seen = new Map();
  const cells = [];
  nodes.forEach((node) => {
    const keys = node.keys || [];
    const truncated = keys.length > node.slots;
    const visible = truncated ? keys.slice(0, node.slots - 1) : keys;
    visible.forEach((key, i) => {
      const base = `${node.leaf ? 'L' : 'I'}:${String(key)}`;
      const occurrence = seen.get(base) || 0;
      seen.set(base, occurrence + 1);
      cells.push({ id: `${base}#${occurrence}`, key, x: node.x + PAD + i * cellW, y: node.y, nodeId: node.id, leaf: node.leaf });
    });
    if (truncated) {
      cells.push({ id: `more:${node.id}`, more: keys.length - visible.length, x: node.x + PAD + (node.slots - 1) * cellW, y: node.y, nodeId: node.id });
    }
  });

  const width = Math.max(420, ...nodes.map((node) => node.x + node.w)) + MARGIN;
  const height = yOf(deepest) + CELL_H + MARGIN + 6;
  return { nodes, cells, byId, width, height, cellW, maxKeys };
}

function pointerX(node, index, total, cellW) {
  const shown = node.keys?.length || 0;
  if (total - 1 === shown && shown <= node.slots) return node.x + PAD + index * cellW;
  const span = node.slots * cellW;
  return node.x + PAD + (total <= 1 ? 0.5 : index / (total - 1)) * span;
}

function curve(x1, y1, x2, y2) {
  const bend = Math.max(24, (y2 - y1) * 0.45);
  return `M ${x1} ${y1} C ${x1} ${y1 + bend}, ${x2} ${y2 - bend}, ${x2} ${y2}`;
}

/* ---------- Narración de cada paso ---------- */

function narrate(event, tree, didactic, hasFrames) {
  if (!hasFrames) return 'Estado actual del índice. Ejecuta un INSERT o DELETE sobre esta tabla para ver la operación paso a paso.';
  if (!event) return 'Estado del árbol antes de la operación. Usa ▶ o las flechas ← → del teclado para avanzar.';
  const order = tree?.order;
  const max = order ? order - 1 : null;
  // is_underfull del motor: menos de la mitad de la página ocupada
  const min = order ? Math.ceil((order - 1) / 2) : null;
  const node = (tree?.nodes || []).find((item) => item.id === event.page_id);
  const count = node?.keys?.length ?? 0;
  const p = (id) => `P${id}`;
  switch (event.type) {
    case 'insert': {
      const base = `Se baja con bisect_left hasta la hoja de ${event.key} y se inserta ordenada en ${p(event.page_id)}.`;
      if (max && count > max) return `${base} No cabe: ${count} claves superan el máximo de ${max} (en el motor, los bytes de la página), así que se divide. El motor reparte antes de escribir; aquí se muestra el desborde para explicarlo.`;
      return didactic && max ? `${base} Queda con ${count}/${max} claves, sin cambios estructurales.` : base;
    }
    case 'delete': {
      const base = `Se elimina ${event.key} de la hoja ${p(event.page_id)}.`;
      if (min && node && !node.isRoot && count < min && tree.root !== event.page_id) {
        return `${base} Queda con ${count} clave(s), menos de la mitad de la página (mín. ${min}): hay underflow. El motor primero intenta pedir prestado al hermano izquierdo, luego al derecho, y si ninguno puede prestar, fusiona.`;
      }
      return base;
    }
    case 'separator':
      return `La hoja perdió su clave mínima, así que el separador del padre ${p(event.page_id)} pasa de ${event.old} a ${event.sep} (igual que _rebalance en bplus_tree.py).`;
    case 'split':
      if (event.kind === 'leaf') {
        return `Split de hoja: ${p(event.page_id)} se parte en dos y la mitad derecha pasa a la nueva ${p(event.new_page_id)}. `
          + `La primera clave de la derecha (${event.sep}) se COPIA al padre${event.parent != null ? ` ${p(event.parent)}` : ''} como separador`
          + `${event.parent_overflow ? '; ahora el padre se desborda.' : '.'}`;
      }
      if (event.new_bucket != null) return eventLabel(event);
      return `Split de nodo interno: ${p(event.page_id)} se divide en ${p(event.page_id)} y ${p(event.new_page_id)}. `
        + `La clave del medio (${event.sep}) SUBE al padre${event.parent != null ? ` ${p(event.parent)}` : ''}: en nodos internos se mueve, no se copia.`;
    case 'new_root':
      return `La raíz se dividió, así que se crea una nueva raíz ${p(event.page_id)} con el separador ${event.sep}. El árbol crece un nivel, siempre por arriba.`;
    case 'borrow':
      return `Préstamo: ${p(event.to_id)} toma una clave de su hermano ${event.side < 0 ? 'izquierdo' : 'derecho'} ${p(event.from_id)}, que sigue al menos a la mitad tras prestar${event.sep != null ? `, y el separador del padre pasa a ser ${event.sep}` : ''}.`;
    case 'merge':
      return `Fusión: ningún hermano podía prestar, así que ${p(event.absorbed)} se une a ${p(event.kept)} (el motor fusiona con el hermano derecho salvo en el último hijo) y el padre ${p(event.parent)} pierde un separador y un puntero.`;
    case 'shrink_root':
      return `La raíz quedó sin claves: su único hijo ${p(event.page_id)} pasa a ser la raíz y el árbol pierde un nivel.`;
    default:
      return eventLabel(event);
  }
}

function nodeState(node, events, maxKeys) {
  if (maxKeys && (node.keys?.length || 0) > maxKeys) return 'is-overflow';
  for (const event of events) {
    if (event.type === 'split' && (node.id === event.page_id || node.id === event.new_page_id)) return 'is-split';
    if (event.type === 'merge' && node.id === event.kept) return 'is-merge';
    if (event.type === 'borrow' && (node.id === event.from_id || node.id === event.to_id)) return 'is-borrow';
    if ((event.type === 'new_root' || event.type === 'shrink_root') && node.id === event.page_id) return 'is-root-new';
  }
  for (const event of events) {
    if (event.page_id === node.id || event.parent === node.id) return 'is-active';
  }
  return '';
}

export default function BPlusViz({ animation, staticView, autoPlay = true }) {
  const [viewMode, setViewMode] = useState('disk');
  const { frames, fallback, didactic } = useMemo(
    () => buildFrames(animation, staticView, viewMode),
    [animation, staticView, viewMode],
  );
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(autoPlay && frames.length > 1);
  const [speed, setSpeed] = useState(1);

  useEffect(() => {
    setIndex(0);
    setPlaying(autoPlay && frames.length > 1);
  }, [animation, autoPlay, frames.length, viewMode]);

  const delay = (didactic ? BASE_DELAY.didactic : BASE_DELAY.disk) / speed;
  useEffect(() => {
    if (!playing || frames.length < 2) return undefined;
    const timer = setTimeout(() => {
      setIndex((current) => {
        if (current + 1 >= frames.length) {
          setPlaying(false);
          return current;
        }
        return current + 1;
      });
    }, delay);
    return () => clearTimeout(timer);
  }, [playing, index, frames.length, delay]);

  const frame = frames[index] || { event: null, events: [], tree: fallback };
  const tree = frame.tree || fallback;
  const event = frame.event;
  const activeEvents = frame.events || (event ? [event] : []);
  const layout = useMemo(() => layoutTree(tree), [tree]);
  const hot = highlightedPages(activeEvents);
  const changed = new Set((animation?.changed || []).map(String));
  const separators = new Set(activeEvents
    .filter((item) => ['split', 'new_root', 'separator', 'borrow'].includes(item.type))
    .map((item) => String(item.sep)));

  // Nodos y claves que estaban en el paso anterior y ya no están: se dibujan
  // un instante más para que se desvanezcan en vez de desaparecer de golpe.
  const previous = useRef(null);
  const ghosts = useMemo(() => {
    const prev = previous.current;
    if (!prev || prev === layout) return { nodes: [], cells: [] };
    const nodeIds = new Set(layout.nodes.map((node) => node.id));
    const cellIds = new Set(layout.cells.map((cell) => cell.id));
    return {
      nodes: prev.nodes.filter((node) => !nodeIds.has(node.id)),
      cells: prev.cells.filter((cell) => !cellIds.has(cell.id) && !cell.more),
    };
  }, [layout]);
  useEffect(() => { previous.current = layout; }, [layout]);

  const eventLog = useMemo(() => {
    if (didactic) {
      return frames
        .map((item, frameIndex) => ({ event: item.event, frameIndex }))
        .filter((item) => item.event);
    }
    return (animation?.disk_events || []).map((item) => ({ event: item, frameIndex: frames.length - 1 }));
  }, [didactic, frames, animation]);

  const transitionMs = Math.round(Math.min(700, delay * 0.55));
  const go = (next) => { setPlaying(false); setIndex(Math.max(0, Math.min(frames.length - 1, next))); };
  const onKeyDown = (keyEvent) => {
    if (frames.length < 2) return;
    if (keyEvent.key === 'ArrowRight') { keyEvent.preventDefault(); go(index + 1); }
    if (keyEvent.key === 'ArrowLeft') { keyEvent.preventDefault(); go(index - 1); }
    if (keyEvent.key === ' ') { keyEvent.preventDefault(); setPlaying((value) => !value); }
  };

  if (!tree) {
    return <div className="viz-empty">Esta tabla no tiene un índice B+ Tree.</div>;
  }

  const { cellW, maxKeys } = layout;

  return (
    <div className="flex flex-col h-full min-h-0 outline-none" tabIndex={0} onKeyDown={onKeyDown}>
      <div className="viz-toolbar shrink-0">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="viz-eyebrow">Índice ordenado · {animation?.column || staticView?.column || 'clave'}</p>
            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100 mt-0.5">
              {didactic ? `Reproducción paso a paso · orden ${tree.order || 4}` : 'B+ Tree físico en disco'}
            </h3>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-1 max-w-2xl">
              {didactic
                ? `Réplica de index/bplus_tree.py con las mismas reglas; la capacidad se cuenta en claves (máx. ${maxKeys ?? 3}) en vez de bytes para que cada split y merge sea visible.`
                : `Páginas reales de ${tree.nodes?.[0]?.page_size || 4096} B leídas desde index/bplus_tree.py.`}
            </p>
          </div>
          <div className="viz-segmented">
            <button type="button" onClick={() => setViewMode('disk')} className={viewMode === 'disk' ? 'is-active' : ''}>
              <HardDrive className="w-3.5 h-3.5" /> Disco real
            </button>
            <button
              type="button"
              onClick={() => setViewMode('didactic')}
              disabled={!animation?.didactic}
              className={viewMode === 'didactic' ? 'is-active' : ''}
              title={animation?.didactic ? '' : 'Disponible después de un INSERT o DELETE'}
            >
              <Route className="w-3.5 h-3.5" /> Paso a paso
            </button>
          </div>
        </div>
        {frames.length > 1 && (
          <PlayerBar
            index={index}
            total={frames.length}
            playing={playing}
            onToggle={() => {
              if (!playing && index >= frames.length - 1) setIndex(0);
              setPlaying((value) => !value);
            }}
            onPrev={() => go(index - 1)}
            onNext={() => go(index + 1)}
            onRestart={() => { setIndex(0); setPlaying(true); }}
            label={eventLabel(event)}
            speed={speed}
            onSpeedChange={setSpeed}
          />
        )}
        <p key={`${viewMode}-${index}`} className={`bpt-narration ${event ? `is-${event.type}` : ''}`}>
          {narrate(event, { ...tree, nodes: layout.nodes }, didactic, frames.length > 1)}
        </p>
      </div>

      <div className="flex-1 min-h-0 flex overflow-hidden">
        <div className="flex-1 overflow-auto p-5 viz-canvas">
          <div className="flex flex-wrap items-center gap-2 mb-4 text-[10px] font-mono text-slate-500 dark:text-slate-400">
            <span className="viz-stat"><Cpu className="w-3 h-3" /> altura {tree.height}</span>
            <span className="viz-stat">{tree.nodes?.length || 0} páginas</span>
            <span className="viz-stat">raíz p{tree.root}</span>
            <span className="bpt-legend"><i className="is-inner" /> interno</span>
            <span className="bpt-legend"><i className="is-leaf" /> hoja</span>
            <span className="bpt-legend"><i className="is-link" /> enlace entre hojas</span>
            {changed.size > 0 && <span className="bpt-legend"><i className="is-changed" /> clave afectada</span>}
          </div>
          <svg
            width={layout.width}
            height={layout.height}
            className="bpt-svg block"
            style={{ '--bpt-dur': `${transitionMs}ms` }}
            role="img"
            aria-label="Árbol B+"
          >
            <defs>
              <marker id="bpt-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
                <path d="M0,0 L8,4 L0,8 z" className="bpt-link-head" />
              </marker>
            </defs>

            {/* punteros padre → hijo, saliendo del hueco entre claves */}
            {layout.nodes.flatMap((node) => (node.children || []).map((childId, childIndex) => {
              const child = layout.byId[childId];
              if (!child) return null;
              const d = curve(
                pointerX(node, childIndex, node.children.length, cellW),
                node.y + CELL_H,
                child.x + child.w / 2,
                child.y - 2,
              );
              const isHot = hot.has(childId) && hot.has(node.id);
              return <path key={`e-${node.id}-${childId}`} d={d} style={{ d: `path("${d}")` }} className={`bpt-edge ${isHot ? 'is-hot' : ''}`} />;
            }))}

            {/* lista enlazada de hojas */}
            {layout.nodes.filter((node) => node.leaf && node.next != null && layout.byId[node.next]).map((node) => {
              const next = layout.byId[node.next];
              const y = node.y + CELL_H / 2;
              const d = `M ${node.x + node.w + 2} ${y} L ${next.x - 3} ${next.y + CELL_H / 2}`;
              return <path key={`l-${node.id}`} d={d} style={{ d: `path("${d}")` }} className="bpt-link" markerEnd="url(#bpt-arrow)" />;
            })}

            {/* páginas */}
            {layout.nodes.map((node) => {
              const state = nodeState(node, activeEvents, maxKeys);
              const isOverflow = state === 'is-overflow';
              const occupancy = node.bytes && node.page_size ? Math.min(1, node.bytes / node.page_size) : null;
              const info = occupancy != null
                ? `${node.bytes}/${node.page_size} B`
                : maxKeys ? `${node.keys?.length || 0}/${maxKeys}` : `${node.count ?? node.keys?.length ?? 0} claves`;
              return (
                <g key={`n-${node.id}`} className="bpt-move" style={{ transform: `translate(${node.x}px, ${node.y}px)` }}>
                  <g className="bpt-enter">
                  <g className={`bpt-node ${node.leaf ? 'is-leaf' : 'is-inner'} ${state}`}>
                    <text x={2} y={-5} className="bpt-label">
                      P{node.id}{node.isRoot ? ' · raíz' : ''}
                    </text>
                    <text x={node.w - 2} y={-5} textAnchor="end" className={isOverflow ? 'bpt-badge' : 'bpt-label'}>
                      {isOverflow ? 'OVERFLOW' : info}
                    </text>
                    <rect width={node.w} height={CELL_H} rx="7" className="bpt-box" style={{ width: `${node.w}px` }} />
                    {Array.from({ length: node.slots - 1 }, (_, i) => (
                      <line key={i} x1={PAD + (i + 1) * cellW} x2={PAD + (i + 1) * cellW} y1={5} y2={CELL_H - 5} className="bpt-divider" />
                    ))}
                    {!node.leaf && (node.children || []).map((childId, childIndex) => (
                      <circle
                        key={`p-${childId}`}
                        cx={pointerX({ ...node, x: 0 }, childIndex, node.children.length, cellW)}
                        cy={CELL_H}
                        r="2.6"
                        className="bpt-pointer"
                      />
                    ))}
                    {occupancy != null && (
                      <rect x={PAD} y={CELL_H - 3.5} width={Math.max(2, (node.w - PAD * 2) * occupancy)} height="2" rx="1" className={node.leaf ? 'bpt-fill-leaf' : 'bpt-fill-inner'} />
                    )}
                  </g>
                  </g>
                  <title>{`${node.leaf ? 'Hoja' : 'Nodo interno'} P${node.id} · ${node.keys?.length || 0} claves`}</title>
                </g>
              );
            })}

            {/* claves */}
            {layout.cells.map((cell) => {
              const isChanged = cell.leaf && changed.has(String(cell.key));
              const isSep = !cell.leaf && !cell.more && separators.has(String(cell.key)) && hot.has(cell.nodeId);
              return (
                <g key={cell.id} className="bpt-move" style={{ transform: `translate(${cell.x}px, ${cell.y}px)` }}>
                  <g className={`bpt-cell bpt-enter ${isChanged ? 'is-changed' : ''} ${isSep ? 'is-sep' : ''}`}>
                    <rect x={2} y={4} width={cellW - 4} height={CELL_H - 8} rx="4" className="bpt-cell-bg" />
                    <text x={cellW / 2} y={CELL_H / 2 + 4} textAnchor="middle" className={cell.more ? 'bpt-more' : 'bpt-key'}>
                      {cell.more ? `+${cell.more}` : shortKey(cell.key)}
                    </text>
                    {!cell.more && <title>{String(cell.key)}</title>}
                  </g>
                </g>
              );
            })}

            {/* lo que se fue en este paso */}
            {ghosts.nodes.map((node) => (
              <g key={`gn-${node.id}-${index}`} style={{ transform: `translate(${node.x}px, ${node.y}px)` }}>
                <g className={`bpt-ghost bpt-exit ${node.leaf ? 'is-leaf' : 'is-inner'}`}>
                  <rect width={node.w} height={CELL_H} rx="7" className="bpt-box" />
                </g>
              </g>
            ))}
            {ghosts.cells.map((cell) => (
              <g key={`gc-${cell.id}-${index}`} style={{ transform: `translate(${cell.x}px, ${cell.y}px)` }}>
                <g className="bpt-cell bpt-exit is-removed">
                  <rect x={2} y={4} width={cellW - 4} height={CELL_H - 8} rx="4" className="bpt-cell-bg" />
                  <text x={cellW / 2} y={CELL_H / 2 + 4} textAnchor="middle" className="bpt-key">{shortKey(cell.key)}</text>
                </g>
              </g>
            ))}
          </svg>
          {changed.size > 0 && <p className="mt-2 text-[11px] text-slate-500 font-mono">clave afectada: {[...changed].join(', ')}</p>}
        </div>

        <aside className="hidden xl:flex w-64 shrink-0 border-l border-slate-200 dark:border-slate-800 p-3 flex-col bg-white/70 dark:bg-slate-950/30">
          <p className="viz-eyebrow mb-3">Eventos de la operación</p>
          <div className="space-y-2 overflow-auto">
            {eventLog.length === 0 && <p className="text-[11px] text-slate-400">La operación no cambió la estructura del árbol.</p>}
            {eventLog.map(({ event: item, frameIndex }, eventIndex) => (
              <button
                type="button"
                key={`${item.type}-${eventIndex}`}
                onClick={() => go(frameIndex)}
                className={`viz-event-card viz-event-${item.type} w-full text-left ${didactic && frameIndex === index ? 'is-current' : ''}`}
              >
                <span className="viz-event-index">{String(eventIndex + 1).padStart(2, '0')}</span>
                <div>
                  <p className="font-semibold text-slate-700 dark:text-slate-200">{eventLabel(item)}</p>
                  <p className="text-[10px] text-slate-400 mt-0.5">{item.kind === 'leaf' ? 'nivel hoja' : item.kind === 'inner' ? 'nivel interno' : 'estructura'}</p>
                </div>
              </button>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}
