import React, { useMemo, useRef, useState } from 'react';
import { Upload, X, AlertTriangle, Table2, FilePlus2, CheckCircle2 } from 'lucide-react';
import { parseCsv, toIdent, inferColumnType, buildImportScript } from '../utils/csvImport';

const TIPOS_DISPONIBLES = ['INT', 'SMALLINT', 'BIGINT', 'FLOAT', 'DOUBLE', 'BOOL', 'VARCHAR', 'CHAR'];

export default function CsvImportModal({ tables = [], onClose, onUseScript }) {
  const fileInputRef = useRef(null);
  const [fileName, setFileName] = useState('');
  const [headers, setHeaders] = useState([]);
  const [rows, setRows] = useState([]);
  const [parseError, setParseError] = useState('');

  // 'new' = CREATE TABLE nueva a partir del CSV; 'existing' = INSERT en una tabla ya registrada
  const [mode, setMode] = useState('new');
  const [existingTable, setExistingTable] = useState('');

  // Config para tabla nueva
  const [newTableName, setNewTableName] = useState('');
  const [newStorage, setNewStorage] = useState('heap');
  const [newColumns, setNewColumns] = useState([]); // [{name, type, size, isPk}]

  // Config para tabla existente: por cada columna de la tabla, que columna del CSV la alimenta
  const [existingMapping, setExistingMapping] = useState({}); // { colNombreTabla: csvHeaderIndex }

  const handleFile = (file) => {
    setParseError('');
    setFileName(file.name);
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const { headers: h, rows: r } = parseCsv(String(reader.result));
        if (h.length === 0) {
          setParseError('El archivo no tiene encabezados o está vacío.');
          return;
        }
        setHeaders(h);
        setRows(r);

        // Config por defecto para "tabla nueva": infiere tipos de todas las columnas
        const base = toIdent(file.name.replace(/\.csv$/i, ''), 'importado');
        setNewTableName(base);
        const inferred = h.map((head, i) => {
          const values = r.map(row => row[i]);
          const { type, size } = inferColumnType(values);
          return { name: toIdent(head, `col${i + 1}`), type, size, isPk: false };
        });
        // si hay una columna llamada 'id' y es INT, se marca como PK por defecto (patrón típico)
        const idIdx = inferred.findIndex(c => c.name === 'id' && c.type === 'INT');
        if (idIdx >= 0) inferred[idIdx].isPk = true;
        setNewColumns(inferred);

        // Config por defecto para "tabla existente": intenta emparejar por nombre
        if (tables.length > 0) {
          const t = tables[0];
          setExistingTable(t.name);
          setExistingMapping(defaultMapping(t, h));
        }
      } catch (err) {
        setParseError('No se pudo leer el CSV: ' + err.message);
      }
    };
    reader.onerror = () => setParseError('No se pudo leer el archivo.');
    reader.readAsText(file);
  };

  const defaultMapping = (table, csvHeaders) => {
    const mapping = {};
    for (const col of table.columns) {
      const norm = col.name.toLowerCase().replace(/[^a-z0-9]/g, '');
      const idx = csvHeaders.findIndex(h => h.toLowerCase().replace(/[^a-z0-9]/g, '') === norm);
      mapping[col.name] = idx >= 0 ? idx : null;
    }
    return mapping;
  };

  const selectedExistingTable = useMemo(
    () => tables.find(t => t.name === existingTable) || null,
    [tables, existingTable]
  );

  const handleExistingTableChange = (name) => {
    setExistingTable(name);
    const t = tables.find(x => x.name === name);
    if (t) setExistingMapping(defaultMapping(t, headers));
  };

  const updateNewColumn = (idx, patch) => {
    setNewColumns(prev => prev.map((c, i) => (i === idx ? { ...c, ...patch } : c)));
  };

  const setPk = (idx) => {
    setNewColumns(prev => prev.map((c, i) => ({ ...c, isPk: i === idx })));
  };

  // ---- validación + generación del script ----
  const { script, warnings, errors, rowCount } = useMemo(() => {
    if (headers.length === 0) return { script: '', warnings: [], errors: [], rowCount: 0 };

    if (mode === 'new') {
      const errs = [];
      if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(newTableName)) {
        errs.push("El nombre de la tabla debe empezar con letra/guion bajo y solo tener letras, números o '_'.");
      }
      if (!newColumns.some(c => c.isPk)) {
        errs.push('Debes marcar exactamente una columna como PRIMARY KEY.');
      }
      const names = new Set();
      for (const c of newColumns) {
        if (names.has(c.name)) errs.push(`La columna '${c.name}' está repetida.`);
        names.add(c.name);
        if ((c.type === 'VARCHAR' || c.type === 'CHAR') && (!c.size || c.size <= 0)) {
          errs.push(`La columna '${c.name}' (${c.type}) necesita un tamaño mayor a 0.`);
        }
      }
      if (errs.length > 0) return { script: '', warnings: [], errors: errs, rowCount: rows.length };

      const columnSourceIndex = newColumns.map((_, i) => i); // 1 a 1 con el CSV
      const { script: sql, warnings: warn } = buildImportScript({
        tableName: newTableName,
        columns: newColumns,
        rows,
        columnSourceIndex,
        createNew: true,
        storage: newStorage,
      });
      return { script: sql, warnings: warn, errors: [], rowCount: rows.length };
    }

    // mode === 'existing'
    if (!selectedExistingTable) {
      return { script: '', warnings: [], errors: ['Selecciona una tabla destino.'], rowCount: rows.length };
    }
    const errs = [];
    const columns = selectedExistingTable.columns.map(c => ({
      name: c.name,
      type: c.type,
      size: c.size,
      isPk: c.is_pk,
    }));
    const columnSourceIndex = columns.map(c => {
      const idx = existingMapping[c.name];
      if (idx === null || idx === undefined) {
        errs.push(`La columna '${c.name}' de la tabla no tiene ninguna columna del CSV asignada.`);
        return null;
      }
      return idx;
    });
    if (errs.length > 0) return { script: '', warnings: [], errors: errs, rowCount: rows.length };

    const { script: sql, warnings: warn } = buildImportScript({
      tableName: selectedExistingTable.name,
      columns,
      rows,
      columnSourceIndex,
      createNew: false,
      storage: null,
    });
    return { script: sql, warnings: warn, errors: [], rowCount: rows.length };
  }, [mode, headers, rows, newTableName, newStorage, newColumns, existingMapping, selectedExistingTable]);

  const previewLines = script ? script.split('\n').slice(0, 6) : [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 dark:bg-black/60 p-4">
      <div className="w-full max-w-3xl max-h-[90vh] bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-2 text-slate-700 dark:text-slate-200 font-semibold text-sm">
            <Upload className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            Importar datos desde CSV
          </div>
          <button onClick={onClose} className="p-1 hover:bg-slate-100 dark:hover:bg-slate-800 rounded text-slate-400 hover:text-slate-800 dark:hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4 text-sm">
          {/* Paso 1: archivo */}
          <div>
            <label className="flex items-center gap-2 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1.5">
              1. Selecciona el archivo .csv
            </label>
            <div className="flex items-center gap-2">
              <button
                onClick={() => fileInputRef.current?.click()}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 border border-slate-300 dark:border-slate-700 rounded text-slate-700 dark:text-slate-200 text-xs"
              >
                <Upload className="w-3.5 h-3.5" />
                Elegir archivo
              </button>
              <span className="text-slate-400 dark:text-slate-500 text-xs truncate">{fileName || 'Ningún archivo seleccionado'}</span>
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                onChange={e => e.target.files?.[0] && handleFile(e.target.files[0])}
              />
            </div>
            {parseError && (
              <p className="mt-2 text-rose-600 dark:text-rose-400 text-xs flex items-center gap-1">
                <AlertTriangle className="w-3.5 h-3.5" /> {parseError}
              </p>
            )}
          </div>

          {headers.length > 0 && (
            <>
              <div className="text-xs text-slate-500 dark:text-slate-500">
                Detectadas <b className="text-slate-700 dark:text-slate-300">{headers.length}</b> columnas y{' '}
                <b className="text-slate-700 dark:text-slate-300">{rows.length}</b> filas de datos.
                {rows.length > 500 && ' Con este tamaño la importación puede tardar un poco (una petición por fila).'}
              </div>

              {/* Paso 2: destino */}
              <div>
                <label className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1.5 block">
                  2. Destino de los datos
                </label>
                <div className="flex gap-2 mb-3">
                  <button
                    onClick={() => setMode('new')}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs border transition ${
                      mode === 'new'
                        ? 'bg-emerald-50 dark:bg-emerald-600/20 border-emerald-400 dark:border-emerald-500/50 text-emerald-700 dark:text-emerald-200'
                        : 'bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200'
                    }`}
                  >
                    <FilePlus2 className="w-3.5 h-3.5" />
                    Crear tabla nueva
                  </button>
                  <button
                    onClick={() => setMode('existing')}
                    disabled={tables.length === 0}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs border transition disabled:opacity-40 ${
                      mode === 'existing'
                        ? 'bg-pg-50 dark:bg-pg-600/20 border-pg-400 dark:border-pg-500/50 text-pg-700 dark:text-pg-200'
                        : 'bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200'
                    }`}
                  >
                    <Table2 className="w-3.5 h-3.5" />
                    Insertar en tabla existente
                  </button>
                </div>

                {mode === 'new' && (
                  <div className="space-y-3 bg-slate-50 dark:bg-slate-950/40 border border-slate-200 dark:border-slate-800 rounded p-3">
                    <div className="flex items-center gap-3 flex-wrap">
                      <label className="text-xs text-slate-500 dark:text-slate-400">
                        Nombre de tabla:
                        <input
                          value={newTableName}
                          onChange={e => setNewTableName(toIdent(e.target.value, 'tabla'))}
                          className="ml-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded px-2 py-1 text-slate-700 dark:text-slate-200 text-xs w-48"
                        />
                      </label>
                      <label className="text-xs text-slate-500 dark:text-slate-400">
                        Storage:
                        <select
                          value={newStorage}
                          onChange={e => setNewStorage(e.target.value)}
                          className="ml-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded px-2 py-1 text-slate-700 dark:text-slate-200 text-xs"
                        >
                          <option value="heap">HEAP</option>
                          <option value="sequential">SEQUENTIAL</option>
                        </select>
                      </label>
                    </div>

                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-slate-500 dark:text-slate-500 text-left">
                          <th className="pb-1 pr-2">Columna CSV</th>
                          <th className="pb-1 pr-2">Nombre en tabla</th>
                          <th className="pb-1 pr-2">Tipo</th>
                          <th className="pb-1 pr-2">Tamaño</th>
                          <th className="pb-1">PK</th>
                        </tr>
                      </thead>
                      <tbody>
                        {headers.map((h, i) => {
                          const col = newColumns[i];
                          if (!col) return null;
                          return (
                            <tr key={i} className="border-t border-slate-200 dark:border-slate-800/60">
                              <td className="py-1 pr-2 text-slate-500 dark:text-slate-400 truncate max-w-[100px]" title={h}>
                                {h}
                              </td>
                              <td className="py-1 pr-2">
                                <input
                                  value={col.name}
                                  onChange={e => updateNewColumn(i, { name: toIdent(e.target.value, `col${i + 1}`) })}
                                  className="bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded px-1.5 py-0.5 text-slate-700 dark:text-slate-200 w-28"
                                />
                              </td>
                              <td className="py-1 pr-2">
                                <select
                                  value={col.type}
                                  onChange={e => updateNewColumn(i, { type: e.target.value })}
                                  className="bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded px-1.5 py-0.5 text-slate-700 dark:text-slate-200"
                                >
                                  {TIPOS_DISPONIBLES.map(t => (
                                    <option key={t} value={t}>{t}</option>
                                  ))}
                                </select>
                              </td>
                              <td className="py-1 pr-2">
                                {(col.type === 'VARCHAR' || col.type === 'CHAR') ? (
                                  <input
                                    type="number"
                                    min={1}
                                    value={col.size}
                                    onChange={e => updateNewColumn(i, { size: parseInt(e.target.value, 10) || 1 })}
                                    className="bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded px-1.5 py-0.5 text-slate-700 dark:text-slate-200 w-16"
                                  />
                                ) : (
                                  <span className="text-slate-300 dark:text-slate-600">—</span>
                                )}
                              </td>
                              <td className="py-1">
                                <input
                                  type="radio"
                                  name="pk-col"
                                  checked={col.isPk}
                                  onChange={() => setPk(i)}
                                />
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}

                {mode === 'existing' && (
                  <div className="space-y-3 bg-slate-50 dark:bg-slate-950/40 border border-slate-200 dark:border-slate-800 rounded p-3">
                    <label className="text-xs text-slate-500 dark:text-slate-400 block">
                      Tabla destino:
                      <select
                        value={existingTable}
                        onChange={e => handleExistingTableChange(e.target.value)}
                        className="ml-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded px-2 py-1 text-slate-700 dark:text-slate-200 text-xs"
                      >
                        {tables.map(t => (
                          <option key={t.name} value={t.name}>{t.name}</option>
                        ))}
                      </select>
                    </label>

                    {selectedExistingTable && (
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="text-slate-500 dark:text-slate-500 text-left">
                            <th className="pb-1 pr-2">Columna de la tabla</th>
                            <th className="pb-1 pr-2">Tipo</th>
                            <th className="pb-1">Columna del CSV</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selectedExistingTable.columns.map(col => (
                            <tr key={col.name} className="border-t border-slate-200 dark:border-slate-800/60">
                              <td className="py-1 pr-2 text-slate-600 dark:text-slate-300">
                                {col.name} {col.is_pk && <span className="text-amber-600 dark:text-amber-400">(PK)</span>}
                              </td>
                              <td className="py-1 pr-2 text-slate-400 dark:text-slate-500">{col.type}</td>
                              <td className="py-1">
                                <select
                                  value={existingMapping[col.name] ?? ''}
                                  onChange={e =>
                                    setExistingMapping(prev => ({
                                      ...prev,
                                      [col.name]: e.target.value === '' ? null : parseInt(e.target.value, 10),
                                    }))
                                  }
                                  className={`bg-white dark:bg-slate-800 border rounded px-1.5 py-0.5 text-slate-700 dark:text-slate-200 ${
                                    existingMapping[col.name] == null ? 'border-rose-400 dark:border-rose-600' : 'border-slate-300 dark:border-slate-700'
                                  }`}
                                >
                                  <option value="">— sin asignar —</option>
                                  {headers.map((h, i) => (
                                    <option key={i} value={i}>{h}</option>
                                  ))}
                                </select>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                )}
              </div>

              {/* Errores / warnings */}
              {errors.length > 0 && (
                <div className="bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800/60 rounded p-2.5 text-rose-700 dark:text-rose-300 text-xs space-y-1">
                  {errors.map((e, i) => (
                    <div key={i} className="flex items-start gap-1.5">
                      <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" /> {e}
                    </div>
                  ))}
                </div>
              )}
              {warnings.length > 0 && (
                <div className="bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800/50 rounded p-2.5 text-amber-700 dark:text-amber-300 text-xs space-y-1">
                  {warnings.map((w, i) => (
                    <div key={i} className="flex items-start gap-1.5">
                      <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" /> {w}
                    </div>
                  ))}
                </div>
              )}

              {/* Paso 3: preview */}
              {script && (
                <div>
                  <label className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1.5 block">
                    3. Vista previa del SQL generado ({rowCount} INSERT{rowCount !== 1 ? 's' : ''})
                  </label>
                  <pre className="bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded p-2.5 text-[11px] text-emerald-700 dark:text-emerald-300 font-mono overflow-x-auto max-h-40">
{previewLines.join('\n')}
{script.split('\n').length > previewLines.length ? `\n... (${script.split('\n').length - previewLines.length} línea(s) más)` : ''}
                  </pre>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-4 py-3 border-t border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/40">
          <p className="text-[11px] text-slate-400 dark:text-slate-500">
            Esto solo carga el script en el editor: nada se ejecuta hasta que presiones <b>Ejecutar</b>.
          </p>
          <div className="flex gap-2">
            <button onClick={onClose} className="px-3 py-1.5 text-xs text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200 rounded">
              Cancelar
            </button>
            <button
              onClick={() => script && onUseScript(script)}
              disabled={!script || errors.length > 0}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded text-xs font-semibold"
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              Cargar en el editor
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
