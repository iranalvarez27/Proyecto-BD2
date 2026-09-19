import React, { useState } from 'react';
import {
  Table2,
  CheckCircle2,
  AlertCircle,
  Clock,
  Download,
  Copy,
  Check,
  Inbox,
  FileSpreadsheet
} from 'lucide-react';

export default function ResultsPanel({ result, loading }) {
  const [copied, setCopied] = useState(false);

  const handleCopyJSON = () => {
    if (!result) return;
    navigator.clipboard.writeText(JSON.stringify(result, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleExportCSV = () => {
    if (!result || !result.columns || !result.rows) return;
    const header = result.columns.join(',');
    const rows = result.rows.map(row =>
      row.map(val => typeof val === 'string' ? `"${val.replace(/"/g, '""')}"` : val).join(',')
    );
    const csvContent = "data:text/csv;charset=utf-8," + [header, ...rows].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `resultado_consulta_${Date.now()}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-100">
      {/* Header bar */}
      <div className="p-2.5 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between flex-wrap gap-2 bg-white/90 dark:bg-slate-900/90">
        <div className="flex items-center gap-2">
          <Table2 className="w-4 h-4 text-pg-600 dark:text-pg-400" />
          <h2 className="font-semibold text-xs tracking-wide uppercase text-slate-600 dark:text-slate-300">
            Panel de Resultados
          </h2>

          {/* Status Badge */}
          {result && (
            result.status === 'success' ? (
              <span className="flex items-center gap-1 text-[11px] bg-emerald-50 dark:bg-emerald-950/80 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60 px-2 py-0.5 rounded-full font-medium">
                <CheckCircle2 className="w-3 h-3" /> Éxito
              </span>
            ) : (
              <span className="flex items-center gap-1 text-[11px] bg-rose-50 dark:bg-rose-950/80 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-800/60 px-2 py-0.5 rounded-full font-medium">
                <AlertCircle className="w-3 h-3" /> Error
              </span>
            )
          )}
        </div>

        {/* Metrics & Actions */}
        {result && (
          <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
            {result.execution_time_ms !== undefined && (
              <div className="flex items-center gap-1 font-mono">
                <Clock className="w-3.5 h-3.5 text-slate-400 dark:text-slate-500" />
                <span className="text-slate-700 dark:text-slate-200">{result.execution_time_ms} ms</span>
              </div>
            )}

            {result.affected_rows !== undefined && (
              <div className="font-mono">
                Filas: <span className="text-slate-700 dark:text-slate-200 font-medium">{result.affected_rows}</span>
              </div>
            )}

            {/* Export buttons */}
            {result.rows && result.rows.length > 0 && (
              <div className="flex items-center gap-1 ml-2 border-l border-slate-200 dark:border-slate-800 pl-2">
                <button
                  onClick={handleExportCSV}
                  title="Exportar como CSV"
                  className="p-1 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200 rounded transition flex items-center gap-1 text-[11px]"
                >
                  <FileSpreadsheet className="w-3.5 h-3.5" />
                  <span className="hidden sm:inline">CSV</span>
                </button>
                <button
                  onClick={handleCopyJSON}
                  title="Copiar JSON al portapapeles"
                  className="p-1 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200 rounded transition flex items-center gap-1 text-[11px]"
                >
                  {copied ? <Check className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                  <span className="hidden sm:inline">{copied ? 'Copiado' : 'JSON'}</span>
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Body Content */}
      <div className="flex-1 overflow-auto p-2">
        {loading ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-500 dark:text-slate-400 gap-2">
            <div className="w-6 h-6 border-2 border-pg-500 border-t-transparent rounded-full animate-spin" />
            <span className="text-xs">Ejecutando consulta en el motor...</span>
          </div>
        ) : !result ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-400 dark:text-slate-500 gap-2 py-10">
            <Inbox className="w-8 h-8 stroke-1 text-slate-300 dark:text-slate-600" />
            <p className="text-xs text-center max-w-sm">
              Escribe una consulta SQL en el panel superior y presiona <b>Ejecutar</b> para visualizar aquí las tuplas obtenidas.
            </p>
          </div>
        ) : result.status === 'error' ? (
          <div className="p-4 bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-800/60 rounded-lg text-rose-800 dark:text-rose-200 text-xs space-y-2">
            <div className="flex items-center gap-2 font-semibold text-rose-700 dark:text-rose-300">
              <AlertCircle className="w-4 h-4 text-rose-500 dark:text-rose-400" />
              <span>Fallo en el procesamiento de la consulta:</span>
            </div>
            <p className="font-mono bg-rose-100/70 dark:bg-rose-950/60 p-2.5 rounded border border-rose-200 dark:border-rose-900/80 whitespace-pre-wrap">
              {result.error || 'Error desconocido al ejecutar la consulta.'}
            </p>
          </div>
        ) : (
          /* Success Table */
          result.rows && result.rows.length > 0 ? (
            <div className="rounded border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm">
              <table className="w-full text-left text-xs text-slate-600 dark:text-slate-300 border-collapse">
                <thead className="bg-slate-50 dark:bg-slate-950/70 text-slate-500 dark:text-slate-400 uppercase font-semibold text-[11px] border-b border-slate-200 dark:border-slate-800 sticky top-0">
                  <tr>
                    <th className="py-2 px-3 w-10 text-slate-400 dark:text-slate-600 text-center font-mono">#</th>
                    {result.columns.map((col, idx) => (
                      <th key={idx} className="py-2 px-3 border-l border-slate-200 dark:border-slate-800/60">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-slate-800/60 font-mono">
                  {result.rows.map((row, rowIdx) => (
                    <tr
                      key={rowIdx}
                      className="hover:bg-pg-50 dark:hover:bg-slate-800/50 transition-colors odd:bg-white even:bg-slate-50 dark:odd:bg-slate-900 dark:even:bg-slate-950/20"
                    >
                      <td className="py-2 px-3 text-center text-slate-400 dark:text-slate-600 text-[10px] select-none">
                        {rowIdx + 1}
                      </td>
                      {row.map((val, cellIdx) => (
                        <td
                          key={cellIdx}
                          className={`py-2 px-3 border-l border-slate-200 dark:border-slate-800/40 truncate max-w-[240px] ${
                            typeof val === 'number' ? 'text-sky-700 dark:text-sky-300 text-right' : 'text-slate-700 dark:text-slate-200'
                          }`}
                        >
                          {val === null || val === undefined ? (
                            <span className="text-slate-400 dark:text-slate-600 italic">NULL</span>
                          ) : typeof val === 'boolean' ? (
                            val ? 'TRUE' : 'FALSE'
                          ) : (
                            String(val)
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="p-4 text-center text-slate-500 dark:text-slate-400 text-xs bg-slate-50 dark:bg-slate-950/20 rounded border border-slate-200 dark:border-slate-800">
              {result.affected_rows !== undefined && result.affected_rows > 0 ? (
                <span>Operación ejecutada con éxito. Filas afectadas: {result.affected_rows}</span>
              ) : (
                <span>La consulta no retornó filas (0 registros).</span>
              )}
            </div>
          )
        )}
      </div>
    </div>
  );
}
