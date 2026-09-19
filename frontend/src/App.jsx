import React, { useState, useEffect, useRef, useCallback } from 'react';
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
  Lock,
  Sun,
  Moon
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
    return crypto.randomUUID();
  }
}

function obtenerTemaInicial() {
  try {
    const guardado = localStorage.getItem('bd2_theme');
    if (guardado === 'light' || guardado === 'dark') return guardado;
  } catch (err) {
  }
  return 'light';
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
  const [theme, setTheme] = useState(obtenerTemaInicial);

  // Initial load of tables
  useEffect(() => {
    fetchTables();
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'dark') {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }
    try {
      localStorage.setItem('bd2_theme', theme);
    } catch (err) {
    }
  }, [theme]);

  const toggleTheme = () => setTheme(t => (t === 'dark' ? 'light' : 'dark'));

  const workspaceRef = useRef(null);
  const [queryPanelHeight, setQueryPanelHeight] = useState(() => {
    try {
      const guardado = Number(localStorage.getItem('bd2_query_panel_h'));
      if (guardado && guardado >= 130) return guardado;
    } catch (err) {
    }
    return 224;
  });
  const [resizing, setResizing] = useState(false);

  const handleResizeStart = useCallback((e) => {
    e.preventDefault();
    setResizing(true);
  }, []);

  useEffect(() => {
    if (!resizing) return undefined;

    const handleMove = (e) => {
      const contenedor = workspaceRef.current;
      if (!contenedor) return;
      const top = contenedor.getBoundingClientRect().top;
      const minAltura = 130;
      const maxAltura = contenedor.getBoundingClientRect().height - 150;
      const nuevaAltura = Math.min(Math.max(e.clientY - top, minAltura), maxAltura);
      setQueryPanelHeight(nuevaAltura);
    };
    const handleUp = () => setResizing(false);

    document.addEventListener('mousemove', handleMove);
    document.addEventListener('mouseup', handleUp);
    return () => {
      document.removeEventListener('mousemove', handleMove);
      document.removeEventListener('mouseup', handleUp);
    };
  }, [resizing]);

  useEffect(() => {
    if (resizing) return;
    try {
      localStorage.setItem('bd2_query_panel_h', String(queryPanelHeight));
    } catch (err) {
    }
  }, [resizing, queryPanelHeight]);

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
      if (qUpper.includes('INSERT') || qUpper.includes('DELETE') || qUpper.includes('CREATE TABLE') || qUpper.includes('DROP TABLE') || terminoTransaccion) {
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
    if (sentencias.length !== 1) return;
    const objetivo = sentencias[0];
    if (!/^(SELECT|INSERT|DELETE)\b/i.test(objetivo)) return;

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

  const handleDropTable = async (tableName) => {
    const data = await ejecutarUnaSentencia(`DROP TABLE ${tableName};`);
    if (data.status !== 'success') {
      alert(`No se pudo eliminar '${tableName}':\n${data.error || 'error desconocido'}`);
      return;
    }
    if (selectedTable === tableName) setSelectedTable(null);
    fetchTables();
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
    <div className={`flex flex-col h-screen w-screen bg-slate-50 dark:bg-slate-950 text-slate-800 dark:text-slate-100 overflow-hidden font-sans transition-colors ${resizing ? 'select-none cursor-row-resize' : ''}`}>
      {/* Top Navbar */}
      <header className="h-12 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 px-4 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-md bg-pg-500 flex items-center justify-center shadow-sm">
            <Database className="w-4 h-4 text-white" />
          </div>
          <div>
            <h1 className="font-bold text-sm tracking-wide text-slate-800 dark:text-white flex items-center gap-2">
              <span>Minigestor Multimodal BD2</span>
              <span className="text-[10px] bg-pg-50 dark:bg-pg-950 text-pg-700 dark:text-pg-300 border border-pg-200 dark:border-pg-800 px-1.5 py-0.2 rounded font-mono font-normal">
                Parte 1 (SQL & Storage)
              </span>
            </h1>
          </div>
        </div>

        {/* Engine status and tools */}
        <div className="flex items-center gap-3 text-xs">
          {transactionState.active && (
            <div
              className="flex items-center gap-1.5 px-2.5 py-1 bg-amber-50 dark:bg-amber-950/60 rounded-full border border-amber-300 dark:border-amber-700/60 text-[11px] text-amber-700 dark:text-amber-300"
              title={`session_id: ${sessionId}`}
            >
              <Lock className="w-3 h-3" />
              <span>Transacción activa: {transactionState.xact_id}</span>
            </div>
          )}

          <button
            onClick={handleReseed}
            title="Reiniciar datos de demostración en disco"
            className="flex items-center gap-1.5 px-2.5 py-1 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white rounded border border-slate-200 dark:border-slate-700/60 transition text-xs"
          >
            <RotateCcw className="w-3.5 h-3.5 text-amber-500 dark:text-amber-400" />
            <span className="hidden sm:inline">Reiniciar Tablas</span>
          </button>

          <button
            onClick={toggleTheme}
            title={theme === 'dark' ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro'}
            className="flex items-center justify-center w-7 h-7 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white rounded-full border border-slate-200 dark:border-slate-700/60 transition"
          >
            {theme === 'dark' ? <Sun className="w-3.5 h-3.5" /> : <Moon className="w-3.5 h-3.5" />}
          </button>

          <div className="flex items-center gap-1.5 px-2.5 py-1 bg-slate-100 dark:bg-slate-950/80 rounded-full border border-slate-200 dark:border-slate-800 text-[11px]">
            {engineConnected ? (
              <>
                <span className="w-2 h-2 rounded-full bg-emerald-500 dark:bg-emerald-400 animate-pulse" />
                <span className="text-slate-600 dark:text-slate-300">Motor Activo</span>
              </>
            ) : (
              <>
                <span className="w-2 h-2 rounded-full bg-rose-500" />
                <span className="text-rose-600 dark:text-rose-400">Motor Desconectado</span>
              </>
            )}
          </div>
        </div>
      </header>

      {/* Main Workspace Layout */}
      <div className="flex-1 flex overflow-hidden">
        {/* Panel 1: Panel de Archivos (Left Sidebar) */}
        <aside className="w-80 shrink-0 h-full border-r border-slate-200 dark:border-slate-800">
          <FilePanel
            tables={tables}
            selectedTable={selectedTable}
            onSelectTable={setSelectedTable}
            onRunSelectStar={handleRunSelectStar}
            onReorganize={handleReorganize}
            onDropTable={handleDropTable}
            onRefresh={fetchTables}
            loading={loadingTables}
          />
        </aside>

        {/* Center / Right Section */}
        <main ref={workspaceRef} className="flex-1 flex flex-col h-full min-w-0 overflow-hidden">
          {/* Panel 2: Panel de Consultas (altura arrastrable) */}
          <div style={{ height: queryPanelHeight }} className="shrink-0 min-h-0 overflow-hidden">
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

          <div
            onMouseDown={handleResizeStart}
            title="Arrastra para redimensionar"
            className={`h-1.5 shrink-0 cursor-row-resize flex items-center justify-center group ${
              resizing ? 'bg-pg-400 dark:bg-pg-500' : 'bg-slate-200 dark:bg-slate-800 hover:bg-pg-300 dark:hover:bg-pg-600'
            } transition-colors`}
          >
            <div className="w-8 h-0.5 rounded-full bg-slate-400 dark:bg-slate-600 group-hover:bg-white/80" />
          </div>

          {/* Bottom Area: Panel 3 (Resultados) & Panel 4 (Plan de Ejecución) */}
          <div className="flex-1 flex flex-col min-h-0 bg-white dark:bg-slate-900">
            {/* Tab selector between Resultados and Plan de Ejecución */}
            <div className="h-9 bg-slate-100 dark:bg-slate-950/80 border-b border-slate-200 dark:border-slate-800 px-3 flex items-center gap-1 shrink-0">
              <button
                onClick={() => setActiveBottomTab('results')}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-t transition-colors ${
                  activeBottomTab === 'results'
                    ? 'bg-white dark:bg-slate-900 text-pg-700 dark:text-pg-300 border-t-2 border-pg-500 border-x border-slate-200 dark:border-slate-800'
                    : 'text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200'
                }`}
              >
                <Table2 className="w-3.5 h-3.5" />
                <span>Panel de Resultados</span>
                {queryResult && queryResult.rows && (
                  <span className="ml-1 text-[10px] bg-slate-200 dark:bg-slate-800 text-slate-600 dark:text-slate-400 px-1.5 py-0.2 rounded-full font-mono">
                    {queryResult.rows.length}
                  </span>
                )}
              </button>

              <button
                onClick={() => setActiveBottomTab('plan')}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-t transition-colors ${
                  activeBottomTab === 'plan'
                    ? 'bg-white dark:bg-slate-900 text-violet-700 dark:text-violet-300 border-t-2 border-violet-500 border-x border-slate-200 dark:border-slate-800'
                    : 'text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200'
                }`}
              >
                <GitBranch className="w-3.5 h-3.5" />
                <span>Panel de Plan de Ejecución</span>
                {executionPlan && (
                  <span className="w-1.5 h-1.5 rounded-full bg-violet-500 dark:bg-violet-400" />
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
                  executedQuery={queryResult?.query}
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
