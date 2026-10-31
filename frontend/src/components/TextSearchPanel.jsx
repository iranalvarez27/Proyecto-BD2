import React, { useState, useEffect } from 'react';
import {
  Search,
  BookOpen,
  TrendingUp,
  BarChart3,
  Copy,
  Check,
  Terminal,
  Activity,
  AlertCircle,
  Inbox,
  Sparkles
} from 'lucide-react';

import { buildMatchSQL } from '../utils/sqlBuilders';
import { HighlightedText } from '../utils/highlight';
import { extractSnippet } from '../utils/textUtils';
import { executeTextSearch } from '../utils/api';

const EJEMPLOS_SUGERIDOS = [
  'auriculares bluetooth con cancelación de ruido',
  'laptop gamer memoria ram',
  'base de datos relacional índices',
  'batería recargable carga rápida'
];

export default function TextSearchPanel({
  tables = [],
  onRunSQL,
  sessionId
}) {
  // Tablas que tengan columnas de texto
  const tablasConTexto = tables.filter(t =>
    t.columns?.some(c => c.type === 'VARCHAR' || c.type === 'CHAR' || c.type === 'TEXT')
  );

  const [selectedTable, setSelectedTable] = useState(
    () => tablasConTexto[0]?.name || tables[0]?.name || 'documentos'
  );

  const tablaInfo = tables.find(t => t.name === selectedTable);
  const columnasTexto = tablaInfo?.columns?.filter(c =>
    c.type === 'VARCHAR' || c.type === 'CHAR' || c.type === 'TEXT'
  ) || [{ name: 'contenido' }];

  const [selectedColumn, setSelectedColumn] = useState(
    () => columnasTexto[0]?.name || 'contenido'
  );

  const [queryText, setQueryText] = useState('');
  const [method, setMethod] = useState('BM25'); // 'BM25' | 'TF_IDF' | 'AMBOS'
  const [topK, setTopK] = useState(10);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  // Estados de resultados (inicialmente vacíos, esperando datos reales)
  const [resultData, setResultData] = useState(null);
  const [resultDual, setResultDual] = useState({ bm25: null, tfidf: null });

  useEffect(() => {
    if (columnasTexto.length > 0 && !columnasTexto.some(c => c.name === selectedColumn)) {
      setSelectedColumn(columnasTexto[0].name);
    }
  }, [selectedTable]);

  const generatedSQL = buildMatchSQL({
    table: selectedTable,
    column: selectedColumn,
    query: queryText || 'termino_consulta',
    method: method === 'AMBOS' ? 'BM25' : method,
    limit: topK
  });

  const handleSearch = async () => {
    if (!queryText.trim()) return;
    setLoading(true);

    try {
      if (method === 'AMBOS') {
        const [resBM25, resTFIDF] = await Promise.all([
          executeTextSearch({
            table: selectedTable,
            column: selectedColumn,
            query: queryText,
            method: 'BM25',
            k: topK,
            sessionId
          }),
          executeTextSearch({
            table: selectedTable,
            column: selectedColumn,
            query: queryText,
            method: 'TF_IDF',
            k: topK,
            sessionId
          })
        ]);
        setResultDual({ bm25: resBM25, tfidf: resTFIDF });
        setResultData(resBM25);
      } else {
        const res = await executeTextSearch({
          table: selectedTable,
          column: selectedColumn,
          query: queryText,
          method,
          k: topK,
          sessionId
        });
        setResultData(res);
      }
    } catch (err) {
      console.error('Error en búsqueda de texto:', err);
      setResultData({
        error: err.message || 'Error al conectar con el motor.',
        resultados: []
      });
    } finally {
      setLoading(false);
    }
  };

  const handleCopySQL = () => {
    navigator.clipboard.writeText(generatedSQL);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleSendToEditor = () => {
    if (onRunSQL) {
      onRunSQL(generatedSQL);
    }
  };

  // Términos para resaltado
  const queryTerms = resultData?.terminos?.map(t => t.termino) || queryText.split(/\s+/).filter(Boolean);

  // Solapamiento Jaccard en modo dual
  const idsBM25 = new Set(resultDual.bm25?.resultados?.map(r => r.id) || []);
  const idsTFIDF = new Set(resultDual.tfidf?.resultados?.map(r => r.id) || []);
  const interseccion = [...idsBM25].filter(x => idsTFIDF.has(x));
  const union = new Set([...idsBM25, ...idsTFIDF]);
  const jaccardSimilarity = union.size > 0 ? (interseccion.length / union.size) : 0;

  // Normalización de score
  const maxScore = Math.max(...(resultData?.resultados?.map(r => r.score) || [1]), 0.001);

  return (
    <div className="flex flex-col h-full bg-slate-50 dark:bg-slate-950 text-slate-800 dark:text-slate-100 overflow-hidden">
      {/* 1. Barra Superior con Formulario */}
      <div className="p-3 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 shadow-xs shrink-0 space-y-2">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-indigo-50 dark:bg-indigo-950/80 text-indigo-600 dark:text-indigo-400 border border-indigo-200 dark:border-indigo-800/60">
              <Search className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-200">
                Búsqueda Textual (Full-Text Search)
              </h2>
              <p className="text-[10px] text-slate-400">
                Índice Invertido en Disco (SPIMI) con Ranking BM25 y TF-IDF Coseno
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 text-xs">
            <button
              onClick={handleCopySQL}
              className="flex items-center gap-1 px-2.5 py-1 rounded bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 text-slate-600 dark:text-slate-300 transition-colors"
              title="Copiar consulta SQL"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
              <span>{copied ? 'Copiado' : 'Copiar SQL'}</span>
            </button>
            <button
              onClick={handleSendToEditor}
              className="flex items-center gap-1 px-2.5 py-1 rounded bg-indigo-50 dark:bg-indigo-950/80 border border-indigo-200 dark:border-indigo-800/60 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-100 transition-colors"
              title="Enviar al editor SQL principal"
            >
              <Terminal className="w-3.5 h-3.5" />
              <span>Abrir en Editor</span>
            </button>
          </div>
        </div>

        {/* Formulario */}
        <div className="grid grid-cols-1 md:grid-cols-12 gap-2 items-center">
          {/* Selector Tabla */}
          <div className="md:col-span-2">
            <label className="text-[10px] font-medium text-slate-400 block mb-0.5">Tabla</label>
            <select
              value={selectedTable}
              onChange={e => setSelectedTable(e.target.value)}
              className="w-full text-xs bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded px-2 py-1.5 focus:outline-hidden focus:ring-1 focus:ring-indigo-500"
            >
              {tables.map(t => (
                <option key={t.name} value={t.name}>
                  {t.name} {t.indexes?.some(i => i.type === 'INVERTED') ? '⚡' : ''}
                </option>
              ))}
            </select>
          </div>

          {/* Selector Columna */}
          <div className="md:col-span-2">
            <label className="text-[10px] font-medium text-slate-400 block mb-0.5">Columna Texto</label>
            <select
              value={selectedColumn}
              onChange={e => setSelectedColumn(e.target.value)}
              className="w-full text-xs bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded px-2 py-1.5 focus:outline-hidden focus:ring-1 focus:ring-indigo-500"
            >
              {columnasTexto.map(c => (
                <option key={c.name} value={c.name}>{c.name}</option>
              ))}
            </select>
          </div>

          {/* Input de Búsqueda */}
          <div className="md:col-span-5">
            <label className="text-[10px] font-medium text-slate-400 block mb-0.5">Consulta de Búsqueda</label>
            <div className="relative">
              <input
                type="text"
                value={queryText}
                onChange={e => setQueryText(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSearch()}
                placeholder="Escribe términos a buscar en el índice..."
                className="w-full text-xs bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded pl-7 pr-3 py-1.5 focus:outline-hidden focus:ring-1 focus:ring-indigo-500 font-mono"
              />
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2 top-2.5" />
            </div>
          </div>

          {/* Selector Modelo */}
          <div className="md:col-span-2">
            <label className="text-[10px] font-medium text-slate-400 block mb-0.5">Ranking IR</label>
            <div className="flex rounded border border-slate-300 dark:border-slate-700 overflow-hidden text-xs">
              <button
                type="button"
                onClick={() => setMethod('BM25')}
                className={`flex-1 py-1 px-1.5 text-center font-semibold transition-colors ${
                  method === 'BM25'
                    ? 'bg-indigo-600 text-white'
                    : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200'
                }`}
              >
                BM25
              </button>
              <button
                type="button"
                onClick={() => setMethod('TF_IDF')}
                className={`flex-1 py-1 px-1.5 text-center font-semibold transition-colors ${
                  method === 'TF_IDF'
                    ? 'bg-indigo-600 text-white'
                    : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200'
                }`}
              >
                TF-IDF
              </button>
              <button
                type="button"
                onClick={() => setMethod('AMBOS')}
                className={`flex-1 py-1 px-1 text-center text-[10px] font-medium transition-colors ${
                  method === 'AMBOS'
                    ? 'bg-indigo-600 text-white'
                    : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200'
                }`}
                title="Comparar BM25 vs TF-IDF lado a lado"
              >
                Dual
              </button>
            </div>
          </div>

          {/* Botón Buscar */}
          <div className="md:col-span-1">
            <label className="text-[10px] font-medium text-slate-400 block mb-0.5">Top-K</label>
            <div className="flex gap-1">
              <select
                value={topK}
                onChange={e => setTopK(Number(e.target.value))}
                className="w-14 text-xs bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded px-1 py-1.5"
              >
                <option value={5}>5</option>
                <option value={10}>10</option>
                <option value={20}>20</option>
                <option value={50}>50</option>
              </select>
              <button
                onClick={handleSearch}
                disabled={loading || !queryText.trim()}
                className="flex-1 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-2 py-1.5 rounded text-xs font-semibold flex items-center justify-center transition-colors shadow-xs"
              >
                {loading ? <Activity className="w-3.5 h-3.5 animate-spin" /> : 'Ir'}
              </button>
            </div>
          </div>
        </div>

        {/* Sugerencias de ejemplo */}
        <div className="flex items-center justify-between text-[11px] gap-2 pt-1 border-t border-slate-100 dark:border-slate-800/60">
          <div className="flex items-center gap-1.5 overflow-x-auto py-0.5">
            <span className="text-slate-400 shrink-0 flex items-center gap-1">
              <Sparkles className="w-3 h-3 text-amber-500" /> Ejemplos:
            </span>
            {EJEMPLOS_SUGERIDOS.map((ex, i) => (
              <button
                key={i}
                onClick={() => { setQueryText(ex); }}
                className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 hover:bg-indigo-50 dark:hover:bg-indigo-950/60 text-slate-600 dark:text-slate-300 hover:text-indigo-600 dark:hover:text-indigo-300 whitespace-nowrap text-[10px] transition-colors"
              >
                {ex}
              </button>
            ))}
          </div>

          <div className="hidden xl:flex items-center gap-2 font-mono text-[10px] text-slate-500 bg-slate-100 dark:bg-slate-800/80 px-2 py-0.5 rounded truncate max-w-md">
            <span className="text-indigo-500 font-bold">SQL:</span>
            <span className="truncate">{generatedSQL}</span>
          </div>
        </div>
      </div>

      {/* 2. Cuerpo Principal */}
      <div className="flex-1 flex overflow-hidden">
        {/* Columna Izquierda: Pipeline Lingüístico */}
        <aside className="w-72 shrink-0 border-r border-slate-200 dark:border-slate-800 bg-white/50 dark:bg-slate-900/40 p-3 overflow-y-auto space-y-4">
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300 flex items-center gap-1.5 mb-2">
              <BookOpen className="w-3.5 h-3.5 text-indigo-500" />
              Pipeline Lingüístico
            </h3>

            {resultData?.preprocesamiento ? (
              <div className="space-y-1.5 text-[11px]">
                <div className="p-2 rounded bg-slate-100 dark:bg-slate-800/70">
                  <span className="text-[10px] uppercase font-bold text-slate-400 block">1. Normalizado (NFC / sin tildes)</span>
                  <span className="font-mono text-slate-700 dark:text-slate-300">
                    {resultData.preprocesamiento.normalizado || '—'}
                  </span>
                </div>

                <div className="p-2 rounded bg-slate-100 dark:bg-slate-800/70">
                  <span className="text-[10px] uppercase font-bold text-slate-400 block">2. Tokens filtrados (sin stopwords)</span>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {resultData.preprocesamiento.sin_stopwords?.map((tok, i) => (
                      <span key={i} className="px-1.5 py-0.5 rounded bg-slate-200 dark:bg-slate-700 font-mono text-[10px]">
                        {tok}
                      </span>
                    )) || '—'}
                  </div>
                </div>

                <div className="p-2 rounded bg-indigo-50 dark:bg-indigo-950/60 border border-indigo-200 dark:border-indigo-800/50">
                  <span className="text-[10px] uppercase font-bold text-indigo-500 dark:text-indigo-400 block">3. Raíces / Stems (Snowball)</span>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {resultData.preprocesamiento.terminos?.map((stem, i) => (
                      <span key={i} className="px-1.5 py-0.5 rounded bg-indigo-100 dark:bg-indigo-900/80 text-indigo-700 dark:text-indigo-300 font-mono text-[10px] font-semibold">
                        {stem}*
                      </span>
                    )) || '—'}
                  </div>
                </div>
              </div>
            ) : (
              <div className="p-3 rounded-lg border border-dashed border-slate-200 dark:border-slate-800 text-center text-slate-400 text-xs py-6">
                Escribe una consulta y presiona <b>Ir</b> para visualizar la tokenización, filtrado de stopwords y stemming.
              </div>
            )}
          </div>

          {/* Diccionario de Términos */}
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300 flex items-center gap-1.5 mb-2">
              <TrendingUp className="w-3.5 h-3.5 text-indigo-500" />
              Términos Evaluados
            </h3>

            {resultData?.terminos && resultData.terminos.length > 0 ? (
              <div className="border border-slate-200 dark:border-slate-800 rounded overflow-hidden">
                <table className="w-full text-[11px] text-left">
                  <thead className="bg-slate-100 dark:bg-slate-800 text-slate-500 text-[10px]">
                    <tr>
                      <th className="p-1.5">Término</th>
                      <th className="p-1.5 text-right">DF</th>
                      <th className="p-1.5 text-right">IDF</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200 dark:divide-slate-800 font-mono">
                    {resultData.terminos.map((t, idx) => (
                      <tr key={idx} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                        <td className="p-1.5 font-semibold text-indigo-600 dark:text-indigo-400">
                          {t.termino}
                        </td>
                        <td className="p-1.5 text-right text-slate-600 dark:text-slate-300">
                          {t.df?.toLocaleString() ?? 0}
                        </td>
                        <td className="p-1.5 text-right text-emerald-600 dark:text-emerald-400 font-bold">
                          {t.idf ? t.idf.toFixed(2) : '0.00'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-[11px] text-slate-400 italic">Sin términos cargados.</p>
            )}
          </div>

          {/* Estadísticas Físicas SPIMI */}
          <div className="p-2.5 rounded-lg bg-slate-100 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 space-y-1.5 text-[11px]">
            <div className="flex items-center justify-between text-slate-500 font-semibold text-[10px] uppercase">
              <span>Métricas SPIMI</span>
              <span className="text-indigo-500">Disco 4 KB</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Docs indexados:</span>
              <strong className="font-mono">{resultData?.indice?.documentos?.toLocaleString() || '—'}</strong>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Postings en disco:</span>
              <strong className="font-mono">{resultData?.indice?.postings?.toLocaleString() || '—'}</strong>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Longitud media (avgdl):</span>
              <strong className="font-mono">{resultData?.indice?.avgdl ? `${resultData.indice.avgdl.toFixed(1)} pal` : '—'}</strong>
            </div>
            <div className="flex justify-between border-t border-slate-200 dark:border-slate-700 pt-1 text-emerald-600 dark:text-emerald-400 font-bold">
              <span>Tiempo de consulta:</span>
              <span className="font-mono">{resultData?.metricas?.tiempo_ms !== undefined ? `${resultData.metricas.tiempo_ms} ms` : '—'}</span>
            </div>
          </div>
        </aside>

        {/* Columna Central: Resultados */}
        <main className="flex-1 p-4 overflow-y-auto space-y-3">
          {/* Mensaje de Error del Motor */}
          {resultData?.error ? (
            <div className="p-4 bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-800/60 rounded-lg text-rose-800 dark:text-rose-200 text-xs space-y-2">
              <div className="flex items-center gap-2 font-semibold text-rose-700 dark:text-rose-300">
                <AlertCircle className="w-4 h-4 text-rose-500" />
                <span>Respuesta del motor de base de datos:</span>
              </div>
              <p className="font-mono bg-rose-100/70 dark:bg-rose-950/60 p-2.5 rounded border border-rose-200 dark:border-rose-900/80 whitespace-pre-wrap">
                {resultData.error}
              </p>
            </div>
          ) : !resultData ? (
            /* Estado Inicial Vacío Elegante */
            <div className="flex flex-col items-center justify-center h-full text-slate-400 dark:text-slate-500 gap-3 py-16">
              <div className="p-4 rounded-full bg-indigo-50 dark:bg-indigo-950/60 border border-indigo-200 dark:border-indigo-800/60 text-indigo-500">
                <Inbox className="w-8 h-8 stroke-1" />
              </div>
              <div className="text-center max-w-md space-y-1">
                <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
                  Panel de Búsqueda Textual Listo
                </h3>
                <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                  Ingresa palabras clave en la barra superior o haz click en un ejemplo para rankear documentos con el índice invertido (SPIMI).
                </p>
              </div>
            </div>
          ) : resultData.resultados?.length === 0 ? (
            /* Sin Coincidencias */
            <div className="p-8 text-center text-slate-500 dark:text-slate-400 text-xs bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 space-y-1">
              <Inbox className="w-6 h-6 mx-auto text-slate-400" />
              <p className="font-medium">No se encontraron documentos coincidentes</p>
              <p className="text-[11px] text-slate-400">Verifica los términos de búsqueda o prueba con otro modelo de ranking.</p>
            </div>
          ) : (
            /* Renderizado de Resultados */
            <>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-slate-700 dark:text-slate-200">
                    Top {resultData.resultados.length} Resultados más relevantes
                  </span>
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-indigo-100 dark:bg-indigo-900/60 text-indigo-700 dark:text-indigo-300 font-mono font-semibold">
                    {method === 'AMBOS' ? 'Comparación BM25 vs TF-IDF' : method}
                  </span>
                </div>

                {method === 'AMBOS' && (
                  <div className="flex items-center gap-2 text-xs bg-amber-50 dark:bg-amber-950/60 border border-amber-200 dark:border-amber-800 px-2 py-1 rounded">
                    <BarChart3 className="w-3.5 h-3.5 text-amber-600" />
                    <span className="text-amber-800 dark:text-amber-200 text-[11px]">
                      Solapamiento Jaccard @{topK}: <strong>{(jaccardSimilarity * 100).toFixed(0)}%</strong> ({interseccion.length}/{union.size} comunes)
                    </span>
                  </div>
                )}
              </div>

              {/* Modo Normal */}
              <div className="space-y-2.5">
                {resultData.resultados.map((item, idx) => {
                  const scorePorcentaje = Math.min(100, Math.round((item.score / maxScore) * 100));

                  return (
                    <div
                      key={item.id || idx}
                      className="p-3.5 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-indigo-300 dark:hover:border-indigo-700 transition-all shadow-xs space-y-2"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-center gap-2.5 min-w-0">
                          <span className="w-6 h-6 rounded-full bg-indigo-100 dark:bg-indigo-900/80 text-indigo-700 dark:text-indigo-300 font-bold text-xs flex items-center justify-center shrink-0">
                            #{idx + 1}
                          </span>
                          <div>
                            <h4 className="text-xs font-bold text-slate-800 dark:text-slate-100 truncate">
                              {item.titulo || `Registro #${item.id}`}
                            </h4>
                            <div className="flex items-center gap-2 text-[10px] text-slate-400 font-mono">
                              {item.id && <span>ID: {item.id}</span>}
                              {item.rid && <span>RID: ({item.rid.page_id}, {item.rid.slot_id})</span>}
                            </div>
                          </div>
                        </div>

                        <div className="text-right shrink-0">
                          <div className="flex items-center gap-1.5 justify-end">
                            <span className="text-[10px] text-slate-400 font-mono">SCORE:</span>
                            <span className="font-mono text-xs font-bold text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/80 px-2 py-0.5 rounded border border-indigo-200 dark:border-indigo-800/60">
                              {typeof item.score === 'number' ? item.score.toFixed(3) : item.score}
                            </span>
                          </div>
                          <div className="w-24 h-1.5 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden mt-1 ml-auto">
                            <div
                              className="h-full bg-indigo-500 rounded-full"
                              style={{ width: `${scorePorcentaje}%` }}
                            />
                          </div>
                        </div>
                      </div>

                      <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed bg-slate-50 dark:bg-slate-800/40 p-2 rounded border border-slate-100 dark:border-slate-800">
                        <HighlightedText
                          text={extractSnippet(item.contenido || '', queryTerms, 220)}
                          terms={queryTerms}
                        />
                      </p>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
