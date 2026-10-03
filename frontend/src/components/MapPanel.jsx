import React, { useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import {
  Map as MapIcon,
  Circle,
  Navigation,
  Hexagon,
  Hand,
  Play,
  Trash2,
  Zap,
  HardDrive,
} from 'lucide-react';

const LIMA = [-12.0931, -77.0465];
const MAX_FONDO = 4000;          // puntos de la tabla que se pintan como contexto
const MAX_ETIQUETAS_KNN = 25;    // por encima de esto los vecinos no llevan numero

const COLOR_FONDO = '#64748b';
const COLOR_RESULTADO = '#e11d48';
const COLOR_CONSULTA = '#336791';

const MODOS = [
  { id: 'radio', label: 'Radio', Icon: Circle, ayuda: 'Haz clic en el mapa para buscar todos los puntos dentro del radio.' },
  { id: 'knn', label: 'k-NN', Icon: Navigation, ayuda: 'Haz clic en el mapa para buscar los k puntos más cercanos.' },
  { id: 'poligono', label: 'Polígono', Icon: Hexagon, ayuda: 'Haz clic para marcar vértices (mínimo 3) y luego pulsa Consultar.' },
  { id: 'mover', label: 'Mover', Icon: Hand, ayuda: 'Modo navegación: arrastra y haz zoom sin lanzar consultas.' },
];

const fmt = (n) => Number(n).toFixed(5);

function tablasEspaciales(tables) {
  return (tables || [])
    .map((t) => ({
      name: t.name,
      column: (t.columns.find((c) => c.type === 'POINT') || {}).name,
      rtree: t.indexes.some((i) => i.type === 'RTREE'),
      records: t.stats ? t.stats.record_count : 0,
    }))
    .filter((t) => t.column);
}

function contenidoPopup(columns, row) {
  const caja = document.createElement('div');
  caja.className = 'map-popup';
  columns.forEach((col, i) => {
    const linea = document.createElement('div');
    const etiqueta = document.createElement('span');
    etiqueta.className = 'map-popup-key';
    etiqueta.textContent = `${col}: `;
    const valor = document.createElement('span');
    const v = row[i];
    valor.textContent = Array.isArray(v) ? `(${v.map(fmt).join(', ')})` : String(v);
    linea.append(etiqueta, valor);
    caja.append(linea);
  });
  return caja;
}

export default function MapPanel({ result, tables, visible, theme, onRunQuery }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const capasRef = useRef(null);
  const clickRef = useRef(() => {});
  const ajustadoRef = useRef(null);
  const visibleRef = useRef(visible);
  const encuadrePendienteRef = useRef(null);
  visibleRef.current = visible;

  // Encuadra el mapa; si la pestaña está oculta (mapa sin tamaño) lo deja para cuando se abra.
  const encuadrar = (limites, opciones) => {
    if (visibleRef.current && mapRef.current) {
      mapRef.current.fitBounds(limites, opciones);
    } else {
      encuadrePendienteRef.current = [limites, opciones];
    }
  };

  const [tableName, setTableName] = useState(null);
  const [mode, setMode] = useState('radio');
  const [radius, setRadius] = useState(2000);
  const [k, setK] = useState(10);
  const [metric, setMetric] = useState('haversine');
  const [draft, setDraft] = useState([]);
  const [fondo, setFondo] = useState(null);
  const [errorFondo, setErrorFondo] = useState(null);

  const espaciales = useMemo(() => tablasEspaciales(tables), [tables]);
  const actual = espaciales.find((t) => t.name === tableName) || null;
  const spatial = result && result.status === 'success' ? result.spatial : null;

  // La tabla del mapa sigue a la última consulta espacial; si no, la primera con POINT.
  useEffect(() => {
    if (spatial && spatial.tabla) {
      setTableName(spatial.tabla);
    }
  }, [spatial]);

  useEffect(() => {
    if (!espaciales.length) return;
    if (!tableName || !espaciales.some((t) => t.name === tableName)) {
      setTableName(espaciales[0].name);
    }
  }, [espaciales, tableName]);

  // Crear el mapa una sola vez.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return undefined;
    const map = L.map(containerRef.current, { center: LIMA, zoom: 12, preferCanvas: true });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);
    capasRef.current = {
      fondo: L.layerGroup().addTo(map),
      consulta: L.layerGroup().addTo(map),
      resultados: L.layerGroup().addTo(map),
      borrador: L.layerGroup().addTo(map),
    };
    map.on('click', (e) => clickRef.current(e.latlng));
    mapRef.current = map;

    const observador = new ResizeObserver(() => map.invalidateSize());
    observador.observe(containerRef.current);
    return () => {
      observador.disconnect();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (visible && mapRef.current) {
      setTimeout(() => {
        const map = mapRef.current;
        if (!map) return;
        map.invalidateSize();
        if (encuadrePendienteRef.current) {
          map.fitBounds(...encuadrePendienteRef.current);
          encuadrePendienteRef.current = null;
        }
      }, 0);
    }
  }, [visible]);

  // Puntos de la tabla (muestra) como contexto de fondo.
  const registros = actual ? actual.records : 0;
  useEffect(() => {
    if (!tableName) return undefined;
    let cancelado = false;
    setErrorFondo(null);
    fetch(`/api/tables/${encodeURIComponent(tableName)}/points?limit=${MAX_FONDO}`)
      .then((res) => (res.ok ? res.json() : res.json().then((e) => Promise.reject(new Error(e.detail || 'error')))))
      .then((data) => { if (!cancelado) setFondo(data); })
      .catch((err) => { if (!cancelado) { setFondo(null); setErrorFondo(err.message); } });
    return () => { cancelado = true; };
  }, [tableName, registros]);

  useEffect(() => {
    const capas = capasRef.current;
    const map = mapRef.current;
    if (!capas || !map) return;
    capas.fondo.clearLayers();
    if (!fondo) return;
    fondo.points.forEach((p) => {
      L.circleMarker(p, {
        radius: 2.5, stroke: false, fillColor: COLOR_FONDO, fillOpacity: 0.55, interactive: false,
      }).addTo(capas.fondo);
    });
    // encuadrar la tabla solo la primera vez que se muestra (no pisar el zoom del usuario)
    if (fondo.bbox && ajustadoRef.current !== fondo.table) {
      ajustadoRef.current = fondo.table;
      if (!spatial || spatial.tipo === 'puntos') {
        const [latMin, lonMin, latMax, lonMax] = fondo.bbox;
        encuadrar([[latMin, lonMin], [latMax, lonMax]], { padding: [24, 24] });
      }
    }
  }, [fondo]);

  // Geometría de la consulta + resultados resaltados.
  useEffect(() => {
    const capas = capasRef.current;
    const map = mapRef.current;
    if (!capas || !map) return;
    capas.consulta.clearLayers();
    capas.resultados.clearLayers();
    if (!spatial) return;

    const limites = L.latLngBounds([]);
    const trazo = { color: COLOR_CONSULTA, weight: 2, fillColor: COLOR_CONSULTA, fillOpacity: 0.08, interactive: false };

    if (spatial.tipo === 'radio') {
      const circulo = L.circle(spatial.centro, { ...trazo, radius: spatial.radio_m }).addTo(capas.consulta);
      limites.extend(circulo.getBounds());
    } else if (spatial.tipo === 'poligono') {
      const poligono = L.polygon(spatial.poligono, trazo).addTo(capas.consulta);
      limites.extend(poligono.getBounds());
    }
    if (spatial.centro) {
      L.circleMarker(spatial.centro, {
        radius: 5, color: '#ffffff', weight: 2, fillColor: COLOR_CONSULTA, fillOpacity: 1, interactive: false,
      }).addTo(capas.consulta);
      limites.extend(spatial.centro);
    }

    const puntos = spatial.puntos || [];
    const etiquetar = spatial.tipo === 'knn' && puntos.length <= MAX_ETIQUETAS_KNN;
    const muchos = puntos.length > 150;   // con muchos resultados, marcas mas chicas para que no se tapen
    puntos.forEach((p, i) => {
      if (spatial.tipo === 'knn' && spatial.centro) {
        L.polyline([spatial.centro, p], { color: COLOR_CONSULTA, weight: 1, opacity: 0.5, dashArray: '3 4', interactive: false })
          .addTo(capas.consulta);
      }
      const marca = L.circleMarker(p, {
        radius: muchos ? 4 : 6, color: '#ffffff', weight: muchos ? 1 : 1.5,
        fillColor: COLOR_RESULTADO, fillOpacity: muchos ? 0.8 : 0.95,
      }).addTo(capas.resultados);
      if (result.rows && result.rows[i]) {
        marca.bindPopup(() => contenidoPopup(result.columns, result.rows[i]));
      }
      if (etiquetar) {
        // etiquetas alternadas arriba / derecha / abajo / izquierda: vecinos pegados no se tapan
        const lado = [['top', [0, -5]], ['right', [6, 0]], ['bottom', [0, 5]], ['left', [-6, 0]]][i % 4];
        marca.bindTooltip(String(i + 1), { permanent: true, direction: lado[0], offset: lado[1], className: 'map-rank' });
      }
      limites.extend(p);
    });

    if (limites.isValid() && (spatial.tipo !== 'puntos' || (puntos.length && puntos.length < 2000))) {
      encuadrar(limites, { padding: [32, 32], maxZoom: 16 });
    }
  }, [result]);

  // Borrador del polígono mientras se marcan vértices.
  useEffect(() => {
    const capas = capasRef.current;
    if (!capas) return;
    capas.borrador.clearLayers();
    if (!draft.length) return;
    const estilo = { color: COLOR_RESULTADO, weight: 2, dashArray: '5 5', fillOpacity: 0.06, interactive: false };
    if (draft.length >= 3) {
      L.polygon(draft, estilo).addTo(capas.borrador);
    } else if (draft.length === 2) {
      L.polyline(draft, estilo).addTo(capas.borrador);
    }
    draft.forEach((p) => {
      L.circleMarker(p, { radius: 4, color: '#ffffff', weight: 1.5, fillColor: COLOR_RESULTADO, fillOpacity: 1, interactive: false })
        .addTo(capas.borrador);
    });
  }, [draft]);

  useEffect(() => {
    if (mode !== 'poligono') setDraft([]);
    const map = mapRef.current;
    if (map) {
      if (mode === 'poligono') map.doubleClickZoom.disable();
      else map.doubleClickZoom.enable();
    }
  }, [mode]);

  const funcionDistancia = metric === 'euclidiana' ? 'distancia_euclidiana' : 'distancia';

  clickRef.current = ({ lat, lng }) => {
    if (!actual || mode === 'mover') return;
    const punto = `POINT(${fmt(lat)}, ${fmt(lng)})`;
    if (mode === 'radio') {
      const r = Math.max(1, Number(radius) || 0);
      onRunQuery(`SELECT * FROM ${actual.name} WHERE ${funcionDistancia}(${actual.column}, ${punto}) < ${r};`);
    } else if (mode === 'knn') {
      const vecinos = Math.max(1, Math.floor(Number(k) || 1));
      onRunQuery(`SELECT * FROM ${actual.name} ORDER BY ${funcionDistancia}(${actual.column}, ${punto}) LIMIT ${vecinos};`);
    } else if (mode === 'poligono') {
      setDraft((d) => [...d, [lat, lng]]);
    }
  };

  const consultarPoligono = () => {
    if (!actual || draft.length < 3) return;
    const vertices = draft.map(([lat, lng]) => `POINT(${fmt(lat)}, ${fmt(lng)})`).join(', ');
    onRunQuery(`SELECT * FROM ${actual.name} WHERE dentro_de(${actual.column}, POLYGON(${vertices}));`);
    setDraft([]);
  };

  const modoActual = MODOS.find((m) => m.id === mode);
  const nResultados = spatial && spatial.puntos ? spatial.puntos.length : null;
  const campo = 'bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 text-xs text-slate-700 dark:text-slate-200 rounded px-2 py-1 outline-none focus:border-pg-500';

  return (
    <div className="flex flex-col h-full bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-100">
      {/* Barra de herramientas */}
      <div className="px-3 py-2 border-b border-slate-200 dark:border-slate-800 flex items-center gap-2 flex-wrap shrink-0">
        <MapIcon className="w-4 h-4 text-pg-600 dark:text-pg-400 shrink-0" />

        <select
          value={tableName || ''}
          onChange={(e) => setTableName(e.target.value)}
          disabled={!espaciales.length}
          title="Tabla con columna POINT"
          className={campo}
        >
          {!espaciales.length && <option value="">Sin tablas POINT</option>}
          {espaciales.map((t) => (
            <option key={t.name} value={t.name}>{t.name}.{t.column}</option>
          ))}
        </select>

        <div className="flex items-center rounded border border-slate-300 dark:border-slate-700 overflow-hidden">
          {MODOS.map(({ id, label, Icon }) => (
            <button
              key={id}
              onClick={() => setMode(id)}
              className={`flex items-center gap-1 px-2 py-1 text-xs transition-colors ${
                mode === id
                  ? 'bg-pg-600 dark:bg-pg-500 text-white'
                  : 'bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{label}</span>
            </button>
          ))}
        </div>

        {mode === 'radio' && (
          <label className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
            <span>Radio</span>
            <input type="number" min="1" step="100" value={radius} onChange={(e) => setRadius(e.target.value)} className={`${campo} w-20 font-mono`} />
            <span>m</span>
          </label>
        )}
        {mode === 'knn' && (
          <label className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
            <span>k</span>
            <input type="number" min="1" step="1" value={k} onChange={(e) => setK(e.target.value)} className={`${campo} w-16 font-mono`} />
          </label>
        )}
        {(mode === 'radio' || mode === 'knn') && (
          <select value={metric} onChange={(e) => setMetric(e.target.value)} title="Métrica de distancia" className={campo}>
            <option value="haversine">Haversine (geodésica)</option>
            <option value="euclidiana">Euclidiana</option>
          </select>
        )}
        {mode === 'poligono' && (
          <>
            <button
              onClick={consultarPoligono}
              disabled={draft.length < 3}
              className="flex items-center gap-1 px-2.5 py-1 bg-pg-600 hover:bg-pg-700 dark:bg-pg-500 dark:hover:bg-pg-400 text-white rounded text-xs font-semibold transition disabled:opacity-50"
            >
              <Play className="w-3 h-3 fill-current" />
              <span>Consultar ({draft.length})</span>
            </button>
            <button
              onClick={() => setDraft([])}
              disabled={!draft.length}
              title="Borrar vértices"
              className="p-1.5 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 rounded transition disabled:opacity-40"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </>
        )}

        <div className="ml-auto flex items-center gap-2 text-[11px]">
          {nResultados !== null && (
            <span className="flex items-center gap-1.5 text-slate-600 dark:text-slate-300">
              <span className="w-2.5 h-2.5 rounded-full border border-white" style={{ backgroundColor: COLOR_RESULTADO }} />
              <span className="font-mono">{nResultados}</span> resultados · {result.execution_time_ms} ms
            </span>
          )}
          {spatial && spatial.tipo !== 'puntos' && (
            spatial.usa_indice ? (
              <span className="flex items-center gap-1 px-2 py-0.5 rounded-full border bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/60">
                <Zap className="w-3 h-3" /> R-Tree
              </span>
            ) : (
              <span className="flex items-center gap-1 px-2 py-0.5 rounded-full border bg-amber-50 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800/60">
                <HardDrive className="w-3 h-3" /> Escaneo secuencial
              </span>
            )
          )}
        </div>
      </div>

      {/* Mapa */}
      {/* Las clases que cambian (tema, cursor) van en este envoltorio. El div del mapa
          tiene className fijo: Leaflet le agrega sus propias clases y, si React lo
          reescribe al cambiar de modo, el mapa pierde su CSS y se desarma. */}
      <div className={`relative z-0 flex-1 min-h-0 overflow-hidden ${theme === 'dark' ? 'map-dark' : ''} ${mode === 'mover' ? '' : 'map-crosshair'}`}>
        <div ref={containerRef} className="absolute inset-0" />
        {!espaciales.length && (
          <div className="absolute inset-0 z-[1000] flex items-center justify-center bg-white/85 dark:bg-slate-900/85 p-6 text-center text-xs text-slate-600 dark:text-slate-300">
            <div>
              <p className="font-semibold mb-1">No hay tablas con una columna POINT.</p>
              <p className="font-mono">CREATE TABLE lugares (id INT PRIMARY KEY, nombre VARCHAR(30), ubicacion POINT);</p>
            </div>
          </div>
        )}
      </div>

      {/* Pie: ayuda del modo + leyenda */}
      <div className="px-3 py-1.5 border-t border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/40 flex items-center justify-between gap-3 text-[11px] text-slate-500 dark:text-slate-400 shrink-0">
        <span className="truncate">{errorFondo ? `No se pudieron cargar los puntos: ${errorFondo}` : modoActual.ayuda}</span>
        {fondo && (
          <span className="flex items-center gap-1.5 shrink-0">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: COLOR_FONDO }} />
            <span>
              {fondo.returned < fondo.total
                ? `muestra de ${fondo.returned.toLocaleString('es-PE')} de ${fondo.total.toLocaleString('es-PE')} puntos`
                : `${fondo.total.toLocaleString('es-PE')} puntos`}
              {actual && !actual.rtree ? ' · sin índice R-Tree' : ''}
            </span>
          </span>
        )}
      </div>
    </div>
  );
}
