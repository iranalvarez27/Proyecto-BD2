import React from 'react';
import { normalizarTexto } from './textUtils';

/**
 * Resalta las ocurrencias de los términos en un texto dado.
 */
export default function HighlightedText({ text, terms = [] }) {
  if (!text || !terms || terms.length === 0) {
    return <span>{text}</span>;
  }

  const termsNorm = terms
    .map(t => normalizarTexto(t).trim())
    .filter(t => t.length > 1);

  if (termsNorm.length === 0) {
    return <span>{text}</span>;
  }

  // Dividir texto por palabras manteniendo delimitadores
  const tokens = text.split(/(\s+|[.,;!?()[\]{}"':]+)/);

  return (
    <span>
      {tokens.map((token, i) => {
        const normToken = normalizarTexto(token);
        const match = termsNorm.some(term => normToken.includes(term) || term.includes(normToken));
        if (match && normToken.length > 2) {
          return (
            <mark
              key={i}
              className="bg-amber-200 dark:bg-amber-500/30 text-amber-900 dark:text-amber-200 font-semibold px-0.5 rounded"
            >
              {token}
            </mark>
          );
        }
        return <span key={i}>{token}</span>;
      })}
    </span>
  );
}

export { HighlightedText };
