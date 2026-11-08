export const money = (centavos, moneda = 'USD') => new Intl.NumberFormat('es-PE', {
  style: 'currency', currency: moneda,
}).format(centavos / 100);

const LABELS = { visual: 'Imagen', texto: 'Texto', metadata: 'Atributos', compras: 'Compras' };

export default function ProductCard({ producto, onSelect }) {
  const aportes = Object.entries(producto.aportes_pct || {}).filter(([, value]) => value > 0).sort((a, b) => b[1] - a[1]);
  const resumenAportes = aportes.map(([m, v]) => `${LABELS[m]} ${v.toFixed(0)}%`).join(' · ');
  return <button className="shop-card" onClick={() => onSelect(producto.id)}>
    <div className="shop-card-image">
      <img src={producto.media_url} alt={producto.nombre} loading="lazy" onError={e => { e.currentTarget.style.visibility = 'hidden'; }} />
    </div>
    <span className="shop-category">{producto.subcategoria || producto.categoria}</span>
    <span className="shop-card-title">{producto.nombre}</span>
    <strong className="shop-price">{money(producto.precio_centavos, producto.moneda)}</strong>
    {aportes.length > 0 && <>
      <span className="shop-contributions" title={resumenAportes} aria-label={resumenAportes}>
        {aportes.map(([m, v]) => <span key={m} className={`shop-signal-${m}`} style={{ width: `${v}%` }} />)}
      </span>
      <span className="shop-reason" title={resumenAportes}>{aportes.slice(0, 2).map(([m, v]) => `${LABELS[m]} ${v.toFixed(0)}%`).join(' + ')}</span>
    </>}
  </button>;
}
