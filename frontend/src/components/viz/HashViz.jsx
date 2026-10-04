import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Binary, Boxes, HardDrive, Route } from 'lucide-react';
import { bitsOf } from './layout';
import PlayerBar, { eventLabel } from './PlayerBar';

// Color fijo por id de cubeta: no cambia cuando aparecen cubetas nuevas.
// Sin ámbar ni rojo: esos colores se reservan para split, cubeta llena y overflow.
const COLORS = ['#0ea5e9', '#8b5cf6', '#10b981', '#6366f1', '#14b8a6', '#d946ef', '#65a30d', '#06b6d4', '#ec4899', '#3b82f6'];
const colorOf = (id) => COLORS[Math.abs(Number(id) || 0) % COLORS.length];

// Geometría del dibujo (px)
const MARGIN = 20;
const TOP = 46;
const ROW = 30;
const SLOT_W = 104;
const WIRE_GAP = 150;
const CW = 58;
const CH = 40;
const PAD = 5;
const BUCKET_GAP = 34;
const MAX_CELLS = 8;
const OVF_W = 86;
const BASE_DELAY = { didactic: 1700, disk: 1900 };

function buildFrames(animation, staticView, viewMode) {
  const diskAfter = animation?.disk || staticView?.disk;
  if (!diskAfter) return { frames: [], fallback: null, didactic: false };
  if (viewMode === 'didactic' && animation?.didactic) {
    const model = animation.didactic;
    const frames = [];
    if (model.before) frames.push({ event: null, events: [], hash: model.before });
    (model.frames || []).forEach((frame) => frames.push({
      ...frame,
      events: frame.event ? [frame.event] : [],
    }));
    return { frames, fallback: model.after, didactic: true };
  }
  const before = animation?.disk_before;
  const events = animation?.disk_events || [];
  if (!before && !events.length) return { frames: [], fallback: diskAfter, didactic: false };
  const primary = [...events].reverse().find((event) => event.type === 'split' || event.type === 'double')
    || events.at(-1)
    || { type: 'insert' };
  return {
    frames: [
      ...(before ? [{ event: null, events: [], hash: before }] : []),
      { event: primary, events: events.length ? events : [primary], hash: diskAfter },
    ],
    fallback: diskAfter,
    didactic: false,
  };
}

function lowBits(hex, n) {
  if (!hex || n <= 0) return '';
  try {
    const value = BigInt(`0x${hex}`);
    return (value & ((1n << BigInt(n)) - 1n)).toString(2).padStart(n, '0');
  } catch {
    return '';
  }
}

function shortText(value) {
  const text = String(value);
  return text.length > 7 ? `${text.slice(0, 6)}…` : text;
}

/* ---------- Layout ---------- */

function layoutHash(snap) {
  const directory = snap?.directory || [];
  const buckets = [...(snap?.buckets || [])];
  const capacity = snap?.capacity || 1;
  const firstSlot = (bucket) => Math.min(...(bucket.dir_slots?.length ? bucket.dir_slots : [Infinity]));
  buckets.sort((a, b) => firstSlot(a) - firstSlot(b));

  const bucketX = MARGIN + SLOT_W + WIRE_GAP;
  const dirH = directory.length * ROW;
  const bucketsH = buckets.length * (CH + BUCKET_GAP) - BUCKET_GAP;
  const dirTop = TOP + Math.max(0, (bucketsH - dirH) / 2);
  const bucketTop = TOP + Math.max(0, (dirH - bucketsH) / 2);

  const slots = directory.map((bucketId, slot) => ({ slot, bucketId, x: MARGIN, y: dirTop + slot * ROW }));

  const seen = new Map();
  const cells = [];
  const placed = buckets.map((bucket, order) => {
    const chain = bucket.chain || [];
    const primary = chain[0];
    const keys = bucket.keys || [];
    const hashes = keys.length
      ? (primary?.hashes || [])
      : chain.filter((page) => page.kind !== 'overflow').flatMap((page) => page.hashes || []);
    const count = keys.length || hashes.length;
    const overflowPages = chain.filter((page) => page.kind === 'overflow');
    const slotsShown = Math.min(MAX_CELLS, Math.max(capacity, count, 1));
    const w = slotsShown * CW + PAD * 2;
    const x = bucketX;
    const y = bucketTop + order * (CH + BUCKET_GAP);
    const truncated = count > slotsShown;
    const visible = truncated ? slotsShown - 1 : count;
    for (let i = 0; i < visible; i += 1) {
      const key = keys.length ? keys[i] : null;
      const hash = hashes[i];
      const base = key != null ? `k:${String(key)}` : `h:${hash}`;
      const occurrence = seen.get(base) || 0;
      seen.set(base, occurrence + 1);
      cells.push({
        id: `${base}#${occurrence}`,
        key,
        hash,
        x: x + PAD + i * CW,
        y,
        bucketId: bucket.id,
        localDepth: bucket.local_depth || 0,
        over: i >= capacity,
      });
    }
    if (truncated) cells.push({ id: `more:${bucket.id}`, more: count - visible, x: x + PAD + visible * CW, y, bucketId: bucket.id });
    return { ...bucket, x, y, w, h: CH, slotsShown, count, overflowPages };
  });

  const byId = Object.fromEntries(placed.map((bucket) => [bucket.id, bucket]));
  const width = Math.max(
    560,
    ...placed.map((bucket) => bucket.x + bucket.w + bucket.overflowPages.length * (OVF_W + 22)),
  ) + MARGIN;
  const height = Math.max(dirTop + dirH, bucketTop + bucketsH) + MARGIN + 8;
  return { slots, buckets: placed, byId, cells, width, height, capacity };
}

function wirePath(slot, bucket) {
  const x1 = slot.x + SLOT_W;
  const y1 = slot.y + (ROW - 6) / 2;
  const x2 = bucket.x - 5;
  const y2 = bucket.y + CH / 2;
  const mid = (x2 - x1) * 0.55;
  return `M ${x1} ${y1} C ${x1 + mid} ${y1}, ${x2 - mid} ${y2}, ${x2} ${y2}`;
}

/* ---------- Narración ---------- */

function narrate(event, snap, didactic, hasFrames) {
  if (!hasFrames) return 'Estado actual del índice. Ejecuta un INSERT o DELETE sobre esta tabla para ver cómo se reparte cada clave.';
  if (!event) return 'Estado antes de la operación. Cada clave va a la cubeta que indica el final de su hash. Usa ▶ o las flechas ← → para avanzar.';
  const d = snap?.global_depth ?? 0;
  const bucket = (snap?.buckets || []).find((item) => item.id === event.bucket);
  const cap = bucket?.capacity ?? snap?.capacity;
  switch (event.type) {
    case 'insert':
      if (!didactic) return `Se inserta ${event.key ?? 'la clave'} en la cubeta que indica su hash.`;
      return `h(${event.key}) termina en …${event.bits}. Con profundidad global ${d} se miran los últimos ${d} bits: entrada ${event.bits} del directorio → cubeta P${event.bucket}. `
        + `Hay espacio (${bucket?.count ?? '?'}/${cap}).`;
    case 'full': {
      const base = `h(${event.key}) termina en …${event.bits} → cubeta P${event.bucket}, pero está llena (${cap}/${cap}). `;
      if (event.local_depth === event.global_depth) {
        return `${base}Su profundidad local (${event.local_depth}) es igual a la global (${event.global_depth}): ninguna otra entrada apunta a ella, así que primero hay que DUPLICAR el directorio.`;
      }
      return `${base}Su profundidad local (${event.local_depth}) es menor que la global (${event.global_depth}): varias entradas la comparten, así que basta con DIVIDIRLA sin tocar el tamaño del directorio.`;
    }
    case 'double':
      return `El directorio se duplica de ${event.old_size ?? event.directory_size / 2} a ${event.directory_size} entradas y la profundidad global sube a ${event.global_depth}. `
        + 'Cada entrada nueva es una copia de su gemela (la misma terminación con un bit menos) y apunta a la misma cubeta; todavía no se mueve ninguna clave.';
    case 'split': {
      const bit = event.bit ?? (event.local_depth - 1);
      const keep = (event.keep || []).join(', ') || 'ninguna';
      const move = (event.move || []).join(', ') || 'ninguna';
      return `Split de P${event.bucket}: su profundidad local sube a ${event.local_depth} y se mira un bit más, el bit ${bit} contando desde la derecha (en ámbar). `
        + `Con 0 se quedan en P${event.bucket} (${keep}); con 1 migran a la nueva P${event.new_bucket} (${move}). Las entradas del directorio con ese bit en 1 ahora apuntan a P${event.new_bucket}.`;
    }
    case 'overflow':
      return `P${event.bucket} está llena y sus claves comparten también el bit ${event.local_depth ?? ''} con ${event.key} (_is_stuck): dividir no las separaría, así que ${event.key} va a la página de overflow P${event.page} encadenada a la cubeta.`;
    case 'consolidate':
      return `Tras el borrado, la página P${event.page} y su overflow P${event.absorbed} caben juntas: el motor las compacta (_consolidate) y libera P${event.absorbed}.`;
    case 'delete':
      return `Se elimina ${event.key} de su cubeta. En este motor el borrado no fusiona cubetas ni reduce el directorio: solo se compactan las páginas de overflow si caben en la primaria.`;
    default:
      return eventLabel(event);
  }
}

export default function HashViz({ animation, staticView, autoPlay = true }) {
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

  const frame = frames[index] || { event: null, events: [], hash: fallback };
  const snap = frame.hash || fallback;
  const event = frame.event;
  const activeEvents = frame.events || (event ? [event] : []);
  const layout = useMemo(() => layoutHash(snap), [snap]);

  // Lo que había en el paso anterior: sirve para animar la copia del
  // directorio, las flechas que cambian de cubeta y las claves que se van.
  const previous = useRef(null);
  const diff = useMemo(() => {
    const prev = previous.current;
    if (!prev || prev === layout) return { ghosts: [], oldDir: layout.slots.length, rewired: new Set() };
    const cellIds = new Set(layout.cells.map((cell) => cell.id));
    const rewired = new Set(layout.slots
      .filter((slot) => prev.slots[slot.slot] && prev.slots[slot.slot].bucketId !== slot.bucketId)
      .map((slot) => slot.slot));
    return {
      ghosts: prev.cells.filter((cell) => !cell.more && !cellIds.has(cell.id)),
      oldDir: prev.slots.length,
      rewired,
    };
  }, [layout]);
  useEffect(() => { previous.current = layout; }, [layout]);

  const eventLog = useMemo(() => {
    if (didactic) {
      return frames.map((item, frameIndex) => ({ event: item.event, frameIndex })).filter((item) => item.event);
    }
    return (animation?.disk_events || []).map((item) => ({ event: item, frameIndex: frames.length - 1 }));
  }, [didactic, frames, animation]);

  if (!snap) return <div className="viz-empty">Esta tabla no tiene un índice Hash extensible.</div>;

  const depth = snap.global_depth || 0;
  const showBits = Math.min(8, Math.max(4, depth + 1));
  const changed = new Set((animation?.changed || []).map(String));
  const splitEvent = activeEvents.find((item) => item.type === 'split');
  const splitIds = new Set(splitEvent ? [splitEvent.bucket, splitEvent.new_bucket] : []);
  const fullIds = new Set(activeEvents.filter((item) => item.type === 'full' || item.type === 'overflow').map((item) => item.bucket));
  const hotSlots = new Set(activeEvents.filter((item) => item.index != null).map((item) => item.index));
  const doubling = activeEvents.find((item) => item.type === 'double');
  const eventKeys = new Set(activeEvents.filter((item) => item.key != null).map((item) => String(item.key)));
  const transitionMs = Math.round(Math.min(750, delay * 0.5));

  const go = (next) => { setPlaying(false); setIndex(Math.max(0, Math.min(frames.length - 1, next))); };
  const onKeyDown = (keyEvent) => {
    if (frames.length < 2) return;
    if (keyEvent.key === 'ArrowRight') { keyEvent.preventDefault(); go(index + 1); }
    if (keyEvent.key === 'ArrowLeft') { keyEvent.preventDefault(); go(index - 1); }
    if (keyEvent.key === ' ') { keyEvent.preventDefault(); setPlaying((value) => !value); }
  };

  return (
    <div className="flex flex-col h-full min-h-0 outline-none" tabIndex={0} onKeyDown={onKeyDown}>
      <div className="viz-toolbar shrink-0">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="viz-eyebrow">Acceso directo · {animation?.column || staticView?.column || 'clave'}</p>
            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100 mt-0.5">
              {didactic ? `Réplica de extendible_hash.py · capacidad ${snap.capacity}` : 'Hash extensible físico en disco'}
            </h3>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-1 max-w-2xl">
              El directorio usa los {depth} bits menos significativos del hash. En cada clave se resaltan los bits que comparte con su cubeta (profundidad local).
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
              <Route className="w-3.5 h-3.5" /> División animada
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
        <p key={`${viewMode}-${index}`} className={`bpt-narration ${event ? `is-${event.type === 'double' ? 'new_root' : event.type === 'full' || event.type === 'overflow' ? 'merge' : event.type}` : ''}`}>
          {narrate(event, snap, didactic, frames.length > 1)}
        </p>
      </div>

      <div className="flex-1 min-h-0 flex overflow-hidden">
        <div className="flex-1 overflow-auto p-5 viz-canvas">
          <div className="grid grid-cols-3 gap-2 mb-4 max-w-xl">
            <div className={`viz-metric-card ${doubling ? 'hx-metric-bump' : ''}`} key={`gd-${depth}`}><Binary className="w-4 h-4 text-violet-500" /><span>Profundidad global</span><strong>{depth}</strong></div>
            <div className="viz-metric-card" key={`dir-${layout.slots.length}`}><Boxes className="w-4 h-4 text-sky-500" /><span>Entradas</span><strong>{layout.slots.length}</strong></div>
            <div className="viz-metric-card" key={`b-${layout.buckets.length}`}><HardDrive className="w-4 h-4 text-emerald-500" /><span>Cubetas</span><strong>{layout.buckets.length}</strong></div>
          </div>

          <svg
            width={layout.width}
            height={layout.height}
            className="hx-svg bpt-svg block"
            style={{ '--bpt-dur': `${transitionMs}ms` }}
            role="img"
            aria-label="Hash extensible"
          >
            <text x={MARGIN} y={14} className="hx-heading">DIRECTORIO · {depth} bit{depth === 1 ? '' : 's'}</text>
            <text x={MARGIN + SLOT_W + WIRE_GAP} y={14} className="hx-heading">CUBETAS</text>

            {/* flechas directorio → cubeta */}
            {layout.slots.map((slot) => {
              const bucket = layout.byId[slot.bucketId];
              if (!bucket) return null;
              const d = wirePath(slot, bucket);
              const isHot = hotSlots.has(slot.slot);
              const isRewired = diff.rewired.has(slot.slot);
              return (
                <path
                  key={`w-${slot.slot}`}
                  d={d}
                  style={{ d: `path("${d}")`, '--bucket-color': colorOf(slot.bucketId) }}
                  className={`hx-wire ${isHot ? 'is-hot' : ''} ${isRewired ? 'is-rewired' : ''}`}
                />
              );
            })}

            {/* entradas del directorio */}
            {layout.slots.map((slot) => {
              const isNew = doubling && slot.slot >= (doubling.old_size ?? diff.oldDir);
              const twinOffset = isNew ? -(doubling.old_size ?? diff.oldDir) * ROW : 0;
              const isHot = hotSlots.has(slot.slot);
              return (
                <g key={`s-${slot.slot}`} className="bpt-move" style={{ transform: `translate(${slot.x}px, ${slot.y}px)` }}>
                  <g
                    className={`hx-slot ${isNew ? 'is-copy' : 'bpt-enter'} ${isHot ? 'is-hot' : ''} ${diff.rewired.has(slot.slot) ? 'is-rewired' : ''}`}
                    style={{ '--bucket-color': colorOf(slot.bucketId), '--copy-dy': `${twinOffset}px` }}
                  >
                    <rect width={SLOT_W} height={ROW - 6} rx="6" className="hx-slot-box" />
                    <rect x={SLOT_W - 5} y={0} width={5} height={ROW - 6} className="hx-slot-tab" />
                    <text x={10} y={(ROW - 6) / 2 + 4} className="hx-slot-bits">{bitsOf(slot.slot, depth)}</text>
                    <text x={SLOT_W - 12} y={(ROW - 6) / 2 + 3.5} textAnchor="end" className="hx-slot-target">P{slot.bucketId}</text>
                  </g>
                </g>
              );
            })}

            {/* cubetas */}
            {layout.buckets.map((bucket) => {
              const color = colorOf(bucket.id);
              const state = splitIds.has(bucket.id) ? 'is-split' : fullIds.has(bucket.id) ? 'is-full' : '';
              const capacity = bucket.capacity ?? layout.capacity;
              return (
                <g key={`b-${bucket.id}`} className="bpt-move" style={{ transform: `translate(${bucket.x}px, ${bucket.y}px)`, '--bucket-color': color }}>
                  <g className="bpt-enter">
                    <g className={`hx-bucket ${state}`}>
                      <text x={2} y={-6} className="hx-bucket-id">P{bucket.id}</text>
                      <text x={30} y={-6} className="hx-bucket-meta">ld {bucket.local_depth} · {bucket.count}/{capacity} · {(bucket.dir_slots || []).length} ref.</text>
                      {state === 'is-full' && <text x={bucket.w + 8} y={CH / 2 + 3} className="bpt-badge">← LLENA</text>}
                      <rect width={bucket.w} height={CH} rx="8" className="hx-bucket-box" style={{ width: `${bucket.w}px` }} />
                      <rect width={4} height={CH} rx="2" className="hx-bucket-tab" />
                      {Array.from({ length: bucket.slotsShown - 1 }, (_, i) => (
                        <line
                          key={i}
                          x1={PAD + (i + 1) * CW}
                          x2={PAD + (i + 1) * CW}
                          y1={6}
                          y2={CH - 6}
                          className={`bpt-divider ${i + 1 === capacity ? 'hx-capacity-line' : ''}`}
                        />
                      ))}
                      {bucket.overflowPages.map((page, pageIndex) => {
                        const ox = bucket.w + 22 + pageIndex * (OVF_W + 22);
                        return (
                          <g key={`o-${page.id}`}>
                            <path d={`M ${ox - 22 + 2} ${CH / 2} L ${ox - 3} ${CH / 2}`} className="hx-chain" markerEnd="url(#hx-arrow)" />
                            <rect x={ox} y={0} width={OVF_W} height={CH} rx="8" className="hx-overflow-box" />
                            <text x={ox + OVF_W / 2} y={16} textAnchor="middle" className="hx-bucket-meta">overflow P{page.id}</text>
                            <text x={ox + OVF_W / 2} y={30} textAnchor="middle" className="hx-key">
                              {page.keys?.length ? page.keys.map(shortText).join(' · ') : `${page.count} entradas`}
                            </text>
                          </g>
                        );
                      })}
                    </g>
                  </g>
                </g>
              );
            })}

            {/* claves con los bits finales de su hash */}
            {layout.cells.map((cell) => {
              const isChanged = cell.key != null && (changed.has(String(cell.key)) || eventKeys.has(String(cell.key)));
              const inSplit = splitEvent && splitIds.has(cell.bucketId);
              const moved = inSplit && (splitEvent.move || []).map(String).includes(String(cell.key));
              const bits = lowBits(cell.hash, showBits);
              return (
                <g key={cell.id} className="bpt-move" style={{ transform: `translate(${cell.x}px, ${cell.y}px)`, '--bucket-color': colorOf(cell.bucketId) }}>
                  <g className={`hx-cell bpt-enter ${isChanged ? 'is-changed' : ''} ${moved ? 'is-moved' : ''} ${cell.over ? 'is-over' : ''}`}>
                    <rect x={3} y={4} width={CW - 6} height={CH - 8} rx="5" className="hx-cell-bg" />
                    {cell.more ? (
                      <text x={CW / 2} y={CH / 2 + 4} textAnchor="middle" className="bpt-more">+{cell.more}</text>
                    ) : (
                      <>
                        <text x={CW / 2} y={18} textAnchor="middle" className="hx-key">
                          {cell.key != null ? shortText(cell.key) : `…${String(cell.hash || '').slice(-4)}`}
                        </text>
                        {bits && (
                          <text x={CW / 2} y={31} textAnchor="middle" className="hx-bits">
                            {bits.split('').map((bit, i) => {
                              const fromRight = bits.length - 1 - i;
                              const isNewBit = inSplit && fromRight === (splitEvent.bit ?? splitEvent.local_depth - 1);
                              const isLocal = fromRight < cell.localDepth;
                              return (
                                <tspan key={i} className={isNewBit ? 'is-new-bit' : isLocal ? 'is-local-bit' : ''}>{bit}</tspan>
                              );
                            })}
                          </text>
                        )}
                        <title>{`${cell.key != null ? `clave ${cell.key} · ` : ''}hash …${cell.hash}`}</title>
                      </>
                    )}
                  </g>
                </g>
              );
            })}

            {diff.ghosts.map((cell) => (
              <g key={`g-${cell.id}-${index}`} style={{ transform: `translate(${cell.x}px, ${cell.y}px)` }}>
                <g className="hx-cell bpt-exit is-removed">
                  <rect x={3} y={4} width={CW - 6} height={CH - 8} rx="5" className="hx-cell-bg" />
                  <text x={CW / 2} y={18} textAnchor="middle" className="hx-key">{cell.key != null ? shortText(cell.key) : '…'}</text>
                </g>
              </g>
            ))}

            <defs>
              <marker id="hx-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
                <path d="M0,0 L8,4 L0,8 z" className="hx-chain-head" />
              </marker>
            </defs>
          </svg>
        </div>

        <aside className="hidden xl:flex w-64 shrink-0 border-l border-slate-200 dark:border-slate-800 p-3 flex-col bg-white/70 dark:bg-slate-950/30">
          <p className="viz-eyebrow mb-3">Secuencia de división</p>
          <div className="space-y-2 overflow-auto">
            {eventLog.length === 0 && <p className="text-[11px] text-slate-400">No hubo duplicación ni split en esta operación.</p>}
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
                  {item.type === 'split' && (
                    <p className="text-[10px] text-slate-400 mt-0.5">
                      {Array.isArray(item.keep) ? item.keep.length : item.keep ?? 0} quedan · {Array.isArray(item.move) ? item.move.length : item.move ?? 0} migran
                    </p>
                  )}
                </div>
              </button>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}
