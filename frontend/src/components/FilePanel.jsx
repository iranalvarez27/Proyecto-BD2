import React, { useState } from 'react';
import {
  Table,
  Key,
  Layers,
  RefreshCw,
  AlertTriangle,
  CheckCircle2,
  FolderTree,
  HardDrive,
  Zap,
  Play,
  Trash2
} from 'lucide-react';

export default function FilePanel({
  tables,
  selectedTable,
  onSelectTable,
  onRunSelectStar,
  onReorganize,
  onDropTable,
  onRefresh,
  loading
}) {
  const [expandedTable, setExpandedTable] = useState(null);
  const [reorganizing, setReorganizing] = useState(null);
  const [dropping, setDropping] = useState(null);

  const toggleExpand = (tableName) => {
    setExpandedTable(prev => prev === tableName ? null : tableName);
    onSelectTable(tableName);
  };

  const handleReorganizeClick = async (e, tableName) => {
    e.stopPropagation();
    setReorganizing(tableName);
    try {
      await onReorganize(tableName);
    } finally {
      setReorganizing(null);
    }
  };

  const handleDropClick = async (e, tableName) => {
    e.stopPropagation();
    if (!onDropTable) return;
    const confirmado = window.confirm(
      `¿Eliminar la tabla '${tableName}' por completo?\n\n` +
      'Esto borra sus archivos de disco (datos e índices) de forma IRREVERSIBLE. ' +
      'No hay papelera de reciclaje ni ROLLBACK posible.'
    );
    if (!confirmado) return;
    setDropping(tableName);
    try {
      await onDropTable(tableName);
    } finally {
      setDropping(null);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-200">
      {/* Header */}
      <div className="p-3 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FolderTree className="w-5 h-5 text-pg-600 dark:text-pg-400" />
          <h2 className="font-semibold text-sm tracking-wide uppercase text-slate-600 dark:text-slate-300">
            Panel de Archivos
          </h2>
          <span className="bg-slate-100 dark:bg-slate-800 text-xs text-slate-500 dark:text-slate-400 px-2 py-0.5 rounded-full font-mono">
            {tables.length}
          </span>
        </div>
        <button
          onClick={onRefresh}
          disabled={loading}
          title="Recargar esquemas"
          className="p-1.5 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded transition disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Subtitle description */}
      <div className="px-3 py-2 text-xs text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-950/40 border-b border-slate-200 dark:border-slate-800/60">
        Estructura de almacenamiento físico (Heap & Secuencial) e índices.
      </div>

      {/* Table list */}
      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {tables.length === 0 ? (
          <div className="text-center py-8 text-xs text-slate-400 dark:text-slate-500">
            {loading ? 'Cargando archivos...' : 'No hay tablas registradas.'}
          </div>
        ) : (
          tables.map(table => {
            const isExpanded = expandedTable === table.name;
            const isSequential = table.storage_type === 'SEQUENTIAL';
            const wasteRatio = table.stats?.wasted_ratio || 0;
            const wastePercent = Math.round(wasteRatio * 100);
            const needsReorg = table.stats?.needs_reorganization || wastePercent >= 30;

            return (
              <div
                key={table.name}
                className={`rounded-lg border transition-all duration-150 ${
                  selectedTable === table.name
                    ? 'border-pg-400 dark:border-pg-500/60 bg-pg-50/60 dark:bg-slate-800/70 shadow-sm'
                    : 'border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/60 hover:border-slate-300 dark:hover:border-slate-700'
                }`}
              >
                {/* Table row header */}
                <div
                  onClick={() => toggleExpand(table.name)}
                  className="p-2.5 flex items-center justify-between cursor-pointer group"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <Table className={`w-4 h-4 shrink-0 ${isSequential ? 'text-violet-500 dark:text-violet-400' : 'text-sky-500 dark:text-sky-400'}`} />
                    <span className="font-medium text-sm text-slate-800 dark:text-slate-100 truncate">
                      {table.name}
                    </span>
                  </div>

                  <div className="flex items-center gap-1.5 shrink-0">
                    {/* Storage badge */}
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono font-medium ${
                      isSequential
                        ? 'bg-violet-50 dark:bg-violet-950/80 text-violet-700 dark:text-violet-300 border border-violet-200 dark:border-violet-800/50'
                        : 'bg-sky-50 dark:bg-sky-950/80 text-sky-700 dark:text-sky-300 border border-sky-200 dark:border-sky-800/50'
                    }`}>
                      {table.storage_type}
                    </span>

                    {/* Quick Query Button */}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onRunSelectStar(table.name);
                      }}
                      title={`SELECT * FROM ${table.name}`}
                      className="p-1 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-500 hover:text-pg-700 dark:text-slate-400 dark:hover:text-pg-300 rounded transition opacity-70 group-hover:opacity-100"
                    >
                      <Play className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                {/* Expanded Details */}
                {isExpanded && (
                  <div className="px-3 pb-3 pt-1 border-t border-slate-200 dark:border-slate-800/70 text-xs space-y-3 bg-slate-50/70 dark:bg-slate-950/30">
                    {/* Columns list */}
                    <div>
                      <div className="text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1.5 flex items-center gap-1">
                        <span>Columnas ({table.columns.length})</span>
                      </div>
                      <div className="space-y-1 pl-1">
                        {table.columns.map(col => (
                          <div key={col.name} className="flex items-center justify-between py-0.5 text-slate-600 dark:text-slate-300">
                            <div className="flex items-center gap-1.5">
                              {col.is_pk ? (
                                <Key className="w-3 h-3 text-amber-500 dark:text-amber-400 shrink-0" title="Primary Key" />
                              ) : (
                                <span className="w-3 h-3 block" />
                              )}
                              <span className={col.is_pk ? "font-semibold text-amber-600 dark:text-amber-300" : ""}>
                                {col.name}
                              </span>
                            </div>
                            <span className="font-mono text-[10px] text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-800/80 px-1.5 py-0.2 rounded">
                              {col.type}{col.size ? `(${col.size})` : ''}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Indexes list */}
                    {table.indexes && table.indexes.length > 0 && (
                      <div>
                        <div className="text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1.5 flex items-center gap-1">
                          <Layers className="w-3 h-3 text-emerald-500 dark:text-emerald-400" />
                          <span>Índices Activos</span>
                        </div>
                        <div className="space-y-1 pl-1">
                          {table.indexes.map(idx => (
                            <div key={idx.name} className="flex items-center justify-between text-[11px] text-slate-600 dark:text-slate-300 bg-white dark:bg-slate-900/80 p-1.5 rounded border border-slate-200 dark:border-slate-800">
                              <span className="font-medium text-emerald-600 dark:text-emerald-300 truncate max-w-[120px]" title={idx.name}>
                                {idx.name}
                              </span>
                              <div className="flex items-center gap-1 font-mono text-[10px]">
                                <span className="text-slate-500 dark:text-slate-400">{idx.column}</span>
                                <span className="text-emerald-600 dark:text-emerald-400 font-semibold">[{idx.type}]</span>
                                {idx.clustered && (
                                  <span className="text-[9px] bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 px-1 rounded">Clustered</span>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Storage Stats */}
                    <div className="bg-white dark:bg-slate-900 p-2 rounded border border-slate-200 dark:border-slate-800/80 space-y-1.5">
                      <div className="text-[11px] font-semibold text-slate-600 dark:text-slate-300 flex items-center gap-1.5">
                        <HardDrive className="w-3.5 h-3.5 text-pg-600 dark:text-pg-400" />
                        <span>Métricas de Disco</span>
                      </div>
                      <div className="grid grid-cols-2 gap-1 text-[11px] text-slate-500 dark:text-slate-400">
                        <div>Páginas 4KB: <span className="text-slate-700 dark:text-slate-200 font-mono font-medium">{table.stats?.page_count ?? 0}</span></div>
                        <div>Registros: <span className="text-slate-700 dark:text-slate-200 font-mono font-medium">{table.stats?.record_count ?? 0}</span></div>
                      </div>

                      {isSequential && (
                        <div className="pt-1.5 border-t border-slate-200 dark:border-slate-800">
                          <div className="flex items-center justify-between text-[11px] mb-1">
                            <span className="text-slate-500 dark:text-slate-400">Desperdicio (Lazy del):</span>
                            <span className={`font-mono font-semibold ${needsReorg ? 'text-rose-600 dark:text-rose-400' : 'text-emerald-600 dark:text-emerald-400'}`}>
                              {wastePercent}%
                            </span>
                          </div>
                          <div className="w-full bg-slate-200 dark:bg-slate-800 h-1.5 rounded-full overflow-hidden">
                            <div
                              className={`h-full transition-all ${needsReorg ? 'bg-rose-500' : 'bg-emerald-500'}`}
                              style={{ width: `${Math.min(wastePercent, 100)}%` }}
                            />
                          </div>

                          {needsReorg && (
                            <div className="mt-2 flex items-center justify-between bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800/60 p-1.5 rounded text-[11px] text-rose-700 dark:text-rose-300">
                              <span className="flex items-center gap-1">
                                <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                                Reorganización sugerida (&gt;30%)
                              </span>
                            </div>
                          )}

                          <button
                            onClick={(e) => handleReorganizeClick(e, table.name)}
                            disabled={reorganizing === table.name}
                            className="mt-2 w-full flex items-center justify-center gap-1.5 py-1 px-2 bg-violet-50 hover:bg-violet-100 dark:bg-violet-600/20 dark:hover:bg-violet-600/30 border border-violet-300 dark:border-violet-500/40 text-violet-700 dark:text-violet-200 hover:text-violet-900 dark:hover:text-white rounded transition text-xs font-medium disabled:opacity-50"
                          >
                            <Zap className={`w-3.5 h-3.5 ${reorganizing === table.name ? 'animate-spin' : ''}`} />
                            {reorganizing === table.name ? 'Reorganizando...' : 'Reorganizar Archivo'}
                          </button>
                        </div>
                      )}

                      {onDropTable && (
                        <div className="pt-1.5 border-t border-slate-200 dark:border-slate-800">
                          <button
                            onClick={(e) => handleDropClick(e, table.name)}
                            disabled={dropping === table.name}
                            title={`DROP TABLE ${table.name} (irreversible)`}
                            className="w-full flex items-center justify-center gap-1.5 py-1 px-2 bg-rose-50 hover:bg-rose-100 dark:bg-rose-600/20 dark:hover:bg-rose-600/30 border border-rose-300 dark:border-rose-500/40 text-rose-700 dark:text-rose-200 hover:text-rose-900 dark:hover:text-white rounded transition text-xs font-medium disabled:opacity-50"
                          >
                            <Trash2 className={`w-3.5 h-3.5 ${dropping === table.name ? 'animate-pulse' : ''}`} />
                            {dropping === table.name ? 'Eliminando...' : 'Eliminar Tabla (DROP)'}
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Footer Info */}
      <div className="p-3 border-t border-slate-200 dark:border-slate-800 text-[11px] text-slate-400 dark:text-slate-500 flex items-center justify-between">
        <span>Minigestor BD2 v1.0</span>
        <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
          <CheckCircle2 className="w-3 h-3" /> Conectado
        </span>
      </div>
    </div>
  );
}
