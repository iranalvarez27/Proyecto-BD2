import React, { useEffect, useMemo, useState } from 'react';
import { Binary, DatabaseZap, GitFork, Layers3, Map as MapIcon, RefreshCw } from 'lucide-react';
import BPlusViz from './viz/BPlusViz';
import HashViz from './viz/HashViz';
import SequentialViz from './viz/SequentialViz';
import RTreeViz from './viz/RTreeViz';

const TABS = [
  { id: 'bplus', label: 'B+ Tree', hint: 'orden y páginas', Icon: GitFork, tone: 'indigo' },
  { id: 'hash', label: 'Hash', hint: 'directorio y buckets', Icon: Binary, tone: 'violet' },
  { id: 'sequential', label: 'Sequential', hint: 'MAIN y AUX', Icon: Layers3, tone: 'sky' },
  { id: 'rtree', label: 'R-Tree', hint: 'MBR y recorrido', Icon: MapIcon, tone: 'emerald' },
];

function pickTab(visualize, snapshot) {
  if (visualize?.operation === 'REORGANIZE') return 'sequential';
  if (visualize?.rtree_query) return 'rtree';
  const kinds = (visualize?.animations || []).map((animation) => animation.kind);
  if (kinds.includes('bplus')) return 'bplus';
  if (kinds.includes('hash')) return 'hash';
  if (visualize?.sequential && kinds.length === 0) return 'sequential';
  if ((snapshot?.indexes || []).some((index) => index.type === 'bplus' || index.type === 'clustered')) return 'bplus';
  if ((snapshot?.indexes || []).some((index) => index.type === 'hash')) return 'hash';
  if (snapshot?.sequential) return 'sequential';
  if ((snapshot?.indexes || []).some((index) => index.type === 'rtree')) return 'rtree';
  return 'bplus';
}

function EmptyStructure({ title }) {
  return (
    <div className="h-full flex items-center justify-center p-8 viz-canvas">
      <div className="text-center max-w-sm">
        <div className="w-12 h-12 rounded-2xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center mx-auto mb-3">
          <DatabaseZap className="w-5 h-5 text-slate-400" />
        </div>
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">{title}</h3>
        <p className="text-[11px] text-slate-400 mt-1">Selecciona una tabla que tenga esta estructura o crea el índice desde el editor SQL.</p>
      </div>
    </div>
  );
}

export default function VisualizePanel({ tableName, tables, visualize, onSelectTable, onOpenMap }) {
  const [snapshot, setSnapshot] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState('bplus');

  useEffect(() => {
    if (!tableName) {
      setSnapshot(null);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    fetch(`/api/visualize/${encodeURIComponent(tableName)}`)
      .then((response) => (response.ok ? response.json() : response.json().then((body) => Promise.reject(new Error(body.detail || 'No se pudo cargar la estructura')))))
      .then((data) => {
        if (!cancelled) {
          setSnapshot(data);
          setError(null);
        }
      })
      .catch((requestError) => {
        if (!cancelled) {
          setSnapshot(null);
          setError(requestError.message);
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [tableName, visualize]);

  useEffect(() => {
    setTab(pickTab(visualize, snapshot));
  }, [visualize, snapshot]);

  const animations = visualize?.animations || [];
  const bplusAnim = animations.find((animation) => animation.kind === 'bplus');
  const hashAnim = animations.find((animation) => animation.kind === 'hash');
  const bplusStatic = (snapshot?.indexes || []).find((index) => index.type === 'bplus' || index.type === 'clustered');
  const hashStatic = (snapshot?.indexes || []).find((index) => index.type === 'hash');
  const rtreeStatic = (snapshot?.indexes || []).find((index) => index.type === 'rtree');
  const seqStatic = snapshot?.sequential;
  const seqAnim = visualize?.sequential || null;
  const availability = useMemo(() => ({
    bplus: Boolean(bplusAnim || bplusStatic),
    hash: Boolean(hashAnim || hashStatic),
    sequential: Boolean(seqAnim || seqStatic),
    rtree: Boolean(rtreeStatic || visualize?.rtree_query),
  }), [bplusAnim, bplusStatic, hashAnim, hashStatic, seqAnim, seqStatic, rtreeStatic, visualize]);

  return (
    <div className="structure-studio h-full min-h-0">
      <aside className="structure-rail">
        <div className="structure-rail-brand"><DatabaseZap className="w-4 h-4" /><span>INSPECTOR</span></div>
        <div className="structure-tabs">
          {TABS.map(({ id, label, hint, Icon, tone }) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              className={`structure-tab tone-${tone} ${tab === id ? 'is-active' : ''}`}
            >
              <span className="structure-tab-icon"><Icon className="w-4 h-4" /></span>
              <span><strong>{label}</strong><small>{hint}</small></span>
              <span className={`structure-availability ${availability[id] ? 'is-ready' : ''}`} />
            </button>
          ))}
        </div>
        <div className="structure-rail-note">
          <span>Estado</span>
          <strong>{visualize?.operation ? `${visualize.operation} capturado` : 'snapshot estable'}</strong>
          <small>{snapshot?.indexes?.length || 0} índices visibles</small>
        </div>
      </aside>

      <section className="min-w-0 min-h-0 flex flex-col flex-1">
        <header className="structure-header">
          <div>
            <p className="viz-eyebrow">Laboratorio de estructuras</p>
            <div className="flex items-center gap-2 mt-1">
              <select value={tableName || ''} onChange={(event) => onSelectTable(event.target.value)} className="structure-table-select">
                {(tables || []).map((table) => <option key={table.name} value={table.name}>{table.name}</option>)}
              </select>
              {visualize?.operation && <span className="structure-operation">{visualize.operation}</span>}
            </div>
          </div>
          <div className="text-right">
            <p className="text-[10px] uppercase tracking-widest text-slate-400">Fuente de datos</p>
            <p className="text-[11px] text-slate-600 dark:text-slate-300 mt-1 flex items-center gap-1.5">
              {loading && <RefreshCw className="w-3 h-3 animate-spin" />}
              motor real · páginas persistidas
            </p>
          </div>
        </header>

        <div className="flex-1 min-h-0 overflow-hidden">
          {error && <div className="viz-empty text-rose-500">{error}</div>}
          {!error && tab === 'bplus' && (availability.bplus
            ? <BPlusViz animation={bplusAnim} staticView={bplusStatic} autoPlay={Boolean(bplusAnim)} />
            : <EmptyStructure title="Sin B+ Tree en esta tabla" />)}
          {!error && tab === 'hash' && (availability.hash
            ? <HashViz animation={hashAnim} staticView={hashStatic} autoPlay={Boolean(hashAnim)} />
            : <EmptyStructure title="Sin Hash extensible en esta tabla" />)}
          {!error && tab === 'sequential' && (availability.sequential
            ? <SequentialViz sequential={seqAnim} staticView={seqStatic} autoPlay={Boolean(seqAnim)} operation={visualize?.operation} />
            : <EmptyStructure title="La tabla no usa Sequential File" />)}
          {!error && tab === 'rtree' && (availability.rtree
            ? <RTreeViz
              query={!visualize?.table || visualize.table === tableName ? visualize?.rtree_query : null}
              staticView={rtreeStatic}
              onOpenMap={onOpenMap}
            />
            : <EmptyStructure title="Sin R-Tree en esta tabla" />)}
        </div>
      </section>
    </div>
  );
}
