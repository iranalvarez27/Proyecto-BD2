export function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let inQuotes = false;
  let i = 0;
  const n = text.length;

  while (i < n) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 2;
          continue;
        }
        inQuotes = false;
        i++;
        continue;
      }
      field += c;
      i++;
      continue;
    }
    if (c === '"') {
      inQuotes = true;
      i++;
      continue;
    }
    if (c === ',') {
      row.push(field);
      field = '';
      i++;
      continue;
    }
    if (c === '\r') {
      i++;
      continue;
    }
    if (c === '\n') {
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
      i++;
      continue;
    }
    field += c;
    i++;
  }

  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }

  const clean = rows.filter(r => !(r.length === 1 && r[0].trim() === ''));
  if (clean.length === 0) return { headers: [], rows: [] };

  const headers = clean[0].map(h => h.trim());
  const dataRows = clean.slice(1);
  return { headers, rows: dataRows };
}

export function toIdent(name, fallback = 'col') {
  let s = String(name || '').trim().replace(/[^a-zA-Z0-9_]/g, '_');
  if (!s) s = fallback;
  if (/^[0-9]/.test(s)) s = '_' + s;
  return s.toLowerCase();
}

export function inferColumnType(values) {
  let allInt = true;
  let allFloat = true;
  let maxLen = 0;
  let sawEmpty = false;

  for (const raw of values) {
    const v = (raw ?? '').trim();
    maxLen = Math.max(maxLen, v.length);
    if (v === '') {
      sawEmpty = true;
      allInt = false;
      allFloat = false;
      continue;
    }
    if (!/^-?\d+$/.test(v)) allInt = false;
    if (!/^-?\d+(\.\d+)?$/.test(v)) allFloat = false;
  }

  if (allInt) return { type: 'INT', size: 4, sawEmpty };
  if (allFloat) return { type: 'FLOAT', size: 4, sawEmpty };
  const size = Math.max(10, Math.min(500, maxLen + 10));
  return { type: 'VARCHAR', size, sawEmpty };
}

export function sanitizeSqlText(raw, warnings) {
  let v = String(raw ?? '').trim();
  if (v.includes("'")) {
    v = v.replace(/'/g, '’');
    warnings.add(
      "Se reemplazaron comillas simples (') por (’) en algunos valores: el parser SQL de este " +
      'proyecto no soporta escaparlas dentro de un texto.'
    );
  }
  if (v.includes(';')) {
    v = v.replace(/;/g, ',');
    warnings.add(
      'Se reemplazaron punto y coma (;) por comas en algunos valores: el editor separa las ' +
      "sentencias de un script por ';'."
    );
  }
  return v;
}

function valueToSql(raw, colType, warnings) {
  const v = sanitizeSqlText(raw, warnings);
  if (colType === 'INT' || colType === 'SMALLINT' || colType === 'BIGINT') {
    const n = parseInt(v, 10);
    return Number.isFinite(n) ? String(n) : '0';
  }
  if (colType === 'FLOAT' || colType === 'DOUBLE') {
    const f = parseFloat(v);
    if (!Number.isFinite(f)) return '0.0';
    // el lexer distingue INT de FLOAT solo por la presencia de un punto
    return Number.isInteger(f) ? `${f}.0` : String(f);
  }
  return `'${v.replace(/'/g, "''")}'`;
}

export function buildImportScript({ tableName, columns, rows, columnSourceIndex, createNew, storage }) {
  const warnings = new Set();
  const lines = [];

  if (createNew) {
    const colDefs = columns
      .map(c => {
        const tipo = c.type === 'VARCHAR' || c.type === 'CHAR' ? `${c.type}(${c.size})` : c.type;
        return `${c.name} ${tipo}${c.isPk ? ' PRIMARY KEY' : ''}`;
      })
      .join(', ');
    const usingClause = storage === 'sequential' ? ' USING SEQUENTIAL' : '';
    lines.push(`CREATE TABLE ${tableName} (${colDefs})${usingClause};`);
  }

  for (const row of rows) {
    const vals = columns.map((c, i) => {
      const srcIdx = columnSourceIndex[i];
      const raw = srcIdx == null ? '' : row[srcIdx] ?? '';
      return valueToSql(raw, c.type, warnings);
    });
    lines.push(`INSERT INTO ${tableName} VALUES (${vals.join(', ')});`);
  }

  return { script: lines.join('\n'), warnings: Array.from(warnings) };
}
