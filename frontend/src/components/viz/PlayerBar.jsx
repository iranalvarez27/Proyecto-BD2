import React from 'react';
import { ChevronLeft, ChevronRight, Pause, Play, RotateCcw } from 'lucide-react';

export default function PlayerBar({
  index,
  total,
  playing,
  onToggle,
  onPrev,
  onNext,
  onRestart,
  label,
  speed,
  onSpeedChange,
}) {
  const safeTotal = Math.max(1, total);
  return (
    <div className="viz-player">
      <button
        type="button"
        onClick={onRestart}
        className="viz-player-button"
        title="Reiniciar"
      >
        <RotateCcw className="w-3.5 h-3.5" />
      </button>
      <button
        type="button"
        onClick={onPrev}
        disabled={index <= 0}
        className="viz-player-button"
        title="Anterior"
      >
        <ChevronLeft className="w-3.5 h-3.5" />
      </button>
      <button
        type="button"
        onClick={onToggle}
        className="viz-player-button is-primary"
        title={playing ? 'Pausar' : 'Reproducir'}
      >
        {playing ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5 fill-current" />}
      </button>
      <button
        type="button"
        onClick={onNext}
        disabled={index >= total - 1}
        className="viz-player-button"
        title="Siguiente"
      >
        <ChevronRight className="w-3.5 h-3.5" />
      </button>
      <div className="viz-player-track">
        <div
          className="viz-player-progress"
          style={{ width: `${((index + 1) / safeTotal) * 100}%` }}
        />
      </div>
      <span className="viz-player-count">
        {Math.min(index + 1, safeTotal)}/{safeTotal}
      </span>
      {onSpeedChange && (
        <div className="viz-speed" role="group" aria-label="Velocidad">
          {[0.5, 1, 2].map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => onSpeedChange(value)}
              className={speed === value ? 'is-active' : ''}
              title={`Velocidad ${value}×`}
            >
              {value}×
            </button>
          ))}
        </div>
      )}
      {label && <span className="viz-player-label">{label}</span>}
    </div>
  );
}

export function eventLabel(event) {
  if (!event) return 'Estado actual';
  switch (event.type) {
    case 'insert':
      return `INSERT ${event.key ?? ''}`.trim();
    case 'delete':
      return `DELETE ${event.key ?? ''}`.trim();
    case 'split':
      return event.kind === 'leaf'
        ? `SPLIT hoja p${event.page_id} → p${event.new_page_id} (sep ${event.sep})`
        : event.new_bucket != null
          ? `SPLIT cubeta ${event.bucket} → ${event.new_bucket}`
          : `SPLIT interno p${event.page_id} → p${event.new_page_id}`;
    case 'merge':
      return `MERGE ${event.absorbed ?? ''} → ${event.kept ?? event.parent ?? ''}`.trim();
    case 'borrow':
      return `BORROW ${event.from_id} → ${event.to_id}`;
    case 'new_root':
      return `Nueva raíz p${event.page_id}`;
    case 'shrink_root':
      return `La raíz baja a p${event.page_id}`;
    case 'double':
      return `Directorio ×2 · profundidad global ${event.global_depth}`;
    case 'overflow':
      return `Overflow en cubeta ${event.bucket}`;
    case 'separator':
      return `Separador P${event.page_id}: ${event.old} → ${event.sep}`;
    case 'consolidate':
      return `Compactar overflow P${event.absorbed} → P${event.page}`;
    case 'full':
      return `Cubeta P${event.bucket} llena · llega ${event.key ?? ''}`.trim();
    default:
      return event.type;
  }
}
