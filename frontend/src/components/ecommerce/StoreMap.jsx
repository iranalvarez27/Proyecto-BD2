import { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

export default function StoreMap({ tiendas, ubicacion }) {
  const container = useRef(null);
  useEffect(() => {
    if (!container.current) return;
    const mapa = L.map(container.current).setView(ubicacion, 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors', maxZoom: 19,
    }).addTo(mapa);
    L.circleMarker(ubicacion, { radius: 7, color: '#2563eb', fillOpacity: .8 }).addTo(mapa).bindTooltip('Tu ubicación');
    const puntos = [ubicacion];
    tiendas.forEach(t => {
      const punto = t.ubicacion;
      puntos.push(punto);
      const texto = document.createElement('span');
      texto.textContent = `${t.nombre} · ${t.stock} disponibles`;
      L.circleMarker(punto, { radius: 7, color: '#059669', fillOpacity: .8 }).addTo(mapa).bindTooltip(texto);
    });
    if (puntos.length > 1) mapa.fitBounds(puntos, { padding: [24, 24], maxZoom: 14 });
    const observer = new ResizeObserver(() => mapa.invalidateSize());
    observer.observe(container.current);
    return () => { observer.disconnect(); mapa.remove(); };
  }, [tiendas, ubicacion]);
  return <div ref={container} className="shop-map" aria-label="Mapa de sucursales con stock" />;
}
