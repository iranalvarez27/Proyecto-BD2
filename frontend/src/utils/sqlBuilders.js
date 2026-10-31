// Generadores de consultas SQL para Búsqueda Textual y Multimedia Vectorial

export function escapeSqlString(str) {
  if (typeof str !== 'string') return '';
  return str.replace(/'/g, "''");
}

/**
 * Genera una consulta SQL para búsqueda textual usando MATCH
 * Ejemplo: SELECT *, SCORE() as relevancia FROM articulos WHERE MATCH(texto, 'machine learning') USING BM25 ORDER BY relevancia DESC LIMIT 10;
 */
export function buildMatchSQL({
  table,
  column,
  query,
  method = 'BM25', // 'BM25' | 'TF_IDF'
  limit = 10,
  includeScore = true,
  scoreAlias = 'relevancia',
  orderByScore = true,
  projection = '*'
}) {
  const safeQuery = escapeSqlString(query || '');
  const proj = includeScore ? `${projection}, SCORE() as ${scoreAlias}` : projection;
  let sql = `SELECT ${proj} FROM ${table || 'documentos'} WHERE MATCH(${column || 'contenido'}, '${safeQuery}') USING ${method}`;
  if (includeScore && orderByScore) {
    sql += ` ORDER BY ${scoreAlias} DESC`;
  }
  if (limit && Number(limit) > 0) {
    sql += ` LIMIT ${Number(limit)}`;
  }
  return sql + ';';
}

/**
 * Genera una consulta SQL para búsqueda vectorial multimedia usando SIMILAR_TO
 * Ejemplo: SELECT *, SIMILARITY_SCORE() as score FROM canciones WHERE SIMILAR_TO('audio.mp3', k=5) USING IVF WITH METRIC=euclidean ORDER BY score DESC;
 */
export function buildSimilarSQL({
  table,
  targetFile,
  k = 10,
  index = 'HNSW', // 'HNSW' | 'IVF' | 'SEQ'
  metric = 'cosine', // 'cosine' | 'euclidean' | 'dot_product'
  includeScore = true,
  scoreAlias = 'similitud',
  projection = '*'
}) {
  const safeFile = escapeSqlString(targetFile || 'consulta.jpg');
  const proj = includeScore ? `${projection}, SIMILARITY_SCORE() as ${scoreAlias}` : projection;
  let sql = `SELECT ${proj} FROM ${table || 'multimedia'} WHERE SIMILAR_TO('${safeFile}', k=${Number(k)})`;
  if (index && index !== 'SEQ') {
    sql += ` USING ${index} WITH METRIC=${metric}`;
  } else {
    sql += ` WITH METRIC=${metric}`;
  }
  if (includeScore) {
    sql += ` ORDER BY ${scoreAlias} DESC`;
  }
  return sql + ';';
}
