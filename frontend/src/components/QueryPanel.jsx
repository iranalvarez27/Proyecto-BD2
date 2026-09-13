import React, { useState } from 'react';
import { 
  Play, 
  GitBranch, 
  RotateCcw, 
  Terminal, 
  Clock, 
  Code2, 
  Sparkles 
} from 'lucide-react';

const SQL_TEMPLATES = [
  { label: 'SELECT * Estudiantes (Heap Scan)', sql: 'SELECT * FROM estudiantes;' },
  { label: 'B+ Tree Index Scan (Igualdad id=1)', sql: 'SELECT * FROM estudiantes WHERE id = 1;' },
  { label: 'B+ Tree Range Search (id > 3)', sql: 'SELECT * FROM estudiantes WHERE id > 3;' },
  { label: 'B+ Tree Lectura Ordenada (ORDER BY id DESC)', sql: 'SELECT * FROM estudiantes ORDER BY id DESC;' },
  { label: 'Extendible Hash Scan (carrera)', sql: "SELECT * FROM estudiantes WHERE carrera = 'Ciencia de Datos';" },
  { label: 'Sequential Binary Search (codigo=101)', sql: 'SELECT * FROM cursos WHERE codigo = 101;' },
  { label: 'GROUP BY por carrera', sql: 'SELECT carrera FROM estudiantes GROUP BY carrera;' },
  { label: 'INSERT en Heap + Actualización Índices', sql: "INSERT INTO estudiantes VALUES (12, 'Valeria Gomez', 'Bioingenieria', 19.5);" },
  { label: 'DELETE en Heap + Limpieza de Índices', sql: 'DELETE FROM estudiantes WHERE id = 12;' },
  { label: 'Transacción: BEGIN', sql: 'BEGIN TRANSACTION;' },
  { label: 'Transacción: COMMIT', sql: 'COMMIT;' },
];


export default function QueryPanel({ 
  query, 
  setQuery, 
  onExecute, 
  onExplain, 
  loading, 
  history = [] 
}) {
  const [selectedTemplate, setSelectedTemplate] = useState('');

  const handleKeyDown = (e) => {
    // Cmd+Enter or Ctrl+Enter to execute
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      onExecute();
    }
  };

  const handleTemplateChange = (e) => {
    const val = e.target.value;
    setSelectedTemplate(val);
    if (val) {
      setQuery(val);
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-900 border-b border-slate-800 text-slate-100">
      {/* Panel Header */}
      <div className="p-2.5 border-b border-slate-800 flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-indigo-400" />
          <h2 className="font-semibold text-xs tracking-wide uppercase text-slate-300">
            Panel de Consultas SQL
          </h2>
        </div>

        {/* Quick templates dropdown */}
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-400 flex items-center gap-1">
            <Sparkles className="w-3.5 h-3.5 text-amber-400" />
            <span className="hidden sm:inline">Ejemplos:</span>
          </label>
          <select 
            value={selectedTemplate} 
            onChange={handleTemplateChange}
            className="bg-slate-800 border border-slate-700 text-xs text-slate-200 rounded px-2 py-1 outline-none focus:border-indigo-500 max-w-[200px] truncate"
          >
            <option value="">Seleccionar consulta...</option>
            {SQL_TEMPLATES.map((tmpl, idx) => (
              <option key={idx} value={tmpl.sql}>{tmpl.label}</option>
            ))}
          </select>

          {/* Action buttons */}
          <button
            onClick={() => setQuery('')}
            title="Limpiar editor"
            className="p-1.5 hover:bg-slate-800 text-slate-400 hover:text-slate-200 rounded transition"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>

          <button
            onClick={onExplain}
            disabled={loading || !query.trim()}
            className="flex items-center gap-1.5 px-2.5 py-1 bg-purple-600/20 hover:bg-purple-600/30 border border-purple-500/40 text-purple-200 hover:text-white rounded text-xs font-medium transition disabled:opacity-50"
            title="Ver Plan de Ejecución (EXPLAIN)"
          >
            <GitBranch className="w-3.5 h-3.5" />
            <span>EXPLAIN</span>
          </button>

          <button
            onClick={onExecute}
            disabled={loading || !query.trim()}
            className="flex items-center gap-1.5 px-3 py-1 bg-indigo-600 hover:bg-indigo-500 text-white rounded text-xs font-semibold shadow-sm transition disabled:opacity-50"
            title="Ejecutar consulta (Cmd/Ctrl + Enter)"
          >
            <Play className={`w-3.5 h-3.5 fill-current ${loading ? 'animate-spin' : ''}`} />
            <span>Ejecutar</span>
            <kbd className="hidden md:inline-block bg-indigo-800/80 px-1 py-0.2 rounded text-[10px] font-mono text-indigo-200">
              ⌘↵
            </kbd>
          </button>
        </div>
      </div>

      {/* Editor Area */}
      <div className="relative flex-1 min-h-[140px] flex">
        {/* Line numbers indicator */}
        <div className="w-8 py-3 bg-slate-950/40 text-slate-600 select-none text-right pr-2 font-mono text-xs border-r border-slate-800/40">
          <div>1</div>
          <div>2</div>
          <div>3</div>
          <div>4</div>
          <div>5</div>
        </div>

        {/* Textarea */}
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="-- Escribe tu consulta SQL aquí...&#10;SELECT * FROM estudiantes;&#10;-- Atajo: Presiona ⌘ + Enter o Ctrl + Enter para ejecutar"
          className="flex-1 w-full p-3 bg-slate-950/20 text-slate-100 font-mono text-xs sm:text-sm outline-none resize-none placeholder-slate-600 leading-relaxed"
          spellCheck="false"
        />
      </div>

      {/* Query History Bar */}
      {history.length > 0 && (
        <div className="px-3 py-1.5 bg-slate-950/40 border-t border-slate-800/60 flex items-center gap-2 overflow-x-auto text-[11px] text-slate-400">
          <Clock className="w-3 h-3 text-slate-500 shrink-0" />
          <span className="shrink-0 text-slate-500">Historial:</span>
          <div className="flex items-center gap-1.5">
            {history.slice(-4).reverse().map((h, i) => (
              <button
                key={i}
                onClick={() => setQuery(h)}
                className="bg-slate-800/80 hover:bg-slate-800 text-slate-300 hover:text-white px-2 py-0.5 rounded font-mono truncate max-w-[180px] border border-slate-700/50 transition"
                title={h}
              >
                {h}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
