import React, { useEffect, useMemo, useState } from 'react';
import { Map as MapIcon, MoveRight } from 'lucide-react';
import PlayerBar from './PlayerBar';

/*
 * R-Tree de index/rtree.py. El árbol es rtree.snapshot() y los pasos son la
 * traza real que emite la consulta (radius_search, _collect para polígonos,
 * _knn_traced / nearest_iter para k-NN), en el mismo orden en que el código
 * lee las páginas.
 */

const METERS_PER_DEGREE = (Math.PI * 6371000) / 180; // common/geo.py
const PLANE_W = 560;
const PLANE_H = 440;
const PAD = 18;
const BASE_DELAY = 1700;
const LEVEL_COLORS = ['#d97706', '#8b5cf6', '#6366f1', '#0ea5e9'];

const fmtDist = (meters) => {
  if (meters == null || Number.isNaN(meters)) return '—';
  return meters < 1000 ? `${Math.round(meters)} m` : `${(meters / 1000).toFixed(2)} km`;
};

/* ---------- Pasos a partir de la traza ---------- */

function buildFrames(tree, trace, query, stats) {
  if (!tree?.nodes?.length) return [];
  const byId = Object.fromEntries(tree.nodes.map((node) => [node.id, node]));
  const tipo = query?.tipo;
  const frames = [];
  const state = { visited: new Set(), pruned: new Map(), full: new Set(), matches: [], hits: [] };
  const push = (frame) => frames.push({
    ...frame,
    visited: new Set(state.visited),
    pruned: new Map(state.pruned),
    full: new Set(state.full),
    matches: [...state.matches],
    hits: [...state.hits],
  });

  const intro = {
    radio: `Búsqueda por radio de ${fmtDist(query?.radio_m)} (${query?.metrica || 'haversine'}). radius_search usa una pila (DFS) desde la raíz y descarta todo nodo cuyo MBR esté a MINDIST > radio del centro.`,
    poligono: `Búsqueda dentro de un polígono de ${query?.poligono?.length || 0} vértices. _collect usa una pila (DFS) y descarta los nodos cuyo MBR no intersecta la caja del polígono.`,
    knn: `k-NN con k = ${query?.k}. Búsqueda best-first: una cola de prioridad ordenada por MINDIST mezcla nodos y puntos; siempre se saca lo más cercano pendiente.`,
  }[tipo] || 'Consulta espacial sobre el R-Tree.';
  push({ label: 'Consulta', narration: intro });

  const order = trace?.order || [];
  let i = 0;
  while (i < order.length) {
    const event = order[i];
    if (event.type === 'visit') {
      const node = byId[event.id];
      state.visited.add(event.id);
      if (event.full) state.full.add(event.id);
      (event.full_children || []).forEach((id) => state.full.add(id));
      const prunedHere = [];
      let j = i + 1;
      while (j < order.length && order[j].type === 'prune' && order[j].parent === event.id) {
        state.pruned.set(order[j].id, order[j]);
        prunedHere.push(order[j]);
        j += 1;
      }
      (event.matches || []).forEach((point) => state.matches.push(point));
      push({
        label: `Leer P${event.id}`,
        current: event.id,
        prunedNow: new Set(prunedHere.map((item) => item.id)),
        narration: narrateVisit(event, node, prunedHere, query, tipo),
      });
      i = j;
      continue;
    }
    if (event.type === 'hit') {
      state.hits.push({ point: event.point, dist: event.dist });
      push({
        label: `Vecino #${state.hits.length}`,
        hitNow: state.hits.length - 1,
        narration: `Sale de la cola un punto a ${fmtDist(event.dist)}. Como la cola está ordenada por distancia, ningún nodo pendiente puede contener algo más cerca: es el vecino #${state.hits.length}${query?.k ? ` de ${query.k}` : ''}.`,
      });
      i += 1;
      continue;
    }
    if (event.type === 'prune') {
      const leftover = [];
      while (i < order.length && order[i].type === 'prune') {
        state.pruned.set(order[i].id, order[i]);
        leftover.push(order[i]);
        i += 1;
      }
      push({
        label: 'Parar',
        prunedNow: new Set(leftover.map((item) => item.id)),
        narration: `Ya hay ${state.hits.length} vecino(s): la búsqueda se detiene y ${leftover.length} nodo(s) quedan en la cola sin leerse (${leftover.map((item) => `P${item.id}`).join(', ')}). Esas páginas nunca se cargan de disco.`,
      });
      continue;
    }
    i += 1;
  }

  const total = tree.nodes.length;
  push({
    label: 'Resultado',
    narration: `Resultado: ${stats?.candidatos ?? state.matches.length + state.hits.length} candidato(s). Se leyeron ${state.visited.size} de ${total} páginas (${stats?.hojas_visitadas ?? '—'} hojas) y ${state.pruned.size} subárbol(es) se podaron sin leerse.`,
  });
  return frames;
}

function narrateVisit(event, node, prunedHere, query, tipo) {
  const kind = node?.leaf ? 'hoja' : 'nodo interno';
  const n = node?.count ?? (node?.children?.length || 0);
  if (tipo === 'knn') {
    const base = `Sale de la cola P${event.id} (${kind}) con MINDIST ${fmtDist(event.dist)}: es lo más cercano que queda pendiente.`;
    return node?.leaf
      ? `${base} Sus ${n} puntos entran a la cola con su distancia exacta.`
      : `${base} Sus ${n} hijos entran a la cola con su MINDIST.`;
  }
  const radio = tipo === 'radio';
  if (event.full) {
    return node?.leaf
      ? `P${event.id} pertenece a un subárbol completo: sus ${n} puntos se aceptan sin calcular distancias.`
      : `P${event.id} está entero dentro de la consulta: todos sus hijos se apilan como completos, sin más comprobaciones.`;
  }
  if (node?.leaf) {
    const hits = event.hits ?? 0;
    const test = radio ? `se calcula la distancia a sus ${n} puntos; ${hits} están a ≤ ${fmtDist(query?.radio_m)}` : `se prueba cada uno de sus ${n} puntos contra el polígono; ${hits} caen dentro`;
    const miss = hits === 0 ? ' Su MBR tocaba la consulta pero ningún punto la cumple: es el costo de aproximar con rectángulos.' : '';
    return `Se saca P${event.id} de la pila: es una hoja y ${test}.${miss}`;
  }
  const pruned = prunedHere.length;
  const full = (event.full_children || []).length;
  const pushed = (node?.children?.length || 0) - pruned;
  const criterio = radio ? `se calcula MINDIST(centro, MBR) de sus ${node?.children?.length || 0} hijos` : `se compara el MBR de sus ${node?.children?.length || 0} hijos con la caja del polígono`;
  return `Se saca P${event.id} de la pila (nodo interno): ${criterio}. ${pushed} se apilan${full ? ` (${full} enteros dentro de la consulta${radio ? ': MAXDIST ≤ radio' : ''})` : ''} y ${pruned} se podan${pruned ? (radio ? ' porque MINDIST > radio' : ' porque su MBR no intersecta') : ''}.`;
}

/* ---------- Proyección del plano ---------- */

function makeProjection(tree, query) {
  const lats = [];
  const lons = [];
  tree.nodes.forEach((node) => {
    if (node.mbr) {
      lons.push(node.mbr[0], node.mbr[2]);
      lats.push(node.mbr[1], node.mbr[3]);
    }
  });
  if (query?.centro) {
    const [lat, lon] = query.centro;
    const r = (query.radio_m || 0) / METERS_PER_DEGREE;
    const cos = Math.cos((lat * Math.PI) / 180) || 1;
    lats.push(lat - r, lat + r);
    lons.push(lon - r / cos, lon + r / cos);
  }
  (query?.poligono || []).forEach(([lat, lon]) => { lats.push(lat); lons.push(lon); });
  if (!lats.length) return null;
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);
  const cos = Math.cos((((minLat + maxLat) / 2) * Math.PI) / 180) || 1;
  const spanX = Math.max(1e-9, (maxLon - minLon) * cos);
  const spanY = Math.max(1e-9, maxLat - minLat);
  const scale = Math.min((PLANE_W - PAD * 2) / spanX, (PLANE_H - PAD * 2) / spanY);
  const offX = (PLANE_W - spanX * scale) / 2;
  const offY = (PLANE_H - spanY * scale) / 2;
  return {
    x: (lon) => offX + (lon - minLon) * cos * scale,
    y: (lat) => PLANE_H - (offY + (lat - minLat) * scale),
    meters: (m) => (m / METERS_PER_DEGREE) * scale,
  };
}

/* ---------- Diagrama del árbol ---------- */

function layoutTree(tree) {
  const byId = Object.fromEntries(tree.nodes.map((node) => [node.id, node]));
  const levels = [];
  const walk = (id, depth) => {
    const node = byId[id];
    if (!node) return;
    (levels[depth] ||= []).push(id);
    (node.children || []).forEach((child) => walk(child, depth + 1));
  };
  walk(tree.root, 0);
  const BOX_W = 46;
  const BOX_H = 30;
  const GAP_X = 10;
  const GAP_Y = 54;
  const pos = {};
  const deepest = levels.length - 1;
  levels[deepest]?.forEach((id, i) => { pos[id] = { x: 10 + i * (BOX_W + GAP_X), y: 10 + deepest * GAP_Y }; });
  for (let d = deepest - 1; d >= 0; d -= 1) {
    let minX = 10;
    levels[d].forEach((id) => {
      const kids = (byId[id].children || []).map((child) => pos[child]).filter(Boolean);
      let x = kids.length ? (kids[0].x + kids.at(-1).x) / 2 : minX;
      x = Math.max(x, minX);
      pos[id] = { x, y: 10 + d * GAP_Y };
      minX = x + BOX_W + GAP_X;
    });
  }
  const width = Math.max(200, ...Object.values(pos).map((p) => p.x + BOX_W + 10));
  const height = 10 + levels.length * GAP_Y - (GAP_Y - BOX_H) + 10;
  return { pos, width, height, BOX_W, BOX_H, byId };
}

function nodeState(id, frame) {
  if (!frame) return '';
  if (frame.current === id) return 'is-current';
  if (frame.prunedNow?.has(id)) return 'is-pruned is-pruned-now';
  if (frame.pruned?.has(id)) return 'is-pruned';
  if (frame.full?.has(id) && frame.visited?.has(id)) return 'is-full';
  if (frame.visited?.has(id)) return 'is-visited';
  return '';
}

export default function RTreeViz({ query, staticView, onOpenMap }) {
  const tree = query?.tree || staticView?.disk || null;
  const trace = query?.trace || null;
  const q = query?.query || null;
  const frames = useMemo(() => (trace ? buildFrames(tree, trace, q, query?.stats) : []), [tree, trace, q, query]);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(frames.length > 1);
  const [speed, setSpeed] = useState(1);
  const [level, setLevel] = useState('all');
  const [hover, setHover] = useState(null);
  const [zoomed, setZoomed] = useState(true);

  useEffect(() => {
    setIndex(0);
    setPlaying(frames.length > 1);
  }, [frames]);

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

  const proj = useMemo(() => (tree ? makeProjection(tree, q) : null), [tree, q]);
  const diagram = useMemo(() => (tree?.nodes?.length ? layoutTree(tree) : null), [tree]);

  if (!tree || !proj || !diagram) {
    return <div className="viz-empty">Esta tabla no tiene un índice R-Tree.</div>;
  }

  const frame = frames[index] || null;
  const height = tree.height || 1;

  // Zoom a la zona de la consulta: la caja del radio/polígono o, en k-NN,
  // la de todos los vecinos que devuelve la traza.
  const focus = (() => {
    if (!q) return null;
    const xs = [];
    const ys = [];
    const add = (lat, lon) => { xs.push(proj.x(lon)); ys.push(proj.y(lat)); };
    if (q.tipo === 'radio' && q.centro) {
      const r = proj.meters(q.radio_m || 0);
      xs.push(proj.x(q.centro[1]) - r, proj.x(q.centro[1]) + r);
      ys.push(proj.y(q.centro[0]) - r, proj.y(q.centro[0]) + r);
    }
    (q.poligono || []).forEach(([lat, lon]) => add(lat, lon));
    if (q.tipo === 'knn' && q.centro) {
      add(q.centro[0], q.centro[1]);
      (trace?.order || []).filter((event) => event.type === 'hit').forEach((event) => add(event.point[0], event.point[1]));
    }
    if (!xs.length) return null;
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
    const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    const span = Math.max(40, (Math.max(...xs) - Math.min(...xs)) * 1.6, (Math.max(...ys) - Math.min(...ys)) * 1.6 * (PLANE_W / PLANE_H));
    const w = Math.min(PLANE_W, span);
    const h = w * (PLANE_H / PLANE_W);
    return { x: cx - w / 2, y: cy - h / 2, w, h };
  })();
  const view = zoomed && focus ? focus : { x: 0, y: 0, w: PLANE_W, h: PLANE_H };
  const z = PLANE_W / view.w;
  const levels = Array.from({ length: height }, (_, i) => i);
  const nodes = [...tree.nodes].sort((a, b) => a.level - b.level);
  const visibleLevel = (node) => level === 'all' || node.level === Number(level);
  const allPoints = tree.nodes.filter((node) => node.leaf).flatMap((node) => (node.points || []).map((p) => ({ p, leaf: node.id })));
  const matchSet = new Set((frame?.matches || []).map(([lat, lon]) => `${lat},${lon}`));
  const go = (next) => { setPlaying(false); setIndex(Math.max(0, Math.min(frames.length - 1, next))); };
  const onKeyDown = (keyEvent) => {
    if (frames.length < 2) return;
    if (keyEvent.key === 'ArrowRight') { keyEvent.preventDefault(); go(index + 1); }
    if (keyEvent.key === 'ArrowLeft') { keyEvent.preventDefault(); go(index - 1); }
    if (keyEvent.key === ' ') { keyEvent.preventDefault(); setPlaying((value) => !value); }
  };
  const colorOf = (node) => (node.leaf ? '#059669' : LEVEL_COLORS[node.level % LEVEL_COLORS.length]);

  return (
    <div className="flex flex-col h-full min-h-0 outline-none" tabIndex={0} onKeyDown={onKeyDown}>
      <div className="viz-toolbar shrink-0">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="viz-eyebrow">Índice espacial · {q?.columna || staticView?.column || 'punto'}</p>
            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100 mt-0.5">
              {q ? `Recorrido de la consulta ${q.tipo === 'knn' ? 'k-NN' : q.tipo}` : 'MBR por nivel'}
            </h3>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-1 max-w-2xl">
              Páginas reales de index/rtree.py ({height} nivel{height === 1 ? '' : 'es'}, {tree.nodes.length} páginas).
              {q ? ' Cada paso es un evento de la traza que emite la consulta.' : ' Ejecuta una consulta por radio, polígono o k-NN para ver qué páginas se leen y cuáles se podan.'}
            </p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <div className="viz-segmented">
              <button type="button" onClick={() => setLevel('all')} className={level === 'all' ? 'is-active' : ''}>Todos</button>
              {levels.map((lvl) => (
                <button type="button" key={lvl} onClick={() => setLevel(String(lvl))} className={level === String(lvl) ? 'is-active' : ''}>
                  {lvl === height - 1 ? 'Hojas' : lvl === 0 ? 'Raíz' : `Nivel ${lvl}`}
                </button>
              ))}
            </div>
            {onOpenMap && (
              <button type="button" className="rtv-map-link" onClick={onOpenMap}>
                <MapIcon className="w-3.5 h-3.5" /> Ver sobre el mapa <MoveRight className="w-3 h-3" />
              </button>
            )}
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
            label={frame?.label}
            speed={speed}
            onSpeedChange={setSpeed}
          />
        )}
        {frame && (
          <p key={index} className={`bpt-narration ${frame.prunedNow?.size ? 'is-merge' : frame.current != null ? 'is-insert' : frame.hitNow != null ? 'is-split' : 'is-new_root'}`}>
            {frame.narration}
          </p>
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-auto p-5 viz-canvas">
        <div className="rtv-grid">
          <section className="rtv-card">
            <div className="flex items-center justify-between mb-2">
              <p className="viz-eyebrow">Plano · lon × lat</p>
              {focus && (
                <div className="viz-segmented">
                  <button type="button" onClick={() => setZoomed(true)} className={zoomed ? 'is-active' : ''}>Zona de la consulta</button>
                  <button type="button" onClick={() => setZoomed(false)} className={!zoomed ? 'is-active' : ''}>Árbol completo</button>
                </div>
              )}
            </div>
            <svg viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`} className="rtv-plane" role="img" aria-label="MBR del R-Tree" style={{ '--z': z }}>
              {/* consulta */}
              {q?.tipo === 'radio' && q.centro && (
                <circle cx={proj.x(q.centro[1])} cy={proj.y(q.centro[0])} r={proj.meters(q.radio_m)} className="rtv-query" />
              )}
              {q?.tipo === 'poligono' && q.poligono && (
                <polygon points={q.poligono.map(([lat, lon]) => `${proj.x(lon)},${proj.y(lat)}`).join(' ')} className="rtv-query" />
              )}

              {/* MBR, de la raíz a las hojas */}
              {nodes.filter((node) => node.mbr && visibleLevel(node)).map((node) => {
                const [x1, y1, x2, y2] = node.mbr;
                const x = proj.x(x1);
                const y = proj.y(y2);
                const w = Math.max(2, proj.x(x2) - x);
                const h = Math.max(2, proj.y(y1) - y);
                const state = nodeState(node.id, frame);
                return (
                  <rect
                    key={`m-${node.id}`}
                    x={x}
                    y={y}
                    width={w}
                    height={h}
                    rx={(node.leaf ? 2 : 4) / z}
                    className={`rtv-mbr ${node.leaf ? 'is-leaf' : 'is-inner'} ${state} ${hover === node.id ? 'is-hover' : ''}`}
                    style={{ '--mbr-color': colorOf(node) }}
                    onMouseEnter={() => setHover(node.id)}
                    onMouseLeave={() => setHover(null)}
                  >
                    <title>{`P${node.id} · ${node.leaf ? 'hoja' : `nivel ${node.level}`} · ${node.count} entradas`}</title>
                  </rect>
                );
              })}

              {/* puntos */}
              {allPoints.map(({ p: [lat, lon], leaf }, i) => (
                <circle
                  key={`p-${i}`}
                  cx={proj.x(lon)}
                  cy={proj.y(lat)}
                  r={(matchSet.has(`${lat},${lon}`) ? 2.6 : 1.5) / Math.sqrt(z)}
                  className={`rtv-point ${matchSet.has(`${lat},${lon}`) ? 'is-match' : ''} ${frame?.pruned?.has(leaf) ? 'is-pruned' : ''}`}
                />
              ))}

              {/* vecinos k-NN */}
              {(frame?.hits || []).map((hit, i) => (
                <g key={`h-${i}`} className={i === frame.hitNow ? 'rtv-hit is-now' : 'rtv-hit'}>
                  <line x1={proj.x(q.centro[1])} y1={proj.y(q.centro[0])} x2={proj.x(hit.point[1])} y2={proj.y(hit.point[0])} />
                  <circle cx={proj.x(hit.point[1])} cy={proj.y(hit.point[0])} r={5 / z} />
                  <text x={proj.x(hit.point[1]) + 7 / z} y={proj.y(hit.point[0]) - 6 / z} style={{ fontSize: `${10 / z}px`, strokeWidth: `${3 / z}px` }}>{i + 1}</text>
                </g>
              ))}

              {q?.centro && (
                <g className="rtv-center">
                  <circle cx={proj.x(q.centro[1])} cy={proj.y(q.centro[0])} r={4.5 / z} />
                </g>
              )}
            </svg>
            <div className="rtv-legend">
              {levels.map((lvl) => {
                const sample = tree.nodes.find((node) => node.level === lvl);
                return <span key={lvl}><i style={{ borderColor: sample ? colorOf(sample) : '#94a3b8' }} />{lvl === height - 1 ? 'hoja' : lvl === 0 ? 'raíz' : `nivel ${lvl}`}</span>;
              })}
              {q && <><span><i className="is-current" />leyendo</span><span><i className="is-visited" />leída</span><span><i className="is-full" />completa</span><span><i className="is-pruned" />podada</span></>}
            </div>
          </section>

          <section className="rtv-card">
            <p className="viz-eyebrow mb-2">Árbol · páginas</p>
            <svg viewBox={`0 0 ${diagram.width} ${diagram.height}`} className="rtv-tree" style={{ maxHeight: 260 }}>
              {tree.nodes.flatMap((node) => (node.children || []).map((child) => {
                const a = diagram.pos[node.id];
                const b = diagram.pos[child];
                if (!a || !b) return null;
                const state = nodeState(child, frame);
                return (
                  <line
                    key={`t-${node.id}-${child}`}
                    x1={a.x + diagram.BOX_W / 2}
                    y1={a.y + diagram.BOX_H}
                    x2={b.x + diagram.BOX_W / 2}
                    y2={b.y}
                    className={`rtv-tree-edge ${state}`}
                  />
                );
              }))}
              {tree.nodes.map((node) => {
                const p = diagram.pos[node.id];
                if (!p) return null;
                return (
                  <g
                    key={`n-${node.id}`}
                    transform={`translate(${p.x}, ${p.y})`}
                    className={`rtv-node ${nodeState(node.id, frame)} ${hover === node.id ? 'is-hover' : ''}`}
                    style={{ '--mbr-color': colorOf(node) }}
                    onMouseEnter={() => setHover(node.id)}
                    onMouseLeave={() => setHover(null)}
                  >
                    <rect width={diagram.BOX_W} height={diagram.BOX_H} rx="6" />
                    <text x={diagram.BOX_W / 2} y={13} textAnchor="middle" className="rtv-node-id">P{node.id}</text>
                    <text x={diagram.BOX_W / 2} y={24} textAnchor="middle" className="rtv-node-count">{node.count}</text>
                  </g>
                );
              })}
            </svg>

            {query?.stats && (
              <div className="grid grid-cols-3 gap-2 mt-3">
                <div className="viz-metric-card"><span /><span>Páginas leídas</span><strong>{query.stats.nodos_visitados ?? '—'}</strong></div>
                <div className="viz-metric-card"><span /><span>Hojas leídas</span><strong>{query.stats.hojas_visitadas ?? '—'}</strong></div>
                <div className="viz-metric-card"><span /><span>Candidatos</span><strong>{query.stats.candidatos ?? '—'}</strong></div>
              </div>
            )}

            {frames.length > 1 && (
              <div className="mt-3 space-y-1.5 rtv-steps">
                {frames.map((item, frameIndex) => (
                  <button
                    type="button"
                    key={frameIndex}
                    onClick={() => go(frameIndex)}
                    className={`viz-event-card w-full text-left ${item.prunedNow?.size ? 'viz-event-merge' : item.hitNow != null ? 'viz-event-split' : ''} ${frameIndex === index ? 'is-current' : ''}`}
                  >
                    <span className="viz-event-index">{String(frameIndex + 1).padStart(2, '0')}</span>
                    <div>
                      <p className="font-semibold text-slate-700 dark:text-slate-200">{item.label}</p>
                      {item.prunedNow?.size > 0 && <p className="text-[10px] text-slate-400">poda {[...item.prunedNow].map((id) => `P${id}`).join(', ')}</p>}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
