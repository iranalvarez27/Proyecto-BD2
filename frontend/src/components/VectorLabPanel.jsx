import React, { useState } from 'react';
import {
  Sparkles,
  Image as ImageIcon,
  Headphones,
  Upload,
  Copy,
  Check,
  Terminal,
  Activity,
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  Volume2,
  Cpu,
  BarChart2,
  Compass,
  Inbox
} from 'lucide-react';

import { buildSimilarSQL } from '../utils/sqlBuilders';
import { executeVectorSearch, uploadMediaApi } from '../utils/api';

export default function VectorLabPanel({
  tables = [],
  onRunSQL,
  sessionId
}) {
  // Modalidad: 'imagen' | 'audio'
  const [modalidad, setModalidad] = useState('imagen');

  // Seleccionar tabla según disponibilidad en el catálogo
  const [selectedTable, setSelectedTable] = useState(() => {
    const defaultName = modalidad === 'imagen' ? 'imagenes' : 'canciones';
    return tables.find(t => t.name.toLowerCase().includes(defaultName))?.name || tables[0]?.name || defaultName;
  });

  const [targetFile, setTargetFile] = useState('');
  const [targetPreviewUrl, setTargetPreviewUrl] = useState(null);
  const [indexType, setIndexType] = useState('HNSW'); // 'HNSW' | 'IVF' | 'SEQ'
  const [metric, setMetric] = useState('cosine'); // 'cosine' | 'euclidean' | 'dot_product'
  const [topK, setTopK] = useState(6);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  // Hiperparámetros avanzados
  const [efSearch, setEfSearch] = useState(64);
  const [nprobe, setNprobe] = useState(8);

  // Resultados (inicialmente null, esperando consulta real)
  const [vectorData, setVectorData] = useState(null);

  const handleCambiarModalidad = (nuevaModalidad) => {
    setModalidad(nuevaModalidad);
    setTargetFile('');
    setTargetPreviewUrl(null);
    setVectorData(null);
    if (nuevaModalidad === 'imagen') {
      setMetric('cosine');
    } else {
      setMetric('euclidean');
    }
  };

  const generatedSQL = buildSimilarSQL({
    table: selectedTable,
    targetFile: targetFile || (modalidad === 'imagen' ? 'foto_consulta.jpg' : 'audio_consulta.mp3'),
    k: topK,
    index: indexType,
    metric,
    includeScore: true,
    scoreAlias: 'score'
  });

  const handleSearch = async () => {
    if (!targetFile) return;
    setLoading(true);
    try {
      const res = await executeVectorSearch({
        modalidad,
        table: selectedTable,
        targetFile,
        metric,
        index: indexType,
        k: topK,
        sessionId
      });
      setVectorData(res);
    } catch (err) {
      console.error('Error en búsqueda vectorial:', err);
      setVectorData({
        error: err.message || 'Error al conectar con el motor.',
        resultados: []
      });
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setLoading(true);
    try {
      const uploaded = await uploadMediaApi(file);
      setTargetFile(uploaded.filename);
      setTargetPreviewUrl(uploaded.url || URL.createObjectURL(file));
      setVectorData(null);
    } catch (err) {
      console.error('Error subiendo archivo multimedia:', err);
      alert(`Error al subir archivo: ${err.message}`);
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

  return (
    <div className="flex flex-col h-full bg-slate-50 dark:bg-slate-950 text-slate-800 dark:text-slate-100 overflow-hidden">
      {/* 1. Header con Formulario de Consulta Vectorial */}
      <div className="p-3 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 shadow-xs shrink-0 space-y-2">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-pink-50 dark:bg-pink-950/80 text-pink-600 dark:text-pink-400 border border-pink-200 dark:border-pink-800/60">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-200">
                Laboratorio Vectorial Multimedia (Imágenes & Audio)
              </h2>
              <p className="text-[10px] text-slate-400">
                Índices de Alta Dimensión HNSW y IVF con Descriptores SIFT y MFCC
              </p>
            </div>
          </div>

          {/* Toggle Modalidad: Imágenes vs Audio */}
          <div className="flex items-center gap-2">
            <div className="flex rounded-lg bg-slate-100 dark:bg-slate-800 p-0.5 border border-slate-200 dark:border-slate-700 text-xs font-semibold">
              <button
                type="button"
                onClick={() => handleCambiarModalidad('imagen')}
                className={`flex items-center gap-1.5 px-3 py-1 rounded-md transition-all ${
                  modalidad === 'imagen'
                    ? 'bg-white dark:bg-slate-700 text-pink-600 dark:text-pink-300 shadow-xs font-bold'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
                }`}
              >
                <ImageIcon className="w-3.5 h-3.5" />
                <span>Imágenes (SIFT)</span>
              </button>

              <button
                type="button"
                onClick={() => handleCambiarModalidad('audio')}
                className={`flex items-center gap-1.5 px-3 py-1 rounded-md transition-all ${
                  modalidad === 'audio'
                    ? 'bg-white dark:bg-slate-700 text-pink-600 dark:text-pink-300 shadow-xs font-bold'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
                }`}
              >
                <Headphones className="w-3.5 h-3.5" />
                <span>Audio (MFCC)</span>
              </button>
            </div>

            <button
              onClick={handleCopySQL}
              className="flex items-center gap-1 px-2.5 py-1 rounded bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 text-slate-600 dark:text-slate-300 text-xs transition-colors"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
              <span>{copied ? 'Copiado' : 'Copiar SQL'}</span>
            </button>

            <button
              onClick={handleSendToEditor}
              className="flex items-center gap-1 px-2.5 py-1 rounded bg-pink-50 dark:bg-pink-950/80 border border-pink-200 dark:border-pink-800/60 text-pink-600 dark:text-pink-400 hover:bg-pink-100 text-xs transition-colors"
            >
              <Terminal className="w-3.5 h-3.5" />
              <span>Abrir en Editor</span>
            </button>
          </div>
        </div>

        {/* Controles de Parámetros */}
        <div className="grid grid-cols-1 md:grid-cols-12 gap-2 items-center text-xs">
          {/* Selector de Tabla */}
          <div className="md:col-span-3">
            <label className="text-[10px] font-medium text-slate-400 block mb-0.5">Tabla</label>
            <select
              value={selectedTable}
              onChange={e => setSelectedTable(e.target.value)}
              className="w-full text-xs bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded px-2 py-1.5 focus:outline-hidden"
            >
              {tables.map(t => (
                <option key={t.name} value={t.name}>{t.name}</option>
              ))}
            </select>
          </div>

          {/* Selector de Índice */}
          <div className="md:col-span-3">
            <label className="text-[10px] font-medium text-slate-400 block mb-0.5">Estructura de Índice</label>
            <div className="flex rounded border border-slate-300 dark:border-slate-700 overflow-hidden">
              <button
                type="button"
                onClick={() => setIndexType('HNSW')}
                className={`flex-1 py-1 px-2 text-center font-bold text-xs transition-colors ${
                  indexType === 'HNSW'
                    ? 'bg-pink-600 text-white'
                    : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300'
                }`}
                title="Hierarchical Navigable Small World (Grafo navegable)"
              >
                HNSW
              </button>
              <button
                type="button"
                onClick={() => setIndexType('IVF')}
                className={`flex-1 py-1 px-2 text-center font-bold text-xs transition-colors ${
                  indexType === 'IVF'
                    ? 'bg-pink-600 text-white'
                    : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300'
                }`}
                title="Inverted File Index (Particionado Voronoi)"
              >
                IVF
              </button>
              <button
                type="button"
                onClick={() => setIndexType('SEQ')}
                className={`flex-1 py-1 px-1.5 text-center text-[10px] font-medium transition-colors ${
                  indexType === 'SEQ'
                    ? 'bg-slate-700 text-white'
                    : 'bg-slate-100 dark:bg-slate-800 text-slate-500'
                }`}
                title="Fuerza Bruta / Búsqueda Secuencial Exacta"
              >
                Secuencial
              </button>
            </div>
          </div>

          {/* Métrica de Similitud */}
          <div className="md:col-span-3">
            <label className="text-[10px] font-medium text-slate-400 block mb-0.5">Métrica de Distancia</label>
            <select
              value={metric}
              onChange={e => setMetric(e.target.value)}
              className="w-full text-xs bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded px-2 py-1.5 focus:outline-hidden"
            >
              <option value="cosine">Similitud del Coseno (Orientación)</option>
              <option value="euclidean">Distancia Euclidiana L2 (Magnitud)</option>
              <option value="dot_product">Producto Punto (Inner Product)</option>
            </select>
          </div>

          {/* Top-K y Parámetros */}
          <div className="md:col-span-3">
            <label className="text-[10px] font-medium text-slate-400 block mb-0.5">
              {indexType === 'HNSW' ? 'Vecinos (k) & ef_search' : indexType === 'IVF' ? 'Vecinos (k) & nprobe' : 'Vecinos (k)'}
            </label>
            <div className="flex gap-2">
              <select
                value={topK}
                onChange={e => setTopK(Number(e.target.value))}
                className="w-20 text-xs bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded px-1 py-1.5"
              >
                <option value={4}>k = 4</option>
                <option value={6}>k = 6</option>
                <option value={10}>k = 10</option>
                <option value={20}>k = 20</option>
              </select>

              {indexType === 'HNSW' && (
                <div className="flex items-center gap-1 bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded px-2 py-1">
                  <span className="text-[10px] text-slate-400">ef:</span>
                  <input
                    type="number"
                    min={16}
                    max={256}
                    value={efSearch}
                    onChange={e => setEfSearch(Number(e.target.value))}
                    className="w-12 text-xs font-mono bg-transparent text-right"
                  />
                </div>
              )}

              {indexType === 'IVF' && (
                <div className="flex items-center gap-1 bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded px-2 py-1">
                  <span className="text-[10px] text-slate-400">probe:</span>
                  <input
                    type="number"
                    min={1}
                    max={32}
                    value={nprobe}
                    onChange={e => setNprobe(Number(e.target.value))}
                    className="w-12 text-xs font-mono bg-transparent text-right"
                  />
                </div>
              )}

              <button
                onClick={handleSearch}
                disabled={loading || !targetFile}
                className="flex-1 bg-pink-600 hover:bg-pink-700 disabled:opacity-50 text-white px-2 py-1.5 rounded text-xs font-bold flex items-center justify-center gap-1 transition-colors shadow-xs"
              >
                {loading ? <Activity className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
                <span>Buscar</span>
              </button>
            </div>
          </div>
        </div>

        {/* Visualización de SQL generado */}
        <div className="flex items-center justify-between text-[11px] pt-1 border-t border-slate-100 dark:border-slate-800/60 font-mono">
          <div className="flex items-center gap-2 text-slate-500 truncate">
            <span className="text-pink-600 dark:text-pink-400 font-bold">SQL SIMILAR_TO:</span>
            <span className="truncate">{generatedSQL}</span>
          </div>

          <div className="flex items-center gap-2 text-[10px] text-slate-400">
            <span>Latencia: <strong className="text-emerald-500 font-mono">{vectorData?.metricas?.tiempo_busqueda_ms !== undefined ? `${vectorData.metricas.tiempo_busqueda_ms} ms` : '—'}</strong></span>
          </div>
        </div>
      </div>

      {/* 2. Cuerpo Principal */}
      <div className="flex-1 flex overflow-hidden">
        {/* Columna Izquierda: Consulta Multimedia & Extracción */}
        <aside className="w-80 shrink-0 border-r border-slate-200 dark:border-slate-800 bg-white/50 dark:bg-slate-900/40 p-3 overflow-y-auto space-y-4">
          {/* Card de Objeto Consulta */}
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300 flex items-center gap-1.5 mb-2">
              <Compass className="w-3.5 h-3.5 text-pink-500" />
              Archivo de Consulta
            </h3>

            <div className="p-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 space-y-2.5">
              {targetPreviewUrl ? (
                modalidad === 'imagen' ? (
                  <div className="relative group rounded-lg overflow-hidden border border-slate-200 dark:border-slate-700 aspect-video bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
                    <img
                      src={targetPreviewUrl}
                      alt="Query Preview"
                      className="w-full h-full object-cover"
                    />
                    <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity">
                      <label className="cursor-pointer bg-white/90 text-slate-800 px-2.5 py-1 rounded text-xs font-semibold flex items-center gap-1.5 shadow-sm">
                        <Upload className="w-3.5 h-3.5" />
                        <span>Cambiar foto</span>
                        <input type="file" accept="image/*" onChange={handleFileUpload} className="hidden" />
                      </label>
                    </div>
                  </div>
                ) : (
                  <div className="p-3 rounded-lg bg-pink-50 dark:bg-pink-950/40 border border-pink-200 dark:border-pink-800/60 space-y-2">
                    <div className="flex items-center gap-2">
                      <div className="p-2 rounded-full bg-pink-600 text-white">
                        <Volume2 className="w-4 h-4" />
                      </div>
                      <div className="min-w-0">
                        <span className="text-xs font-bold text-slate-800 dark:text-slate-100 truncate block">
                          {targetFile}
                        </span>
                        <span className="text-[10px] text-pink-600 dark:text-pink-400 font-mono">
                          Pista de Audio cargada
                        </span>
                      </div>
                    </div>

                    <audio controls className="w-full h-8 mt-1">
                      <source src={targetPreviewUrl} type="audio/mpeg" />
                    </audio>

                    <label className="cursor-pointer w-full py-1 rounded border border-pink-300 dark:border-pink-700 bg-white dark:bg-slate-900 text-pink-700 dark:text-pink-300 text-[11px] font-semibold flex items-center justify-center gap-1 hover:bg-pink-100 transition-colors">
                      <Upload className="w-3 h-3" />
                      <span>Cambiar archivo de audio</span>
                      <input type="file" accept="audio/*" onChange={handleFileUpload} className="hidden" />
                    </label>
                  </div>
                )
              ) : (
                /* Dropzone de Carga Inicial Limpio */
                <label className="cursor-pointer block border-2 border-dashed border-slate-300 dark:border-slate-700 rounded-lg p-6 text-center hover:border-pink-500 dark:hover:border-pink-500 transition-colors bg-slate-50 dark:bg-slate-800/40">
                  <Upload className="w-8 h-8 mx-auto text-slate-400 mb-2" />
                  <span className="text-xs font-semibold text-slate-700 dark:text-slate-200 block">
                    Haz clic o arrastra un archivo aquí
                  </span>
                  <span className="text-[10px] text-slate-400 mt-1 block">
                    {modalidad === 'imagen' ? 'Soporta JPG, PNG, WEBP' : 'Soporta MP3, WAV, OGG'}
                  </span>
                  <input
                    type="file"
                    accept={modalidad === 'imagen' ? 'image/*' : 'audio/*'}
                    onChange={handleFileUpload}
                    className="hidden"
                  />
                </label>
              )}
            </div>
          </div>

          {/* Pipeline de Feature Extraction */}
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300 flex items-center gap-1.5 mb-2">
              <Cpu className="w-3.5 h-3.5 text-pink-500" />
              Extracción de Características
            </h3>

            <div className="p-3 rounded-lg bg-slate-100 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 space-y-2 text-[11px]">
              <div className="flex justify-between">
                <span className="text-slate-400">Algoritmo extractor:</span>
                <strong className="font-mono text-slate-800 dark:text-slate-200">
                  {modalidad === 'imagen' ? 'SIFT (Scale-Invariant)' : 'MFCC (Mel-Cepstral)'}
                </strong>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Cuantización BoW:</span>
                <strong className="font-mono">K-Means</strong>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Dimensión de vector:</span>
                <strong className="font-mono text-pink-600 dark:text-pink-400">
                  {vectorData?.extraccion?.dimension_vector ? `d = ${vectorData.extraccion.dimension_vector}` : '—'}
                </strong>
              </div>
              <div className="flex justify-between border-t border-slate-200 dark:border-slate-700 pt-1 text-slate-500">
                <span>Tiempo de extracción:</span>
                <span className="font-mono font-bold text-emerald-500">
                  {vectorData?.extraccion?.tiempo_extraccion_ms ? `${vectorData.extraccion.tiempo_extraccion_ms} ms` : '—'}
                </span>
              </div>
            </div>
          </div>

          {/* Diagnóstico de Calidad */}
          {vectorData?.recall_vs_fuerza_bruta && (
            <div>
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300 flex items-center gap-1.5 mb-2">
                <BarChart2 className="w-3.5 h-3.5 text-pink-500" />
                Diagnóstico de Calidad (Recall@{topK})
              </h3>

              <div className="p-3 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800/60 space-y-1.5 text-[11px]">
                <div className="flex items-center justify-between">
                  <span className="text-emerald-800 dark:text-emerald-200 font-semibold">Exactitud (Recall):</span>
                  <span className="font-mono font-bold text-sm text-emerald-700 dark:text-emerald-300">
                    {(vectorData.recall_vs_fuerza_bruta.recall_k * 100).toFixed(0)}%
                  </span>
                </div>

                <p className="text-[10px] text-emerald-700 dark:text-emerald-300">
                  {vectorData.recall_vs_fuerza_bruta.aceleracion}
                </p>

                <div className="flex items-center gap-2 pt-1 border-t border-emerald-200 dark:border-emerald-800 text-[10px]">
                  <span className="flex items-center gap-1 text-emerald-700 dark:text-emerald-300">
                    <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                    {vectorData.recall_vs_fuerza_bruta.verdaderos_positivos} Aciertos
                  </span>
                  {vectorData.recall_vs_fuerza_bruta.falsos_positivos > 0 && (
                    <span className="flex items-center gap-1 text-amber-700 dark:text-amber-300">
                      <AlertTriangle className="w-3 h-3 text-amber-500" />
                      {vectorData.recall_vs_fuerza_bruta.falsos_positivos} Falsos Positivos
                    </span>
                  )}
                </div>
              </div>
            </div>
          )}
        </aside>

        {/* Columna Derecha: Galería k-NN */}
        <main className="flex-1 p-4 overflow-y-auto space-y-3">
          {vectorData?.error ? (
            <div className="p-4 bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-800/60 rounded-lg text-rose-800 dark:text-rose-200 text-xs space-y-2">
              <div className="flex items-center gap-2 font-semibold text-rose-700 dark:text-rose-300">
                <AlertCircle className="w-4 h-4 text-rose-500" />
                <span>Respuesta del motor de base de datos:</span>
              </div>
              <p className="font-mono bg-rose-100/70 dark:bg-rose-950/60 p-2.5 rounded border border-rose-200 dark:border-rose-900/80 whitespace-pre-wrap">
                {vectorData.error}
              </p>
            </div>
          ) : !vectorData ? (
            /* Estado Inicial Vacío */
            <div className="flex flex-col items-center justify-center h-full text-slate-400 dark:text-slate-500 gap-3 py-16">
              <div className="p-4 rounded-full bg-pink-50 dark:bg-pink-950/60 border border-pink-200 dark:border-pink-800/60 text-pink-500">
                <Inbox className="w-8 h-8 stroke-1" />
              </div>
              <div className="text-center max-w-md space-y-1">
                <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
                  Laboratorio Vectorial Multimedia Listo
                </h3>
                <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                  Sube un archivo de consulta en el panel lateral izquierdo y presiona <b>Buscar</b> para recuperar los vecinos más cercanos ($k$-NN) de tu dataset usando índices de alta dimensión.
                </p>
              </div>
            </div>
          ) : vectorData.resultados?.length === 0 ? (
            <div className="p-8 text-center text-slate-500 dark:text-slate-400 text-xs bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 space-y-1">
              <Inbox className="w-6 h-6 mx-auto text-slate-400" />
              <p className="font-medium">No se encontraron elementos similares</p>
              <p className="text-[11px] text-slate-400">Verifica que la tabla tenga vectores generados o prueba ajustando la métrica.</p>
            </div>
          ) : (
            /* Grid de Resultados */
            <>
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-700 dark:text-slate-200">
                  Top {vectorData.resultados.length} Vecinos Más Cercanos
                </span>
                <span className="text-xs text-slate-400 font-mono">
                  Índice: {indexType} · Métrica: {metric}
                </span>
              </div>

              <div className={`grid gap-3.5 ${
                modalidad === 'imagen'
                  ? 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3'
                  : 'grid-cols-1 lg:grid-cols-2'
              }`}>
                {vectorData.resultados.map((item, idx) => (
                  <div
                    key={item.id || idx}
                    className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden shadow-xs hover:border-pink-300 dark:hover:border-pink-700 transition-all flex flex-col justify-between"
                  >
                    {modalidad === 'imagen' && item.media_url ? (
                      <div className="relative aspect-video bg-slate-100 dark:bg-slate-800 overflow-hidden">
                        <img
                          src={item.media_url}
                          alt={item.titulo}
                          className="w-full h-full object-cover"
                        />
                        <div className="absolute top-2 left-2">
                          <span className="w-5 h-5 rounded-full bg-pink-600 text-white font-bold text-[10px] flex items-center justify-center shadow-md">
                            #{idx + 1}
                          </span>
                        </div>
                      </div>
                    ) : null}

                    <div className="p-3 space-y-2 flex-1 flex flex-col justify-between">
                      <div>
                        <div className="flex items-center justify-between">
                          <h4 className="text-xs font-bold text-slate-800 dark:text-slate-100 truncate">
                            {item.titulo || `Item #${item.id}`}
                          </h4>
                          <span className="font-mono text-xs font-bold text-pink-600 dark:text-pink-400 bg-pink-50 dark:bg-pink-950 px-2 py-0.5 rounded">
                            Score: {typeof item.score === 'number' ? item.score.toFixed(3) : item.score}
                          </span>
                        </div>

                        <p className="text-[11px] text-slate-600 dark:text-slate-400 line-clamp-2 mt-1">
                          {item.detalles || 'Registro multimedia coincidente en espacio métrico.'}
                        </p>

                        {modalidad === 'audio' && item.audio_url && (
                          <audio controls className="w-full h-7 mt-2">
                            <source src={item.audio_url} type="audio/mpeg" />
                          </audio>
                        )}
                      </div>

                      {item.distancia !== undefined && (
                        <div className="pt-2 border-t border-slate-100 dark:border-slate-800/80 text-[10px] font-mono text-slate-400">
                          Distancia calculada: <strong>{typeof item.distancia === 'number' ? item.distancia.toFixed(3) : item.distancia}</strong>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
