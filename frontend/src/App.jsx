import React, { useState, useEffect } from 'react';
import {
  Database,
  Table2,
  GitBranch,
  RefreshCw,
  Sparkles,
  CheckCircle2,
  XCircle,
  Terminal,
  Layers,
  HelpCircle,
  RotateCcw,
  Lock
} from 'lucide-react';

import FilePanel from './components/FilePanel';
import QueryPanel from './components/QueryPanel';
import ResultsPanel from './components/ResultsPanel';
import PlanPanel from './components/PlanPanel';
import CsvImportModal from './components/CsvImportModal';

function obtenerOCrearSessionId() {
  try {
    const existente = localStorage.getItem('bd2_session_id');
    if (existente) return existente;
    const nuevo = crypto.randomUUID();
    localStorage.setItem('bd2_session_id', nuevo);
    return nuevo;
  } catch (err) {
    // localStorage puede fallar (modo privado); usa un id solo para esta pestaña
    return crypto.randomUUID();
  }
}

export default function App() {
  const [tables, setTables] = useState([]);
  const [selectedTable, setSelectedTable] = useState(null);
  const [query, setQuery] = useState('SELECT * FROM estudiantes;');
  const [history, setHistory] = useState([
    'SELECT * FROM estudiantes;',
    'SELECT * FROM cursos;'
  ]);
  const [queryResult, setQueryResult] = useState(null);
  const [executionPlan, setExecutionPlan] = useState(null);
  const [activeBottomTab, setActiveBottomTab] = useState('results'); // 'results' | 'plan'

  const [loadingTables, setLoadingTables] = useState(false);
  const [loadingQuery, setLoadingQuery] = useState(false);
  const [engineConnected, setEngineConnected] = useState(true);

  const [sessionId] = useState(obtenerOCrearSessionId);
  const [transactionState, setTransactionState] = useState({ active: false, xact_id: null });
  const [csvImportOpen, setCsvImportOpen] = useState(false);

  // Initial load of tables
  useEffect(() => {
    fetchTables();
  }, []);

  const fetchTables = async () => {
    setLoadingTables(true);
    try {
      const res = await fetch('/api/tables');
      if (!res.ok) throw new Error('Error al conectar con la API');
      const data = await res.json();
      setTables(data);
      setEngineConnected(true);
      if (data.length > 0 && !selectedTable) {
        setSelectedTable(data[0].name);
      }
    } catch (err) {
      console.error('Error fetching tables:', err);
      setEngineConnected(false);
    } finally {
      setLoadingTables(false);
    }
  };

  const ejecutarUnaSentencia = async (sentencia) => {
    const res = await fetch('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: sentencia, session_id: sessionId }),
    });
    return res.json();
  };

  const handleExecuteQuery = async (customQuery = null) => {
    const q = customQuery || query;
    if (!q.trim()) return;

    // Un script pegado (plantilla "Transacción completa") puede traer varias
    // sentencias separadas por ';'; se ejecutan en orden sobre el mismo
    // session_id y se detiene en el primer error.
    const sentencias = q.split(';').map(s => s.trim()).filter(Boolean);

    setLoadingQuery(true);
    let data = null;
    let activaAntes = transactionState.active;
    try {
      for (const sentencia of sentencias) {
        data = await ejecutarUnaSentencia(sentencia + ';');
        if (data.transaction) {
          setTransactionState(data.transaction);
        }
        if (data.status !== 'success') {
          if (data.transaction && data.transaction.active) {
            try {
              const rb = await ejecutarUnaSentencia('ROLLBACK;');
              if (rb.transaction) setTransactionState(rb.transaction);
              data = { ...data, error: `${data.error || ''} (transacción revertida automáticamente)`.trim() };
            } catch (rbErr) {
              console.error('Fallo el ROLLBACK automático tras error en script:', rbErr);
            }
          }
          break;
        }
      }

      setQueryResult(data);
      if (data && data.plan) {
        setExecutionPlan(data.plan);
      }
      setActiveBottomTab('results');

      setHistory(prev => {
        if (prev[prev.length - 1] === q) return prev;
        return [...prev, q];
      });

      const terminoTransaccion = activaAntes && data && data.transaction && !data.transaction.active;
      const qUpper = q.trim().toUpperCase();
      if (qUpper.includes('INSERT') || qUpper.includes('DELETE') || qUpper.includes('CREATE TABLE') || terminoTransaccion) {
        fetchTables();
      }
    } catch (err) {
      console.error('Query execution error:', err);
      setQueryResult({
        status: 'error',
        query: q,
        error: `Fallo de conexión al motor: ${err.message}`,
        execution_time_ms: 0,
      });
    } finally {
      setLoadingQuery(false);
    }
  };

  const handleExplainQuery = async (analyze = false) => {
    if (!query.trim()) return;
    const sentencias = query.split(';').map(s => s.trim()).filter(Boolean);
    if (sentencias.length === 0) return;
    const explicables = sentencias.filter(s => /^(SELECT|INSERT|DELETE)\b/i.test(s));
    if (explicables.length === 0) {
      alert(
        'EXPLAIN solo puede analizar sentencias SELECT, INSERT o DELETE.\n\n' +
        'El editor no tiene ninguna (por ejemplo, CREATE TABLE o BEGIN/COMMIT/ROLLBACK no se pueden explicar).'
      );
      return;
    }
    const objetivo = explicables[0];
    if (sentencias.length > 1) {
      const continuar = confirm(
        `El editor tiene ${sentencias.length} sentencias, pero EXPLAIN solo puede analizar una a la vez.\n\n` +
        `Se analizará:\n${objetivo}\n\n¿Continuar?`
      );
      if (!continuar) return;
    }

    setLoadingQuery(true);
    try {
      const res = await fetch('/api/explain', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: objetivo, session_id: sessionId, analyze }),
      });
      const data = await res.json();
      if (data.transaction) {
        setTransactionState(data.transaction);
      }

      const qUpper = objetivo.toUpperCase();
      if (analyze && (qUpper.includes('INSERT') || qUpper.includes('DELETE') || qUpper.includes('CREATE TABLE'))) {
        fetchTables();
      }
      setQueryResult(data);
      setExecutionPlan(data.plan || null);
      setActiveBottomTab('plan');
    } catch (err) {
      console.error('Explain error:', err);
      alert('Error obteniendo el plan de ejecución: ' + err.message);
    } finally {
      setLoadingQuery(false);
    }
  };

  const handleReorganize = async (tableName) => {
    try {
      const res = await fetch('/api/tables/reorganize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ table_name: tableName }),
      });
      const data = await res.json();
      alert(`Reorganización completada para '${tableName}':\nTiempo: ${data.duration_ms} ms\nNuevo ratio de desperdicio: ${(data.new_wasted_ratio * 100).toFixed(1)}%`);
      fetchTables();
    } catch (err) {
      alert('Error en reorganización: ' + err.message);
    }
  };

  const handleRunSelectStar = (tableName) => {
    const q = `SELECT * FROM ${tableName};`;
    setQuery(q);
    handleExecuteQuery(q);
  };

  const handleCsvScriptReady = (script) => {
    setQuery(script);
    setCsvImportOpen(false);
  };

  const handleReseed = async () => {
    if (!confirm('¿Deseas reiniciar las tablas con datos de prueba de disco?')) return;
    try {
      await fetch('/api/seed', { method: 'POST' });
      fetchTables();
    } catch (err) {
      alert('Error al reiniciar datos: ' + err.message);
    }
  };

  return (
    <div className="flex flex-col h-screen w-screen bg-slate-950 text-slate-100 overflow-hidden font-sans">
      {/* Top Navbar */}
      <header className="h-12 bg-slate-900 border-b border-slate-800 px-4 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-md bg-indigo-600 flex items-center justify-center shadow-md">
            <Database className="w-4 h-4 text-white" />
          </div>
          <div>
            <h1 className="font-bold text-sm tracking-wide text-white flex items-center gap-2">
              <span>Minigestor Multimodal BD2</span>
              <span className="text-[10px] bg-indigo-950 text-indigo-300 border border-indigo-800 px-1.5 py-0.2 rounded font-mono font-normal">
                Parte 1 (SQL & Storage)
              </span>
            </h1>
          </div>
        </div>

        {/* Engine status and tools */}
        <div className="flex items-center gap-3 text-xs">
          {transactionState.active && (
            <div
              className="flex items-center gap-1.5 px-2.5 py-1 bg-amber-950/60 rounded-full border border-amber-700/60 text-[11px] text-amber-300"
              title={`session_id: ${sessionId}`}
            >
              <Lock className="w-3 h-3" />
              <span>Transacción activa: {transactionState.xact_id}</span>
            </div>
          )}

          <button
            onClick={handleReseed}
            title="Reiniciar datos de demostración en disco"
            className="flex items-center gap-1.5 px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded border border-slate-700/60 transition text-xs"
          >
            <RotateCcw className="w-3.5 h-3.5 text-amber-400" />
            <span className="hidden sm:inline">Reiniciar Tablas</span>
          </button>

          <div className="flex items-center gap-1.5 px-2.5 py-1 bg-slate-950/80 rounded-full border border-slate-800 text-[11px]">
            {engineConnected ? (
              <>
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                <span className="text-slate-300">Motor Activo</span>
              </>
            ) : (
              <>
                <span className="w-2 h-2 rounded-full bg-rose-500" />
                <span className="text-rose-400">Motor Desconectado</span>
              </>
            )}
          </div>
        </div>
      </header>

      {/* Main Workspace Layout */}
      <div className="flex-1 flex overflow-hidden">
        {/* Panel 1: Panel de Archivos (Left Sidebar) */}
        <aside className="w-80 shrink-0 h-full border-r border-slate-800">
          <FilePanel
            tables={tables}
            selectedTable={selectedTable}
            onSelectTable={setSelectedTable}
            onRunSelectStar={handleRunSelectStar}
            onReorganize={handleReorganize}
            onRefresh={fetchTables}
            loading={loadingTables}
          />
        </aside>

        {/* Center / Right Section */}
        <main className="flex-1 flex flex-col h-full min-w-0 overflow-hidden">
          {/* Panel 2: Panel de Consultas (Top Half) */}
          <div className="h-56 shrink-0">
            <QueryPanel
              query={query}
              setQuery={setQuery}
              onExecute={() => handleExecuteQuery()}
              onExplain={handleExplainQuery}
              onOpenCsvImport={() => setCsvImportOpen(true)}
              loading={loadingQuery}
              history={history}
            />
          </div>

          {/* Bottom Area: Panel 3 (Resultados) & Panel 4 (Plan de Ejecución) */}
          <div className="flex-1 flex flex-col min-h-0 bg-slate-900">
            {/* Tab selector between Resultados and Plan de Ejecución */}
            <div className="h-9 bg-slate-950/80 border-b border-slate-800 px-3 flex items-center gap-1 shrink-0">
              <button
                onClick={() => setActiveBottomTab('results')}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-t transition-colors ${
                  activeBottomTab === 'results'
                    ? 'bg-slate-900 text-indigo-300 border-t-2 border-indigo-500 border-x border-slate-800'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <Table2 className="w-3.5 h-3.5" />
                <span>Panel de Resultados</span>
                {queryResult && queryResult.rows && (
                  <span className="ml-1 text-[10px] bg-slate-800 text-slate-400 px-1.5 py-0.2 rounded-full font-mono">
                    {queryResult.rows.length}
                  </span>
                )}
              </button>

              <button
                onClick={() => setActiveBottomTab('plan')}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-t transition-colors ${
                  activeBottomTab === 'plan'
                    ? 'bg-slate-900 text-purple-300 border-t-2 border-purple-500 border-x border-slate-800'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <GitBranch className="w-3.5 h-3.5" />
                <span>Panel de Plan de Ejecución</span>
                {executionPlan && (
                  <span className="w-1.5 h-1.5 rounded-full bg-purple-400" />
                )}
              </button>
            </div>

            {/* Tab Content */}
            <div className="flex-1 min-h-0 overflow-hidden">
              {activeBottomTab === 'results' ? (
                <ResultsPanel
                  result={queryResult}
                  loading={loadingQuery}
                />
              ) : (
                <PlanPanel
                  plan={executionPlan}
                  query={query}
                />
              )}
            </div>
          </div>
        </main>
      </div>

      {csvImportOpen && (
        <CsvImportModal
          tables={tables}
          onClose={() => setCsvImportOpen(false)}
          onUseScript={handleCsvScriptReady}
        />
      )}
    </div>
  );
}
