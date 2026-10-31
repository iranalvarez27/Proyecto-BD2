/**
 * Cliente de API para el Minigestor de Base de Datos
 */

/**
 * Obtener lista de tablas y metadata del catálogo
 */
export async function fetchTablesApi() {
  const res = await fetch('/api/tables');
  if (!res.ok) throw new Error('Error al conectar con la API de tablas');
  return res.json();
}

/**
 * Ejecutar una consulta SQL general en el motor
 */
export async function executeQueryApi(sql, sessionId) {
  const res = await fetch('/api/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: sql, session_id: sessionId }),
  });
  return res.json();
}

/**
 * Subir un archivo multimedia (imagen o audio) al servidor
 */
export async function uploadMediaApi(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const base64Data = reader.result;
        const res = await fetch('/api/media/upload', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            filename: file.name,
            content_base64: base64Data,
            content_type: file.type
          }),
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || 'Fallo en la subida del archivo');
        }
        const data = await res.json();
        resolve(data);
      } catch (err) {
        reject(err);
      }
    };
    reader.onerror = error => reject(error);
    reader.readAsDataURL(file);
  });
}

/**
 * Ejecutar búsqueda textual en el motor real
 */
export async function executeTextSearch({ table, column, query, method = 'BM25', k = 10, sessionId }) {
  const sql = `SELECT *, SCORE() as relevancia FROM ${table} WHERE MATCH(${column}, '${query.replace(/'/g, "''")}') USING ${method} LIMIT ${k};`;
  const result = await executeQueryApi(sql, sessionId);

  if (result.status !== 'success') {
    return {
      error: result.error || 'Error al ejecutar la búsqueda de texto en el motor.',
      tabla: table,
      columna: column,
      consulta: query,
      metodo: method,
      k,
      resultados: []
    };
  }

  // Si el motor devuelve el payload text enriquecido
  if (result.text) {
    return result.text;
  }

  // Si el motor devuelve tuplas estándar
  const cols = result.columns || [];
  const scoreIdx = cols.findIndex(c => c.toLowerCase() === 'relevancia' || c.toLowerCase() === 'score');
  const contentIdx = cols.findIndex(c => c.toLowerCase() === column.toLowerCase() || c.toLowerCase() === 'contenido' || c.toLowerCase() === 'descripcion');
  const idIdx = cols.findIndex(c => c.toLowerCase() === 'id' || c.toLowerCase() === 'codigo');

  const rows = result.rows || [];

  return {
    tabla: table,
    columna: column,
    consulta: query,
    metodo: method,
    k,
    preprocesamiento: {
      normalizado: query.toLowerCase(),
      tokens: query.toLowerCase().split(/\s+/),
      sin_stopwords: query.toLowerCase().split(/\s+/),
      terminos: query.toLowerCase().split(/\s+/)
    },
    terminos: query.split(/\s+/).map(t => ({
      termino: t.toLowerCase(),
      df: 0,
      idf: 0.0,
      en_diccionario: true,
      formas: [t]
    })),
    indice: {
      documentos: rows.length,
      terminos: 0,
      postings: 0,
      avgdl: 0.0,
      bloques_spimi: 1
    },
    metricas: {
      tiempo_ms: result.execution_time_ms || 0.0,
      paginas_leidas: 0,
      postings_evaluados: rows.length
    },
    resultados: rows.map((row, idx) => ({
      id: idIdx !== -1 ? row[idIdx] : idx + 1,
      titulo: `Registro #${idIdx !== -1 ? row[idIdx] : idx + 1}`,
      score: scoreIdx !== -1 ? Number(row[scoreIdx]) : 1.0 - idx * 0.1,
      contenido: contentIdx !== -1 ? String(row[contentIdx]) : JSON.stringify(row),
      contribuciones: {}
    }))
  };
}

/**
 * Ejecutar búsqueda vectorial multimedia (Imágenes o Audio) en el motor real
 */
export async function executeVectorSearch({ modalidad = 'imagen', table, targetFile, metric = 'cosine', index = 'HNSW', k = 6, sessionId }) {
  const sql = `SELECT *, SIMILARITY_SCORE() as score FROM ${table} WHERE SIMILAR_TO('${targetFile}', k=${k}) USING ${index} WITH METRIC=${metric};`;
  const result = await executeQueryApi(sql, sessionId);

  if (result.status !== 'success') {
    return {
      error: result.error || 'Error al ejecutar la búsqueda vectorial en el motor.',
      modalidad,
      tabla: table,
      archivo_consulta: targetFile,
      indice: index,
      metrica: metric,
      k,
      resultados: []
    };
  }

  if (result.vector) {
    return result.vector;
  }

  const cols = result.columns || [];
  const scoreIdx = cols.findIndex(c => c.toLowerCase() === 'score' || c.toLowerCase() === 'similitud');
  const idIdx = cols.findIndex(c => c.toLowerCase() === 'id' || c.toLowerCase() === 'codigo');
  const mediaIdx = cols.findIndex(c => c.toLowerCase().includes('url') || c.toLowerCase().includes('foto') || c.toLowerCase().includes('archivo'));

  const rows = result.rows || [];

  return {
    modalidad,
    tabla: table,
    archivo_consulta: targetFile,
    indice: index,
    metrica: metric,
    k,
    metricas: {
      tiempo_busqueda_ms: result.execution_time_ms || 0.0,
      distancias_calculadas: rows.length
    },
    resultados: rows.map((row, idx) => ({
      id: idIdx !== -1 ? row[idIdx] : idx + 1,
      titulo: `Item #${idIdx !== -1 ? row[idIdx] : idx + 1}`,
      score: scoreIdx !== -1 ? Number(row[scoreIdx]) : 1.0 - idx * 0.1,
      media_url: mediaIdx !== -1 ? String(row[mediaIdx]) : '',
      detalles: JSON.stringify(row),
      es_verdadero_positivo: true
    }))
  };
}
