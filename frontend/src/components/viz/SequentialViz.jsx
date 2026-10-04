import React, { useEffect, useMemo, useRef, useState } from 'react';
import { GitMerge, Layers3 } from 'lucide-react';
import { formatKey } from './layout';
import PlayerBar from './PlayerBar';

/*
 * Visualiza storage/sequential_file.py a partir de sus snapshots reales
 * (antes y después). Los pasos intermedios se reconstruyen aplicando, en el
 * mismo orden que el código, las escrituras que hace cada operación:
 *   insert()     → decide MAIN (append al final) o AUX, escribe el registro
 *                  y luego actualiza el next del predecesor (o el head).
 *   delete()     → _find_by_key, marca deleted=True y desenlaza al predecesor.
 *   reorganize() → records = list(scan()), truncate de MAIN y AUX, append de
 *                  cada registro a MAIN y enlace de los next.
 */

// Umbrales de needs_reorganization()
const MAX_AUX = 100;
const WASTE_THRESHOLD = 0.3;

// Geometría (px)
const CW = 64;
const CH = 46;
const GAP = 8;
const COLS = 12;
const PAGE_PAD = 8;
const PAGE_HEAD = 18;
const LANE_HEAD = 30;
const LANE_GAP = 56;
const MARGIN = 16;
const MAX_W = 1000;
const MAX_VISIBLE_ROWS = 96;
const BASE_DELAY = 1900;

const pid = (pointer) => (pointer ? `${pointer.file === 'MAIN' ? 'M' : 'A'}-${pointer.page}-${pointer.slot}` : null);
const rowsOf = (snap) => [...(snap?.main || []), ...(snap?.aux || [])];
const ptrText = (pointer) => (pointer ? `${pointer.file} P${pointer.page}:${pointer.slot}` : '∅');
const rowPtr = (row) => (row ? { file: row.id.startsWith('M-') ? 'MAIN' : 'AUX', page: row.page, slot: row.slot } : null);
const isAux = (row) => row.id.startsWith('A-');

function chainOrder(snap) {
  const byId = Object.fromEntries(rowsOf(snap).map((row) => [row.id, row]));
  const order = [];
  const seen = new Set();
  let cursor = pid(snap?.head);
  while (cursor && byId[cursor] && !seen.has(cursor)) {
    seen.add(cursor);
    order.push(cursor);
    cursor = pid(byId[cursor].next);
  }
  return order;
}

function lastPhysicalMain(snap) {
  // _last_main_key(): último slot ocupado de MAIN, esté o no borrado
  const main = [...(snap?.main || [])].sort((a, b) => (a.page - b.page) || (a.slot - b.slot));
  return main.at(-1) || null;
}

function withRow(snap, row, file) {
  const key = file === 'MAIN' ? 'main' : 'aux';
  return { ...snap, [key]: [...(snap[key] || []), row] };
}

function patchRow(snap, id, patch) {
  const fix = (rows) => (rows || []).map((row) => (row.id === id ? { ...row, ...patch } : row));
  return { ...snap, main: fix(snap.main), aux: fix(snap.aux) };
}

/* ---------- Pasos de cada operación ---------- */

function insertFrames(before, after) {
  const beforeIds = new Set(rowsOf(before).map((row) => row.id));
  const added = rowsOf(after).filter((row) => !beforeIds.has(row.id));
  if (added.length !== 1) return null;
  const row = added[0];
  const toMain = !isAux(row);
  const byIdBefore = Object.fromEntries(rowsOf(before).map((item) => [item.id, item]));
  const tail = byIdBefore[pid(before.tail)] || null;
  const lastMain = lastPhysicalMain(before);
  const pred = rowsOf(after).find((item) => pid(item.next) === row.id) || null;
  const succ = rowsOf(after).find((item) => item.id === pid(row.next)) || null;
  const k = formatKey(row.key);
  const frames = [{ snap: before, label: 'Antes del INSERT', narration: `Se va a insertar ${k}. Primero se decide en qué archivo se escribe.` }];

  if (!before.head) {
    frames.push({
      snap: before,
      hot: new Set(lastMain ? [lastMain.id] : []),
      label: 'Cadena vacía',
      narration: `La cadena está vacía (head = ∅). Si MAIN no tiene registros o ${k} es mayor que su última clave física, va a MAIN; si no, a AUX. Aquí va a ${toMain ? 'MAIN' : 'AUX'}.`,
    });
  } else if (toMain) {
    frames.push({
      snap: before,
      hot: new Set([tail?.id, lastMain?.id].filter(Boolean)),
      label: 'Va al final de MAIN',
      narration: `${k} es mayor que el tail (${formatKey(tail?.key)}) y que la última clave física de MAIN (${formatKey(lastMain?.key)}): se agrega al final de MAIN, que sigue ordenado, sin tocar AUX.`,
    });
  } else {
    const reason = tail && row.key <= tail.key
      ? `no es mayor que el tail (${formatKey(tail.key)})`
      : `no es mayor que la última clave física de MAIN (${formatKey(lastMain?.key)})`;
    frames.push({
      snap: before,
      hot: new Set([tail?.id, lastMain?.id].filter(Boolean)),
      label: 'No cabe al final → AUX',
      narration: `${k} ${reason}, así que agregarlo al final de MAIN rompería el orden: se escribirá en AUX y se enlazará en su lugar de la cadena.`,
    });
    frames.push({
      snap: before,
      hot: new Set([pred?.id, succ?.id].filter(Boolean)),
      label: 'Buscar posición',
      narration: `_find_insert_position: búsqueda binaria sobre las páginas de MAIN para hallar el predecesor vivo y luego se avanza por los next. `
        + `${pred ? `Predecesor: ${formatKey(pred.key)}` : 'No hay predecesor: será la nueva cabeza'}; sucesor: ${succ ? formatKey(succ.key) : '∅ (será el nuevo tail)'}.`,
    });
  }

  const written = withRow(before, toMain ? { ...row, next: null } : row, toMain ? 'MAIN' : 'AUX');
  frames.push({
    snap: written,
    hot: new Set([row.id]),
    hotEdges: new Set(toMain ? [] : [row.id]),
    label: `Escribir en ${toMain ? 'MAIN' : 'AUX'}`,
    narration: toMain
      ? `_append_entry(MAIN): ${k} se escribe en la última página de MAIN (P${row.page}:${row.slot}) con next = ∅.`
      : `_append_entry(AUX): ${k} se escribe al final de AUX (P${row.page}:${row.slot}) y ya apunta a su sucesor ${succ ? formatKey(succ.key) : '∅'}. Todavía nadie lo apunta a él.`,
  });

  frames.push({
    snap: after,
    hot: new Set([row.id, pred?.id].filter(Boolean)),
    hotEdges: new Set(pred ? [pred.id] : []),
    label: 'Enlazar',
    narration: toMain
      ? `El antiguo tail ${formatKey(tail?.key)} ahora apunta a ${k}, y ${k} pasa a ser el tail.`
      : pred
        ? `Se reescribe ${formatKey(pred.key)}.next → ${k}. La cadena vuelve a estar en orden${succ ? '' : ' y el tail pasa a ser ' + k}. AUX: ${after.n_aux ?? (after.aux || []).length} registro(s).`
        : `${k} pasa a ser el head de la cadena. AUX: ${after.n_aux ?? (after.aux || []).length} registro(s).`,
  });
  return frames;
}

function deleteFrames(before, after) {
  const afterById = Object.fromEntries(rowsOf(after).map((row) => [row.id, row]));
  const removed = rowsOf(before).filter((row) => !row.deleted && afterById[row.id]?.deleted);
  if (removed.length !== 1) return null;
  const row = removed[0];
  const pred = rowsOf(before).find((item) => !item.deleted && pid(item.next) === row.id) || null;
  const succ = rowsOf(before).find((item) => item.id === pid(row.next)) || null;
  const k = formatKey(row.key);
  const waste = Math.round((after.wasted_ratio || 0) * 100);
  return [
    { snap: before, label: 'Antes del DELETE', narration: `Se va a eliminar ${k}.` },
    {
      snap: before,
      hot: new Set([row.id, pred?.id].filter(Boolean)),
      label: 'Buscar',
      narration: `_find_by_key: búsqueda binaria en MAIN para el predecesor vivo y recorrido por los next hasta ${k}, que está en ${isAux(row) ? 'AUX' : 'MAIN'} P${row.page}:${row.slot}.`,
    },
    {
      snap: patchRow(before, row.id, { deleted: true }),
      hot: new Set([row.id]),
      label: 'Borrado lógico',
      narration: `Se marca deleted = True y se reescribe la entrada: ${k} sigue ocupando su slot (no se libera espacio hasta reorganizar).`,
    },
    {
      snap: after,
      hot: new Set([pred?.id, succ?.id].filter(Boolean)),
      hotEdges: new Set(pred ? [pred.id] : []),
      label: 'Desenlazar',
      narration: `${pred ? `${formatKey(pred.key)}.next pasa a apuntar a ${succ ? formatKey(succ.key) : '∅'}` : `El head pasa a ser ${succ ? formatKey(succ.key) : '∅'}`}: ${k} queda fuera de la cadena. `
        + `Desperdicio: ${waste}% (se reorganiza al superar ${WASTE_THRESHOLD * 100}% o con ${MAX_AUX} registros en AUX).`,
    },
  ];
}

const tagRows = (snap, src) => (snap ? {
  ...snap,
  main: (snap.main || []).map((row) => ({ ...row, src })),
  aux: (snap.aux || []).map((row) => ({ ...row, src })),
} : snap);

function reorganizeFrames(rawBefore, rawAfter) {
  // Cada fila recuerda de qué snapshot viene: los ids página-slot se repiten.
  const before = tagRows(rawBefore, 'before');
  const after = tagRows(rawAfter, 'after');
  const order = chainOrder(before);
  const byId = Object.fromEntries(rowsOf(before).map((row) => [row.id, row]));
  const badges = new Map(order.map((id, i) => [id, i + 1]));
  const deleted = rowsOf(before).filter((row) => row.deleted).length;
  const ram = order.map((id) => byId[id]);
  const emptied = { ...before, main: [], aux: [], head: null, tail: null };
  const unlinked = {
    ...after,
    main: (after.main || []).map((row) => ({ ...row, next: null })),
    head: null,
    tail: null,
  };
  return [
    {
      snap: before,
      label: 'Antes de reorganizar',
      narration: `MAIN tiene ${(before.main || []).length} entradas y AUX ${(before.aux || []).length}; ${deleted} son borrados lógicos. Desperdicio ${Math.round((before.wasted_ratio || 0) * 100)}%.`,
    },
    {
      snap: before,
      badges,
      hot: new Set(order),
      label: 'records = list(scan())',
      narration: `reorganize() recorre la cadena desde head siguiendo los next. Solo visita los ${order.length} registros vivos y ya salen en orden de clave; los ${deleted} borrados estaban desenlazados y se descartan.`,
    },
    {
      snap: emptied,
      ram,
      label: 'truncate(MAIN, AUX)',
      narration: `Los registros quedan en memoria, en orden, y se truncan ambos archivos a 0 páginas.`,
    },
    {
      snap: unlinked,
      label: 'append a MAIN',
      narration: `Cada registro se agrega a MAIN con next = ∅, en orden: MAIN queda compacto y ordenado físicamente, y AUX vacío.`,
    },
    {
      snap: after,
      hotEdges: new Set((after.main || []).map((row) => row.id)),
      label: 'Enlazar next',
      narration: `Se enlaza cada registro con el siguiente; head = primero, tail = último, n_aux = 0 y n_deleted = 0. Desperdicio: ${Math.round((after.wasted_ratio || 0) * 100)}%.`,
    },
  ];
}

function buildFrames(before, after, operation) {
  if (operation === 'REORGANIZE' && before && after) return reorganizeFrames(before, after);
  if (before && after) {
    const detailed = operation === 'INSERT' ? insertFrames(before, after)
      : operation === 'DELETE' ? deleteFrames(before, after)
        : null;
    if (detailed) return detailed;
    return [
      { snap: before, label: `Antes de ${operation || 'la operación'}`, narration: `Estado antes de ${operation || 'la operación'}.` },
      { snap: after, label: `${operation || 'Cambio'} aplicado`, narration: 'Estado después de la operación (varios registros cambiaron a la vez, así que se muestra el resultado completo).' },
    ];
  }
  const snap = after || before;
  return snap ? [{ snap, label: 'Estado actual', narration: 'Estado actual del archivo. Ejecuta un INSERT, DELETE o REORGANIZE para verlo paso a paso.' }] : [];
}

/* ---------- Layout ---------- */

function visiblePages(rows, focus) {
  const pages = [...new Set(rows.map((row) => row.page))].sort((a, b) => a - b);
  if (rows.length <= MAX_VISIBLE_ROWS) return { shown: new Set(pages), hidden: 0 };
  const keep = new Set([pages[0], pages.at(-1)]);
  rows.filter((row) => focus.has(row.id)).forEach((row) => { keep.add(row.page - 1); keep.add(row.page); keep.add(row.page + 1); });
  const shown = new Set(pages.filter((page) => keep.has(page)));
  return { shown, hidden: pages.length - shown.size };
}

function layoutLane(name, rows, y, focus, identity) {
  const { shown, hidden } = visiblePages(rows, focus);
  const byPage = new Map();
  rows.filter((row) => shown.has(row.page)).forEach((row) => {
    if (!byPage.has(row.page)) byPage.set(row.page, []);
    byPage.get(row.page).push(row);
  });
  const pages = [];
  const cells = [];
  let x = MARGIN;
  let rowY = y + LANE_HEAD;
  let rowH = 0;
  [...byPage.entries()].sort((a, b) => a[0] - b[0]).forEach(([page, pageRows]) => {
    pageRows.sort((a, b) => a.slot - b.slot);
    const cols = Math.min(COLS, Math.max(1, pageRows.length));
    const lines = Math.ceil(pageRows.length / COLS);
    const w = cols * CW + (cols - 1) * GAP + PAGE_PAD * 2;
    const h = PAGE_HEAD + lines * CH + (lines - 1) * GAP + PAGE_PAD * 2;
    if (x + w > MAX_W && x > MARGIN) {
      x = MARGIN;
      rowY += rowH + GAP * 2;
      rowH = 0;
    }
    pages.push({ page, x, y: rowY, w, h, count: pageRows.length });
    pageRows.forEach((row, i) => {
      cells.push({
        id: row.id,
        ident: identity(row),
        row,
        file: name,
        x: x + PAGE_PAD + (i % COLS) * (CW + GAP),
        y: rowY + PAGE_HEAD + PAGE_PAD + Math.floor(i / COLS) * (CH + GAP),
      });
    });
    x += w + GAP * 2;
    rowH = Math.max(rowH, h);
  });
  const contentH = pages.length ? rowY + rowH - y - LANE_HEAD : CH;
  const h = LANE_HEAD + contentH + PAGE_PAD;
  return { name, y, h, pages, cells, hidden, empty: pages.length === 0 };
}

function layoutFrame(frame, identity, focus) {
  const snap = frame.snap || {};
  const lanes = [];
  let y = MARGIN;
  for (const [name, rows] of [['MAIN', snap.main || []], ['AUX', snap.aux || []]]) {
    const lane = layoutLane(name, rows, y, focus, identity);
    lanes.push(lane);
    y += lane.h + LANE_GAP;
  }
  if (frame.ram) {
    const rows = frame.ram.map((row, i) => ({ ...row, page: Math.floor(i / COLS), slot: i % COLS }));
    const lane = layoutLane('MEMORIA', rows, y, new Set(), identity);
    lanes.push(lane);
    y += lane.h + LANE_GAP;
  }
  const cells = lanes.flatMap((lane) => lane.cells);
  return { lanes, cells, byId: Object.fromEntries(cells.map((cell) => [cell.id, cell])), height: y, width: MAX_W + MARGIN };
}

function edgePath(from, to) {
  // Entre archivos o filas distintas: sale por abajo o por arriba de la celda.
  if (from.file !== to.file || Math.abs(from.y - to.y) >= 1) {
    const down = to.y > from.y;
    const sx = from.x + CW / 2 + (down ? 6 : -6);
    const sy = down ? from.y + CH : from.y;
    const ex = to.x + CW / 2 + (down ? -6 : 6);
    const ey = down ? to.y - 2 : to.y + CH + 2;
    const bend = Math.max(28, Math.abs(ey - sy) * 0.45) * (down ? 1 : -1);
    return `M ${sx} ${sy} C ${sx} ${sy + bend}, ${ex} ${ey - bend}, ${ex} ${ey}`;
  }
  // Vecinos en la misma fila: flecha corta.
  if (Math.abs(from.y - to.y) < 1 && to.x > from.x && to.x - from.x <= CW + GAP * 2) {
    return `M ${from.x + CW} ${from.y + CH / 2} L ${to.x - 2} ${to.y + CH / 2}`;
  }
  // Mismo archivo pero saltando entradas (p. ej. un borrado): arco por encima.
  const sx = from.x + CW * 0.72;
  const ex = to.x + CW * 0.28;
  const top = Math.min(from.y, to.y) - 14 - Math.min(16, Math.abs(ex - sx) * 0.05);
  return `M ${sx} ${from.y} C ${sx} ${top}, ${ex} ${top}, ${ex} ${to.y - 2}`;
}

function Gauge({ label, value, max, text, danger }) {
  const ratio = Math.min(1, max ? value / max : 0);
  return (
    <div className={`seqv-gauge ${danger ? 'is-danger' : ''}`}>
      <div className="flex items-center justify-between gap-2"><span>{label}</span><strong>{text}</strong></div>
      <div className="seqv-gauge-track"><div style={{ width: `${ratio * 100}%` }} /></div>
    </div>
  );
}

export default function SequentialViz({ sequential, staticView, autoPlay = true, operation }) {
  const before = sequential?.before || null;
  const after = sequential?.after || staticView || null;
  const frames = useMemo(() => buildFrames(before, after, operation), [before, after, operation]);
  const isReorg = operation === 'REORGANIZE' && Boolean(before && after);

  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(autoPlay && frames.length > 1);
  const [speed, setSpeed] = useState(1);

  useEffect(() => {
    setIndex(0);
    setPlaying(autoPlay && frames.length > 1);
  }, [frames, autoPlay]);

  const delay = BASE_DELAY / speed;
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

  // En una mutación cada entrada conserva su página y slot, así que se
  // identifica por su posición física; al reorganizar cambian de posición y
  // se siguen por su clave, para que se vea a dónde va cada registro.
  const identity = useMemo(() => {
    if (!isReorg) return (row) => row.id;
    const occurrences = new Map();
    const live = new Map();
    chainOrder(before).forEach((id) => {
      const row = rowsOf(before).find((item) => item.id === id);
      const base = `k:${row.key}`;
      const n = occurrences.get(base) || 0;
      occurrences.set(base, n + 1);
      live.set(id, `${base}#${n}`);
    });
    const afterOcc = new Map();
    const afterIdent = new Map();
    chainOrder(after).forEach((id) => {
      const row = rowsOf(after).find((item) => item.id === id);
      const base = `k:${row.key}`;
      const n = afterOcc.get(base) || 0;
      afterOcc.set(base, n + 1);
      afterIdent.set(id, `${base}#${n}`);
    });
    return (row) => {
      if (row.src === 'after') return afterIdent.get(row.id) || `ra:${row.id}`;
      return live.get(row.id) || `rb:${row.id}`;
    };
  }, [isReorg, before, after]);

  const focus = useMemo(() => new Set(frames.flatMap((frame) => [...(frame.hot || [])])), [frames]);
  const frame = frames[index] || frames[0];
  const layout = useMemo(() => (frame ? layoutFrame(frame, identity, focus) : null), [frame, identity, focus]);

  const previous = useRef(null);
  const ghosts = useMemo(() => {
    const prev = previous.current;
    if (!prev || !layout || prev === layout) return [];
    const idents = new Set(layout.cells.map((cell) => cell.ident));
    return prev.cells.filter((cell) => !idents.has(cell.ident));
  }, [layout]);
  useEffect(() => { previous.current = layout; }, [layout]);

  if (!frame || !layout) return <div className="viz-empty">Esta tabla no usa Sequential File.</div>;

  const snap = frame.snap;
  const stats = index === frames.length - 1 || !before ? (after || snap) : before;
  const hot = frame.hot || new Set();
  const hotEdges = frame.hotEdges || new Set();
  const transitionMs = Math.round(Math.min(800, delay * 0.45));
  const headId = pid(snap.head);
  const tailId = pid(snap.tail);
  const order = chainOrder(snap);
  const byId = Object.fromEntries(rowsOf(snap).map((row) => [row.id, row]));
  const wasted = stats?.wasted_ratio || 0;
  const nAux = stats?.n_aux ?? (stats?.aux || []).length;

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
            <p className="viz-eyebrow">Organización ordenada · {snap.key_column || after?.key_column}</p>
            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100 mt-0.5">MAIN / AUX en disco</h3>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-1 max-w-2xl">
              Páginas, slots y punteros next reales de storage/sequential_file.py. Los pasos intermedios siguen el orden de escritura del código.
            </p>
          </div>
          <div className="flex flex-col gap-1.5 w-56 shrink-0">
            <Gauge label="AUX" value={nAux} max={MAX_AUX} text={`${nAux} / ${MAX_AUX}`} danger={nAux >= MAX_AUX} />
            <Gauge label="Desperdicio" value={wasted} max={WASTE_THRESHOLD} text={`${Math.round(wasted * 100)}% / ${WASTE_THRESHOLD * 100}%`} danger={wasted > WASTE_THRESHOLD} />
            {stats?.needs_reorganization && <span className="seqv-alert">needs_reorganization() = True</span>}
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
            label={frame.label}
            speed={speed}
            onSpeedChange={setSpeed}
          />
        )}
        <p key={`${operation}-${index}`} className={`bpt-narration ${operation === 'DELETE' ? 'is-merge' : operation === 'REORGANIZE' ? 'is-new_root' : operation === 'INSERT' ? 'is-insert' : ''}`}>
          {frame.narration}
        </p>
      </div>

      <div className="flex-1 min-h-0 overflow-auto p-5 viz-canvas">
        {isReorg && (
          <div className="seq-phase-strip seqv-phases">
            {frames.map((item, phaseIndex) => (
              <button type="button" key={item.label} onClick={() => go(phaseIndex)} className={`seq-phase ${phaseIndex === index ? 'is-active' : ''} ${phaseIndex < index ? 'is-done' : ''}`}>
                <span>{phaseIndex + 1}</span><p>{item.label}</p>
              </button>
            ))}
          </div>
        )}

        <svg width={layout.width} height={layout.height} className="bpt-svg seqv-svg block" style={{ '--bpt-dur': `${transitionMs}ms` }} role="img" aria-label="Sequential File">
          <defs>
            {['main', 'aux', 'hot'].map((tone) => (
              <marker key={tone} id={`seqv-arrow-${tone}`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
                <path d="M0,0 L8,4 L0,8 z" className={`seqv-head-${tone}`} />
              </marker>
            ))}
          </defs>

          {layout.lanes.map((lane) => (
            <g key={`lane-${lane.name}`} className={`seqv-lane is-${lane.name.toLowerCase()}`}>
              <rect x={4} y={lane.y} width={layout.width - 8} height={lane.h} rx="12" className="seqv-lane-box" />
              <rect x={4} y={lane.y} width={4} height={lane.h} rx="2" className="seqv-lane-tab" />
              <text x={MARGIN} y={lane.y + 20} className="seqv-lane-title">{lane.name}</text>
              <text x={MARGIN + 62} y={lane.y + 20} className="seqv-lane-meta">
                {lane.name === 'MEMORIA'
                  ? `records = list(scan()) · ${lane.cells.length} registros`
                  : `${lane.cells.length} entradas · ${lane.pages.length + lane.hidden} página(s)${lane.hidden ? ` · ${lane.hidden} ocultas` : ''}`}
              </text>
              {lane.empty && <text x={MARGIN} y={lane.y + LANE_HEAD + 22} className="seqv-empty">{lane.name === 'MEMORIA' ? '' : 'archivo vacío'}</text>}
              {lane.name !== 'MEMORIA' && lane.pages.map((page) => (
                <g key={`p-${lane.name}-${page.page}`}>
                  <rect x={page.x} y={page.y} width={page.w} height={page.h} rx="8" className="seqv-page" />
                  <text x={page.x + 8} y={page.y + 13} className="seqv-page-label">PÁGINA {page.page}</text>
                </g>
              ))}
            </g>
          ))}

          {/* punteros next */}
          {layout.cells.filter((cell) => cell.file !== 'MEMORIA' && cell.row.next).map((cell) => {
            const target = layout.byId[pid(cell.row.next)];
            if (!target) return null;
            const d = edgePath(cell, target);
            const tone = hotEdges.has(cell.id) ? 'hot' : isAux(cell.row) || isAux(target.row) ? 'aux' : 'main';
            return (
              <path
                key={`e-${cell.ident}`}
                d={d}
                style={{ d: `path("${d}")` }}
                className={`seqv-edge is-${tone} ${cell.row.deleted ? 'is-dead' : ''}`}
                markerEnd={`url(#seqv-arrow-${tone})`}
              />
            );
          })}

          {/* registros */}
          {layout.cells.map((cell) => {
            const { row } = cell;
            const badge = frame.badges?.get(row.id);
            const dim = frame.badges && !badge;
            return (
              <g key={`c-${cell.ident}`} className="bpt-move" style={{ transform: `translate(${cell.x}px, ${cell.y}px)` }}>
                <g className={`seqv-cell bpt-enter is-${cell.file.toLowerCase()} ${row.deleted ? 'is-deleted' : ''} ${hot.has(row.id) ? 'is-hot' : ''} ${dim ? 'is-dim' : ''}`}>
                  <rect width={CW} height={CH} rx="7" className="seqv-cell-box" />
                  <text x={CW / 2} y={19} textAnchor="middle" className="seqv-key">{formatKey(row.key)}</text>
                  {row.deleted && <line x1={12} x2={CW - 12} y1={15} y2={15} className="seqv-strike" />}
                  <text x={CW / 2} y={35} textAnchor="middle" className="seqv-pos">
                    {cell.file === 'MEMORIA' ? `#${row.slot + row.page * COLS + 1}` : `P${row.page}:${row.slot}`}
                  </text>
                  {cell.file !== 'MEMORIA' && row.id === headId && <text x={2} y={-4} className="seqv-flag">HEAD</text>}
                  {cell.file !== 'MEMORIA' && row.id === tailId && <text x={CW - 2} y={-4} textAnchor="end" className="seqv-flag">TAIL</text>}
                  {badge && (
                    <g>
                      <circle cx={CW - 4} cy={4} r="8" className="seqv-badge" />
                      <text x={CW - 4} y={7} textAnchor="middle" className="seqv-badge-text">{badge}</text>
                    </g>
                  )}
                  <title>{`${row.values?.join(' · ') || row.key}\nnext → ${ptrText(row.next)}${row.deleted ? '\n(borrado lógico)' : ''}`}</title>
                </g>
              </g>
            );
          })}

          {ghosts.map((cell) => (
            <g key={`g-${cell.ident}-${index}`} style={{ transform: `translate(${cell.x}px, ${cell.y}px)` }}>
              <g className={`seqv-cell bpt-exit is-${cell.file.toLowerCase()} ${cell.row.deleted ? 'is-deleted' : ''}`}>
                <rect width={CW} height={CH} rx="7" className="seqv-cell-box" />
                <text x={CW / 2} y={19} textAnchor="middle" className="seqv-key">{formatKey(cell.row.key)}</text>
              </g>
            </g>
          ))}
        </svg>

        <div className="seq-chain">
          <div className="flex items-center gap-2 shrink-0">
            <GitMerge className="w-4 h-4 text-amber-500" />
            <div><p className="viz-eyebrow">Orden lógico</p><p className="text-[10px] text-slate-400">head → next → …</p></div>
          </div>
          <div className="seq-chain-flow">
            {order.length === 0 && <span className="text-[11px] text-slate-400">cadena vacía</span>}
            {order.slice(0, 30).map((id, i) => (
              <React.Fragment key={id}>
                <span className={`seq-chain-key ${id.startsWith('A-') ? 'is-aux' : ''} ${hot.has(id) ? 'seqv-chain-hot' : ''}`}>{formatKey(byId[id].key)}</span>
                {i < Math.min(order.length, 30) - 1 && <span className="text-slate-300 text-[10px]">→</span>}
              </React.Fragment>
            ))}
            {order.length > 30 && <span className="text-[10px] text-slate-400">… +{order.length - 30}</span>}
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3 text-[10px] font-mono text-slate-400">
          <span className="flex items-center gap-1"><Layers3 className="w-3 h-3" /> head {ptrText(snap.head)}</span>
          <span>tail {ptrText(snap.tail)}</span>
          <span>vivos {order.length}</span>
          <span>borrados {rowsOf(snap).filter((row) => row.deleted).length}</span>
        </div>
      </div>
    </div>
  );
}
