import React from 'react';
import {
  GitBranch,
  Layers,
  Filter,
  ArrowUpDown,
  HardDrive,
  Key,
  Share2,
  Zap,
  Info
} from 'lucide-react';

function PlanNode({ node, depth = 0, isLast = true }) {
  if (!node) return null;

  // Determine icon & color based on node type
  let Icon = GitBranch;
  let borderColor = 'border-pg-400 dark:border-pg-500/50';
  let badgeBg = 'bg-pg-50 dark:bg-pg-950/80 text-pg-700 dark:text-pg-300 border-pg-200 dark:border-pg-800/60';

  const type = node.node_type || '';

  if (type.includes('Scan')) {
    Icon = HardDrive;
    borderColor = 'border-sky-400 dark:border-sky-500/50';
    badgeBg = 'bg-sky-50 dark:bg-sky-950/80 text-sky-700 dark:text-sky-300 border-sky-200 dark:border-sky-800/60';
  } else if (type.includes('Index')) {
    Icon = Key;
    borderColor = 'border-emerald-400 dark:border-emerald-500/50';
    badgeBg = 'bg-emerald-50 dark:bg-emerald-950/80 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/60';
  } else if (type.includes('Sort')) {
    Icon = ArrowUpDown;
    borderColor = 'border-amber-400 dark:border-amber-500/50';
    badgeBg = 'bg-amber-50 dark:bg-amber-950/80 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800/60';
  } else if (type.includes('Filter')) {
    Icon = Filter;
    borderColor = 'border-violet-400 dark:border-violet-500/50';
    badgeBg = 'bg-violet-50 dark:bg-violet-950/80 text-violet-700 dark:text-violet-300 border-violet-200 dark:border-violet-800/60';
  } else if (type.includes('Join')) {
    Icon = Share2;
    borderColor = 'border-pink-400 dark:border-pink-500/50';
    badgeBg = 'bg-pink-50 dark:bg-pink-950/80 text-pink-700 dark:text-pink-300 border-pink-200 dark:border-pink-800/60';
  }

  const hasChildren = node.children && node.children.length > 0;

  return (
    <div className="flex flex-col relative">
      {/* Node Card */}
      <div className={`flex items-start gap-3 p-3 bg-slate-50 dark:bg-slate-950/60 rounded-lg border ${borderColor} shadow-sm my-1 max-w-xl`}>
        <div className={`p-2 rounded-md bg-white dark:bg-slate-900 shrink-0 border border-slate-200 dark:border-slate-800 ${badgeBg}`}>
          <Icon className="w-4 h-4" />
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between flex-wrap gap-2 mb-1">
            <span className={`text-xs font-semibold px-2 py-0.5 rounded border font-mono ${badgeBg}`}>
              {node.node_type}
            </span>

            {/* Metrics */}
            <div className="flex items-center gap-2 text-[11px] font-mono text-slate-500 dark:text-slate-400">
              {(node.estimated_time_ms !== undefined || node.cost !== undefined) && (
                <span>Tiempo Est.: <b className="text-slate-700 dark:text-slate-200">{node.estimated_time_ms ?? node.cost} ms</b></span>
              )}
              {node.rows_estimated !== undefined && (
                <span>Filas est.: <b className="text-slate-700 dark:text-slate-200">{node.rows_estimated}</b></span>
              )}
            </div>
          </div>

          {/* Node details */}
          <div className="text-xs text-slate-600 dark:text-slate-300 space-y-0.5 mt-1 font-mono">
            {node.relation && (
              <div>Tabla: <span className="text-amber-600 dark:text-amber-300 font-semibold">{node.relation}</span></div>
            )}
            {node.method && (
              <div className="text-slate-500 dark:text-slate-400">Método de Acceso: <span className="text-sky-600 dark:text-sky-300">{node.method}</span></div>
            )}
            {node.condition && (
              <div className="text-violet-700 dark:text-violet-300 bg-violet-50 dark:bg-violet-950/30 p-1 rounded border border-violet-200 dark:border-violet-900/50">
                Condición: <code>{node.condition}</code>
              </div>
            )}
            {node.order_by && (
              <div className="text-amber-600 dark:text-amber-300">Orden: <code>{node.order_by}</code> ({node.algorithm || 'ExternalSort'})</div>
            )}
            {node.columns && (
              <div className="text-slate-500 dark:text-slate-400">Proyección: <span className="text-slate-700 dark:text-slate-200">{node.columns}</span></div>
            )}
            {node.index_name && (
              <div className="text-emerald-600 dark:text-emerald-300">Índice: {node.index_name}</div>
            )}
          </div>
        </div>
      </div>

      {/* Children branches */}
      {hasChildren && (
        <div className="pl-6 border-l-2 border-dashed border-slate-300 dark:border-slate-700/60 ml-5 my-1 space-y-2">
          {node.children.map((child, idx) => (
            <PlanNode
              key={idx}
              node={child}
              depth={depth + 1}
              isLast={idx === node.children.length - 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function PlanPanel({ plan, query, executedQuery }) {
  if (!plan) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-8 text-slate-400 dark:text-slate-500 text-xs text-center">
        <GitBranch className="w-8 h-8 stroke-1 mb-2 text-slate-300 dark:text-slate-600" />
        <p>No hay un plan de ejecución activo.</p>
        <p className="mt-1 text-slate-400 dark:text-slate-600">
          Haz clic en el botón <b>EXPLAIN</b> en el panel de consultas para visualizar el árbol de operadores.
        </p>
      </div>
    );
  }

  // Support both wrapped { root_node } or raw root node
  const root = plan.root_node || plan;
  const primerHijo = root.children && root.children[0];
  const etiquetaModo =
    primerHijo?.node_type === 'ExplainAnalyze' ? 'EXPLAIN ANALYZE'
    : primerHijo?.node_type === 'ExplainEstimate' ? 'EXPLAIN'
    : null;
  const consultaMostrada = executedQuery || query || plan.query || 'N/A';

  return (
    <div className="flex flex-col h-full bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-100 overflow-hidden">
      {/* Header */}
      <div className="p-2.5 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between bg-white/90 dark:bg-slate-900/90">
        <div className="flex items-center gap-2">
          <GitBranch className="w-4 h-4 text-violet-600 dark:text-violet-400" />
          <h2 className="font-semibold text-xs tracking-wide uppercase text-slate-600 dark:text-slate-300">
            Panel de Plan de Ejecución{etiquetaModo ? ` (${etiquetaModo})` : ''}
          </h2>
        </div>
        <div className="text-xs text-slate-500 dark:text-slate-400 font-mono">
          Estructura de Operadores de Consulta
        </div>
      </div>

      {/* Info banner */}
      <div className="px-3 py-2 bg-slate-50 dark:bg-slate-950/40 border-b border-slate-200 dark:border-slate-800/60 text-xs text-slate-500 dark:text-slate-400 flex items-center justify-between">
        <div className="flex items-center gap-1.5 truncate max-w-lg">
          <Info className="w-3.5 h-3.5 text-pg-600 dark:text-pg-400 shrink-0" />
          <span className="text-slate-400 dark:text-slate-500">Consulta:</span>
          <code className="text-slate-600 dark:text-slate-300 truncate">{consultaMostrada}</code>
        </div>
        {(root.estimated_time_ms !== undefined || root.cost !== undefined) && (
          <div className="text-[11px] font-mono bg-slate-200/70 dark:bg-slate-800/80 px-2 py-0.5 rounded text-slate-600 dark:text-slate-300 shrink-0">
            Tiempo Total Est.: <b className="text-amber-600 dark:text-amber-400">{root.estimated_time_ms ?? root.cost} ms</b>
          </div>
        )}
      </div>

      {/* Plan Visual Tree */}
      <div className="flex-1 overflow-auto p-4 bg-slate-50/60 dark:bg-slate-950/20">
        <PlanNode node={root} />
      </div>
    </div>
  );
}
