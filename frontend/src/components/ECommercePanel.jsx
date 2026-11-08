import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ShoppingBag, ShoppingCart, Search, SlidersHorizontal, X, MapPin } from 'lucide-react';
import { fetchEcommerceStatus, fetchEcommerceCatalog, fetchEcommerceProduct, fetchEcommerceRecommendations,
  recordEcommerceInteraction, purchaseEcommerceCart } from '../utils/api';
import ProductCard, { money } from './ecommerce/ProductCard';
import StoreMap from './ecommerce/StoreMap';
import './ecommerce/shop.css';

const LOCATIONS = [
  ['Miraflores', -12.1211, -77.0297], ['San Isidro', -12.0977, -77.0365],
  ['Centro de Lima', -12.0464, -77.0428], ['Surco', -12.1450, -76.9917], ['Los Olivos', -11.9920, -77.0708],
];
const INITIAL = { pesos: { visual: .3, texto: .3, metadata: .2, compras: .2 }, metodo: 'HNSW', metrica: 'cosine', texto: 'BM25', solo_stock: false };
const LABELS = { visual: 'Imagen', texto: 'Descripción', metadata: 'Categoría y precio', compras: 'Compras compartidas' };

function usuarioDemo() {
  const key = 'bd2_ecommerce_usuario';
  try {
    const actual = Number(localStorage.getItem(key));
    if (Number.isInteger(actual) && actual > 200 && actual < 2147483647) return actual;
    const id = 1000 + Math.floor(Math.random() * 1000000000);
    localStorage.setItem(key, String(id));
    return id;
  } catch { return 1001; }
}

export default function ECommercePanel({ onUseSQL }) {
  const [status, setStatus] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [filters, setFilters] = useState({ category: '', search: '' });
  const [draftSearch, setDraftSearch] = useState('');
  const [cursor, setCursor] = useState('');
  const [selected, setSelected] = useState(null);
  const [product, setProduct] = useState(null);
  const [recommendation, setRecommendation] = useState(null);
  const [settings, setSettings] = useState(INITIAL);
  const [draftSettings, setDraftSettings] = useState(INITIAL);
  const [location, setLocation] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingCatalog, setLoadingCatalog] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [cart, setCart] = useState([]);
  const [cartOpen, setCartOpen] = useState(false);
  const [store, setStore] = useState('');
  const [buying, setBuying] = useState(false);
  const [revision, setRevision] = useState(0);
  const [user] = useState(usuarioDemo);
  const purchaseKey = useRef(null);
  const position = LOCATIONS[location].slice(1);

  useEffect(() => {
    const controller = new AbortController();
    fetchEcommerceStatus(controller.signal).then(setStatus).catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!status?.listo) return;
    const controller = new AbortController();
    setLoadingCatalog(true);
    setError('');
    const params = { ...filters, limit: 24 };
    if (cursor) params[filters.search ? 'cursor' : 'after_id'] = cursor;
    fetchEcommerceCatalog(params, controller.signal).then(data => {
      setCatalog(previous => ({ ...data, productos: cursor ? [...(previous?.productos || []), ...data.productos] : data.productos }));
    }).catch(e => { if (e.name !== 'AbortError') setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoadingCatalog(false); });
    return () => controller.abort();
  }, [filters, cursor, status]);

  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    setLoading(true);
    setError('');
    setProduct(null);
    setRecommendation(null);
    Promise.all([
      fetchEcommerceProduct(selected, controller.signal),
      fetchEcommerceRecommendations({ product_id: selected, k: 10, ...settings,
        lat: LOCATIONS[location][1], lon: LOCATIONS[location][2] }, controller.signal),
    ]).then(([detail, rec]) => {
      setProduct(detail);
      setRecommendation(rec);
      setStore(String(rec.producto_base.tiendas[0]?.id || ''));
    }).catch(e => { if (e.name !== 'AbortError') setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [selected, settings, location, revision]);

  function selectProduct(id) {
    setSelected(id);
    setMessage('');
    recordEcommerceInteraction({ usuario_id: user, producto_id: id, tipo: 'vista' }).catch(e => setError(e.message));
  }

  function addToCart() {
    const tienda = recommendation.producto_base.tiendas.find(t => t.id === Number(store));
    if (!tienda || buying) return;
    const existente = cart.find(p => p.id === product.id && p.tienda_id === tienda.id);
    if ((existente?.cantidad || 0) >= tienda.stock) { setError('Se alcanzó el stock disponible en esa sucursal'); return; }
    purchaseKey.current = null;
    setCart(old => existente ? old.map(p => p === existente ? { ...p, cantidad: p.cantidad + 1 } : p)
      : [...old, { ...product, tienda_id: tienda.id, tienda_nombre: tienda.nombre, cantidad: 1 }]);
    setMessage('Producto añadido al carrito');
    recordEcommerceInteraction({ usuario_id: user, producto_id: product.id, tipo: 'carrito' }).catch(e => setError(e.message));
  }

  async function buy() {
    if (!cart.length || buying) return;
    setBuying(true); setError('');
    purchaseKey.current ||= crypto.randomUUID();
    try {
      const result = await purchaseEcommerceCart({ usuario_id: user, solicitud: purchaseKey.current,
        items: cart.map(p => ({ producto_id: p.id, tienda_id: p.tienda_id, cantidad: p.cantidad })) });
      setCart([]); purchaseKey.current = null;
      setMessage(`Compra de demostración registrada por ${money(result.total_centavos)}. Inventario y recomendaciones actualizados.`);
      setRevision(r => r + 1);
    } catch (e) { setError(e.message); }
    finally { setBuying(false); }
  }

  return <div className="shop" aria-label="Tienda de recomendaciones">
    <header className="shop-header">
      <div className="shop-brand"><ShoppingBag size={23} /><div><strong>Tecno Lima</strong><span>Encuentra tu próxima conexión</span></div></div>
      <label className="shop-location"><MapPin size={16} /><select aria-label="Tu ubicación" value={location} onChange={e => setLocation(Number(e.target.value))}>
        {LOCATIONS.map(([name], i) => <option key={name} value={i}>{name}</option>)}
      </select></label>
      <button className="shop-button" onClick={() => setCartOpen(v => !v)}><ShoppingCart size={17} /> Carrito ({cart.reduce((n, p) => n + p.cantidad, 0)})</button>
    </header>
    <div className="shop-notice">Catálogo Amazon · Precios del dataset en USD · Sucursales, stock y compras de demostración simulados</div>
    {error && <div className="shop-error" role="alert">{error}<button aria-label="Cerrar error" onClick={() => setError('')}><X size={16} /></button></div>}
    {message && <div className="shop-success" role="status">{message}</div>}
    {!status && !error && <p className="shop-empty" role="status">Conectando con el catálogo…</p>}
    {status && !status.listo && <div className="shop-empty"><h2>El catálogo está pendiente de preparación</h2><p>Ejecuta la preparación de e-commerce y reinicia el backend.</p><code>python3 -m recomendacion.preparar --size 1000</code></div>}
    {cartOpen && <section className="shop-cart">
      <h2>Tu carrito</h2>
      {!cart.length && <p>Selecciona un producto y una sucursal para añadirlo.</p>}
      {cart.map(p => <div className="shop-cart-line" key={`${p.id}-${p.tienda_id}`}>
        <img src={p.media_url} alt="" /><div><strong>{p.nombre}</strong><small>{p.tienda_nombre} · Cantidad {p.cantidad}</small></div>
        <span>{money(p.precio_centavos * p.cantidad)}</span><button aria-label={`Quitar ${p.nombre}`} disabled={buying} onClick={() => { purchaseKey.current = null; setCart(old => old.filter(item => item !== p)); }}><X size={17} /></button>
      </div>)}
      {!!cart.length && <div className="shop-cart-total"><strong>Total {money(cart.reduce((sum, p) => sum + p.precio_centavos * p.cantidad, 0))}</strong><button className="shop-primary" disabled={buying} onClick={buy}>{buying ? 'Registrando compra…' : 'Confirmar compra de demostración'}</button></div>}
    </section>}
    {status?.listo && !selected && <>
      <div className="shop-intro"><div><p className="shop-eyebrow">TECNOLOGÍA PARA TU DÍA A DÍA</p><h1>Descubre algo que va contigo.</h1><p>Explora productos y encuentra alternativas por imagen, descripción y compras compartidas.</p></div><span className="shop-count">{status.productos.toLocaleString()} productos</span></div>
      <form className="shop-search" onSubmit={e => { e.preventDefault(); setCursor(''); setFilters(f => ({ ...f, search: draftSearch })); }}>
        <div><Search size={18} /><input aria-label="Buscar productos" value={draftSearch} onChange={e => setDraftSearch(e.target.value)} placeholder="Busca por nombre o descripción" /></div>
        <select aria-label="Categoría" value={filters.category} onChange={e => { setCursor(''); setFilters(f => ({ ...f, category: e.target.value })); }}><option value="">Todas las categorías</option>{catalog?.categorias.map(c => <option key={c}>{c}</option>)}</select>
        <button className="shop-primary" type="submit">Buscar</button>
      </form>
      <div className="shop-grid" aria-busy={loadingCatalog}>{catalog?.productos.map(p => <ProductCard key={p.id} producto={p} onSelect={selectProduct} />)}</div>
      {loadingCatalog && <p className="shop-empty" role="status">Cargando productos…</p>}
      {!loadingCatalog && catalog?.productos.length === 0 && <p className="shop-empty">No hay productos con estos filtros.</p>}
      {catalog?.busqueda_acotada && <p className="shop-empty">Mostrando los primeros 500 resultados. Puedes precisar la búsqueda.</p>}
      {catalog?.next_cursor && <button className="shop-more shop-button" disabled={loadingCatalog} onClick={() => setCursor(catalog.next_cursor)}>Mostrar más productos</button>}
    </>}
    {selected && <>
      <button className="shop-back" onClick={() => setSelected(null)}><ArrowLeft size={16} /> Volver al catálogo</button>
      {loading && <p className="shop-empty" role="status">Buscando productos relacionados y disponibilidad…</p>}
      {product && recommendation && <>
        <section className="shop-detail">
          <div className="shop-detail-image"><img src={product.media_url} alt={product.nombre} /></div>
          <div className="shop-detail-copy"><p className="shop-category">{product.subcategoria}</p><h1>{product.nombre}</h1>
            <div className="shop-detail-price">{money(product.precio_centavos, product.moneda)}</div>
            {!!product.rating && <p className="shop-muted">Valoración del dataset {product.rating.toFixed(1)} / 5</p>}
            <details><summary>Descripción y características</summary><p className="shop-description">{product.descripcion}</p></details>
            {recommendation.producto_base.tiendas.length ? <>
              <label className="shop-stock">Recoger en una sucursal<select value={store} onChange={e => setStore(e.target.value)}>{recommendation.producto_base.tiendas.map(t => <option value={t.id} key={t.id}>{t.nombre} · {(t.dist_m / 1000).toFixed(1)} km · {t.stock} disponibles</option>)}</select></label>
              <button className="shop-primary" disabled={!store || buying} onClick={addToCart}><ShoppingCart size={17} /> Añadir al carrito</button>
            </> : <p className="shop-muted">Sin stock en las sucursales de demostración.</p>}
          </div>
        </section>
        <details className="shop-controls"><summary><SlidersHorizontal size={17} /> Ajustar recomendaciones</summary><form onSubmit={e => { e.preventDefault(); setSettings({ ...draftSettings }); }}>
          <div className="shop-sliders">{Object.entries(draftSettings.pesos).map(([m, value]) => <label key={m}>{LABELS[m]}<output>{Math.round(value * 100)}</output><input type="range" min="0" max="1" step="0.05" value={value} onChange={e => setDraftSettings(s => ({ ...s, pesos: { ...s.pesos, [m]: Number(e.target.value) } }))} /></label>)}</div>
          <div className="shop-selectors"><label>Índice visual<select value={draftSettings.metodo} onChange={e => setDraftSettings(s => ({ ...s, metodo: e.target.value }))}>{['HNSW', 'IVF', 'EXACT'].map(v => <option key={v}>{v}</option>)}</select></label>
            <label>Métrica<select value={draftSettings.metrica} onChange={e => setDraftSettings(s => ({ ...s, metrica: e.target.value }))}><option value="cosine">Coseno</option><option value="euclidean">Euclidiana</option><option value="dot">Producto punto</option></select></label>
            <label>Texto<select value={draftSettings.texto} onChange={e => setDraftSettings(s => ({ ...s, texto: e.target.value }))}><option>BM25</option><option>TF_IDF</option></select></label>
            <label className="shop-check"><input type="checkbox" checked={draftSettings.solo_stock} onChange={e => setDraftSettings(s => ({ ...s, solo_stock: e.target.checked }))} /> Solo con stock</label>
            <button className="shop-primary" disabled={Object.values(draftSettings.pesos).every(v => v === 0)}>Aplicar</button>
          </div>
        </form></details>
        <div className="shop-section-title"><h2>También puede interesarte</h2><span>{recommendation.tiempo_total_ms.toFixed(0)} ms</span></div>
        <div className="shop-legend">{Object.entries(LABELS).map(([m, label]) => <span key={m}><i className={`shop-signal-${m}`} />{label}</span>)}</div>
        {Object.entries(recommendation.errores_modalidades).map(([m, detail]) => <p className="shop-error" key={m}>{LABELS[m]} no disponible. {detail}</p>)}
        <div className="shop-grid">{recommendation.recomendaciones.map(p => <ProductCard key={p.id} producto={p} onSelect={selectProduct} />)}</div>
        {!recommendation.recomendaciones.length && <p className="shop-empty">No hay recomendaciones con esta configuración.</p>}
        <section className="shop-stores"><h2>Sucursales con disponibilidad</h2><StoreMap tiendas={recommendation.producto_base.tiendas} ubicacion={position} /></section>
        <details className="shop-traces"><summary>Consultas y planes de ejecución</summary>
          <p>Las barras muestran la contribución de cada estrategia al ranking.</p>
          <div className="shop-modalities">{Object.entries(recommendation.modalidades).map(([m, state]) => <span key={m}>{LABELS[m]} · {state.replaceAll('_', ' ')}</span>)}</div>
          {recommendation.trazas.map((t, i) => <article key={i}><pre>{t.sql}</pre><p>{t.plan.join(' → ')}</p><span>{t.tiempo_ms.toFixed(2)} ms</span><button className="shop-button" onClick={() => onUseSQL(t.sql)}>Enviar al editor SQL</button></article>)}
        </details>
      </>}
    </>}
  </div>;
}
