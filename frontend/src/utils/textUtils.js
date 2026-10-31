/**
 * Normaliza una palabra quitando tildes y diacríticos
 */
export function normalizarTexto(texto) {
  if (!texto) return '';
  return texto
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '');
}

/**
 * Extrae un snippet relevante alrededor del primer término encontrado
 */
export function extractSnippet(text, terms = [], maxLen = 160) {
  if (!text) return '';
  if (text.length <= maxLen) return text;

  const termsNorm = terms.map(t => normalizarTexto(t).trim()).filter(t => t.length > 1);
  if (termsNorm.length === 0) {
    return text.slice(0, maxLen) + '...';
  }

  const lower = normalizarTexto(text);
  let firstIdx = -1;

  for (const term of termsNorm) {
    const idx = lower.indexOf(term);
    if (idx !== -1 && (firstIdx === -1 || idx < firstIdx)) {
      firstIdx = idx;
    }
  }

  if (firstIdx === -1) {
    return text.slice(0, maxLen) + '...';
  }

  const start = Math.max(0, firstIdx - Math.floor(maxLen / 3));
  const end = Math.min(text.length, start + maxLen);
  let snippet = text.slice(start, end);

  if (start > 0) snippet = '...' + snippet;
  if (end < text.length) snippet = snippet + '...';

  return snippet;
}
