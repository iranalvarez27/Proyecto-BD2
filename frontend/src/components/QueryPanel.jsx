import React, { useState, useRef } from 'react';
import {
  Play,
  GitBranch,
  RotateCcw,
  Terminal,
  Clock,
  Code2,
  Sparkles,
  Gauge,
  Upload
} from 'lucide-react';

const SQL_TEMPLATES = [
  { label: 'SELECT * Estudiantes (Heap Scan)', sql: 'SELECT * FROM estudiantes;' },
  { label: 'B+ Tree Index Scan (Igualdad id=1)', sql: 'SELECT * FROM estudiantes WHERE id = 1;' },
  { label: 'B+ Tree Range Search (id > 3)', sql: 'SELECT * FROM estudiantes WHERE id > 3;' },
  { label: 'BETWEEN (rango con indice, id 2 a 4)', sql: 'SELECT * FROM estudiantes WHERE id BETWEEN 2 AND 4;' },
  { label: 'B+ Tree Lectura Ordenada (ORDER BY id DESC)', sql: 'SELECT * FROM estudiantes ORDER BY id DESC;' },
  { label: 'Extendible Hash Scan (carrera)', sql: "SELECT * FROM estudiantes WHERE carrera = 'Ciencia de Datos';" },
  { label: 'Sequential Binary Search (codigo=101)', sql: 'SELECT * FROM cursos WHERE codigo = 101;' },
  { label: 'GROUP BY por carrera', sql: 'SELECT carrera FROM estudiantes GROUP BY carrera;' },
  { label: 'INSERT en Heap + Actualización Índices', sql: "INSERT INTO estudiantes VALUES (12, 'Valeria Gomez', 'Bioingenieria', 19.5);" },
  { label: 'DELETE en Heap + Limpieza de Índices', sql: 'DELETE FROM estudiantes WHERE id = 12;' },
  { label: 'EXPLAIN (plan estimado, sin tocar disco)', sql: "EXPLAIN INSERT INTO estudiantes VALUES (12, 'Valeria Gomez', 'Bioingenieria', 19.5);" },
  { label: 'EXPLAIN ANALYZE (ejecuta de verdad + tiempo real)', sql: 'EXPLAIN ANALYZE SELECT * FROM estudiantes WHERE id > 3;' },
  { label: 'CREATE TABLE (Heap, con PK indexada)', sql: 'CREATE TABLE productos (id INT PRIMARY KEY, nombre VARCHAR(30), precio FLOAT);' },
  { label: 'CREATE TABLE (Sequential, PK agrupada)', sql: 'CREATE TABLE ventas (folio INT PRIMARY KEY, monto FLOAT) USING SEQUENTIAL;' },
  { label: 'DROP TABLE (borra archivos de disco, irreversible)', sql: 'DROP TABLE productos;' },
  { label: 'Transacción: BEGIN', sql: 'BEGIN TRANSACTION;' },
  { label: 'Transacción: COMMIT', sql: 'COMMIT;' },
  { label: 'Transacción: ROLLBACK', sql: 'ROLLBACK;' },
  {
    label: 'Transacción completa (BEGIN → INSERT → ROLLBACK)',
    sql: [
      'BEGIN TRANSACTION;',
      "INSERT INTO estudiantes VALUES (500, 'Prueba Rollback', 'Demo', 10.0);",
      'SELECT * FROM estudiantes WHERE id = 500;',
      'ROLLBACK;',
    ].join('\n'),
  },
];


export default function QueryPanel({
  query,
  setQuery,
  onExecute,
  onExplain,
  onOpenCsvImport,
  loading,
  history = []
}) {
  const [selectedTemplate, setSelectedTemplate] = useState('');
  const [scrollTop, setScrollTop] = useState(0);
  const lineNumbersInnerRef = useRef(null);

  const lineCount = Math.max(1, query.split('\n').length);
  const sentenciasEnEditor = query.split(';').map(s => s.trim()).filter(Boolean);
  const hayExplicable = sentenciasEnEditor.length === 1
    && /^(SELECT|INSERT|DELETE)\b/i.test(sentenciasEnEditor[0]);

  let motivoDeshabilitado = '';
  if (sentenciasEnEditor.length === 0) {
    motivoDeshabilitado = 'Escribe una consulta en el editor primero.';
  } else if (sentenciasEnEditor.length > 1) {
    motivoDeshabilitado = 'El editor tiene varias sentencias: deja una sola SELECT, INSERT o DELETE para poder analizarla.';
  } else if (!hayExplicable) {
    motivoDeshabilitado = 'Solo se puede analizar SELECT, INSERT o DELETE (no CREATE TABLE, DROP TABLE ni BEGIN/COMMIT/ROLLBACK).';
  }

  const handleKeyDown = (e) => {
    // Cmd+Enter or Ctrl+Enter to execute
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      onExecute();
    }
  };

  const handleEditorScroll = (e) => {
    setScrollTop(e.target.scrollTop);
  };

  const handleTemplateChange = (e) => {
    const val = e.target.value;
    setSelectedTemplate(val);
    if (val) {
      setQuery(val);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 text-slate-800 dark:text-slate-100 overflow-hidden">
      {/* Panel Header */}
      <div className="p-2.5 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-pg-600 dark:text-pg-400" />
          <h2 className="font-semibold text-xs tracking-wide uppercase text-slate-600 dark:text-slate-300">
            Panel de Consultas SQL
          </h2>
        </div>

        {/* Quick templates dropdown */}
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-500 dark:text-slate-400 flex items-center gap-1">
            <Sparkles className="w-3.5 h-3.5 text-amber-500 dark:text-amber-400" />
            <span className="hidden sm:inline">Ejemplos:</span>
          </label>
          <select
            value={selectedTemplate}
            onChange={handleTemplateChange}
            className="bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 text-xs text-slate-700 dark:text-slate-200 rounded px-2 py-1 outline-none focus:border-pg-500 max-w-[200px] truncate"
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
            className="p-1.5 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200 rounded transition"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>

          {onOpenCsvImport && (
            <button
              onClick={onOpenCsvImport}
              title="Importar datos desde un archivo CSV (genera CREATE TABLE/INSERT en el editor)"
              className="flex items-center gap-1.5 px-2.5 py-1 bg-emerald-50 hover:bg-emerald-100 dark:bg-emerald-600/20 dark:hover:bg-emerald-600/30 border border-emerald-300 dark:border-emerald-500/40 text-emerald-700 dark:text-emerald-200 hover:text-emerald-900 dark:hover:text-white rounded text-xs font-medium transition"
            >
              <Upload className="w-3.5 h-3.5" />
              <span>Cargar CSV</span>
            </button>
          )}

          <button
            onClick={() => onExplain(false)}
            disabled={loading || !query.trim() || !hayExplicable}
            className="flex items-center gap-1.5 px-2.5 py-1 bg-violet-50 hover:bg-violet-100 dark:bg-violet-600/20 dark:hover:bg-violet-600/30 border border-violet-300 dark:border-violet-500/40 text-violet-700 dark:text-violet-200 hover:text-violet-900 dark:hover:text-white rounded text-xs font-medium transition disabled:opacity-50 disabled:cursor-not-allowed"
            title={
              hayExplicable
                ? "Ver el plan estimado, sin ejecutar cambios en disco (INSERT/DELETE no se aplican)"
                : motivoDeshabilitado
            }
          >
            <GitBranch className="w-3.5 h-3.5" />
            <span>EXPLAIN</span>
          </button>

          <button
            onClick={() => onExplain(true)}
            disabled={loading || !query.trim() || !hayExplicable}
            className="flex items-center gap-1.5 px-2.5 py-1 bg-fuchsia-50 hover:bg-fuchsia-100 dark:bg-fuchsia-600/20 dark:hover:bg-fuchsia-600/30 border border-fuchsia-300 dark:border-fuchsia-500/40 text-fuchsia-700 dark:text-fuchsia-200 hover:text-fuchsia-900 dark:hover:text-white rounded text-xs font-medium transition disabled:opacity-50 disabled:cursor-not-allowed"
            title={
              hayExplicable
                ? "Ejecuta la consulta de verdad y muestra tiempo real + filas reales (EXPLAIN ANALYZE)"
                : motivoDeshabilitado
            }
          >
            <Gauge className="w-3.5 h-3.5" />
            <span>EXPLAIN ANALYZE</span>
          </button>

          <button
            onClick={onExecute}
            disabled={loading || !query.trim()}
            className="flex items-center gap-1.5 px-3 py-1 bg-pg-600 hover:bg-pg-700 dark:bg-pg-500 dark:hover:bg-pg-400 text-white rounded text-xs font-semibold shadow-sm transition disabled:opacity-50"
            title="Ejecutar consulta (Cmd/Ctrl + Enter)"
          >
            <Play className={`w-3.5 h-3.5 fill-current ${loading ? 'animate-spin' : ''}`} />
            <span>Ejecutar</span>
            <kbd className="hidden md:inline-block bg-pg-800/60 dark:bg-pg-800/80 px-1 py-0.2 rounded text-[10px] font-mono text-pg-100">
              ⌘↵
            </kbd>
          </button>
        </div>
      </div>

      {/* Editor Area */}
      <div className="relative flex-1 min-h-[52px] flex overflow-hidden">
        <div className="w-8 py-3 bg-slate-50 dark:bg-slate-950/40 text-slate-400 dark:text-slate-600 select-none text-right pr-2 font-mono text-xs sm:text-sm border-r border-slate-200 dark:border-slate-800/40 overflow-hidden">
          <div
            ref={lineNumbersInnerRef}
            style={{ transform: `translateY(-${scrollTop}px)` }}
          >
            {Array.from({ length: lineCount }, (_, i) => (
              <div key={i} className="leading-relaxed">{i + 1}</div>
            ))}
          </div>
        </div>

        {/* Textarea */}
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          onScroll={handleEditorScroll}
          placeholder="-- Escribe tu consulta SQL aquí...&#10;SELECT * FROM estudiantes;&#10;-- Atajo: Presiona ⌘ + Enter o Ctrl + Enter para ejecutar"
          className="flex-1 w-full p-3 bg-white dark:bg-slate-950/20 text-slate-800 dark:text-slate-100 font-mono text-xs sm:text-sm outline-none resize-none placeholder-slate-400 dark:placeholder-slate-600 leading-relaxed"
          spellCheck="false"
        />
      </div>

      {/* Query History Bar */}
      {history.length > 0 && (
        <div className="px-3 py-1.5 bg-slate-50 dark:bg-slate-950/40 border-t border-slate-200 dark:border-slate-800/60 flex items-center gap-2 overflow-x-auto text-[11px] text-slate-500 dark:text-slate-400">
          <Clock className="w-3 h-3 text-slate-400 dark:text-slate-500 shrink-0" />
          <span className="shrink-0 text-slate-400 dark:text-slate-500">Historial:</span>
          <div className="flex items-center gap-1.5">
            {history.slice(-4).reverse().map((h, i) => (
              <button
                key={i}
                onClick={() => setQuery(h)}
                className="bg-slate-200/70 hover:bg-slate-200 dark:bg-slate-800/80 dark:hover:bg-slate-800 text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white px-2 py-0.5 rounded font-mono truncate max-w-[180px] border border-slate-300/60 dark:border-slate-700/50 transition"
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
