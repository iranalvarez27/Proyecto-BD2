import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Download,
  Inbox,
  LoaderCircle,
  Music,
  Pause,
  Play,
  RefreshCw,
  Search,
  Settings2,
  SlidersHorizontal,
  Upload,
  X,
} from "lucide-react";
import { uploadMediaApi } from "../utils/api";
import "./ecommerce/shop.css";
import "./audio/audio.css";

const tiempo = (s) =>
  `${Math.floor(Math.max(0, s) / 60)}:${String(Math.floor(Math.max(0, s)) % 60).padStart(2, "0")}`;
const claveFragmento = (c) => `${c.track_id}:${c.inicio_s}:${c.fin_s}`;
const colores = ["#235bd8", "#db65a2", "#29a387", "#daa640", "#6366dc"];
const inicial = {
  segmento_s: 5,
  paso_s: 0.5,
  k: 100,
  umbral: 0.65,
  min_votos: 2,
  metodo: "EXACTO",
  representacion: "hibrida",
  umbral_secuencia: 0.6,
  reducir_ruido: true,
};

function NumericField({ label, value, onChange, min, max, step = 1 }) {
  return (
    <label className="audio-field">
      {label}
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}

export default function AudioCopyrightPanel() {
  const [colecciones, setColecciones] = useState([]);
  const [n, setN] = useState("");
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState("");
  const [duracion, setDuracion] = useState(null);
  const [subida, setSubida] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [resultado, setResultado] = useState(null);
  const [estado, setEstado] = useState("");
  const [transcurrido, setTranscurrido] = useState(0);
  const [params, setParams] = useState(inicial);
  const [reproduciendo, setReproduciendo] = useState(null);
  const panel = useRef(null);
  const fragmento = useRef(null);
  const player = useRef(null);
  const resultados = useRef(null);
  const cambiar = (clave, valor) =>
    setParams((p) => ({ ...p, [clave]: valor }));

  const cargar = useCallback((signal) => {
    return fetch("/api/audio/collections", { signal })
      .then(async (res) => {
        if (!res.ok)
          throw new Error("No se pudo cargar la biblioteca de audio.");
        const data = await res.json();
        if (signal?.aborted) return;
        setColecciones(data.colecciones);
        setN((prev) =>
          String(
            data.colecciones.find((c) => String(c.n) === prev)?.n ||
              data.colecciones.find((c) => c.unificada)?.n ||
              data.colecciones.find((c) => c.completa)?.n ||
              data.colecciones[0]?.n ||
              "",
          ),
        );
        setError("");
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!signal?.aborted) setCargando(false);
      });
  }, []);

  useEffect(() => {
    const c = new AbortController();
    cargar(c.signal);
    return () => c.abort();
  }, [cargar]);
  useEffect(() => {
    if (preview) return () => URL.revokeObjectURL(preview);
  }, [preview]);
  useEffect(() => {
    if (!busy) return;
    const inicio = Date.now();
    const timer = setInterval(
      () => setTranscurrido(Math.floor((Date.now() - inicio) / 1000)),
      1000,
    );
    return () => clearInterval(timer);
  }, [busy]);
  useEffect(() => {
    if (resultados.current) resultados.current.scrollTop = 0;
  }, [resultado, busy]);

  const seleccionar = (archivo) => {
    player.current?.pause();
    fragmento.current = null;
    setReproduciendo(null);
    setResultado(null);
    setEstado("");
    setSubida(null);
    setDuracion(null);
    setError("");
    setPreview("");
    if (archivo && !/\.(mp3|wav|ogg|flac|m4a)$/i.test(archivo.name)) {
      setFile(null);
      setError("Selecciona un audio MP3, WAV, OGG, FLAC o M4A.");
      return;
    }
    if (archivo && archivo.size > 50 * 1024 * 1024) {
      setFile(null);
      setError("El archivo debe pesar como máximo 50 MB.");
      return;
    }
    setFile(archivo);
    if (archivo) setPreview(URL.createObjectURL(archivo));
  };
  const analizar = async (e) => {
    e.preventDefault();
    if (!file || !n || busy) return;
    const minimo = 5;
    if (duracion !== null && (duracion < minimo || duracion > 600)) {
      setError(
        `Usa un audio de ${minimo} segundos a 10 minutos para este tipo de búsqueda.`,
      );
      return;
    }
    setTranscurrido(0);
    setBusy(true);
    setError("");
    setResultado(null);
    try {
      setEstado(subida ? "Preparando el análisis…" : "Subiendo el audio…");
      const uploaded = subida || (await uploadMediaApi(file));
      setSubida(uploaded);
      setEstado("Buscando y verificando coincidencias…");
      const res = await fetch("/api/audio/detect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path: uploaded.path,
          n_coleccion: Number(n),
          ...params,
        }),
      });
      const data = await res.json();
      if (!res.ok)
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : "No se pudo completar el análisis.",
        );
      setResultado(data);
      setEstado("Análisis completado");
    } catch (e) {
      setError(e.message);
      setEstado("");
    } finally {
      setBusy(false);
    }
  };
  const sincronizar = (audio) => {
    for (const otro of panel.current.querySelectorAll("audio")) {
      if (otro !== audio) otro.pause();
    }
    setReproduciendo(audio === player.current ? fragmento.current : null);
  };
  const escuchar = (coincidencia) => {
    const audio = player.current;
    if (!audio) return;
    const clave = claveFragmento(coincidencia);
    if (fragmento.current === clave && !audio.paused) {
      audio.pause();
      return;
    }
    if (fragmento.current !== clave || audio.ended) {
      fragmento.current = clave;
      audio.currentTime = coincidencia.inicio_s;
    }
    audio.play().catch((e) => {
      if (e.name !== "AbortError")
        setError("Pulsa reproducir en el control de audio.");
    });
  };
  const descargar = () => {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(resultado, null, 2)], {
        type: "application/json",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "analisis-audio.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const pistas = new Map();
  for (const c of resultado?.coincidencias || []) {
    if (!pistas.has(c.track_id)) pistas.set(c.track_id, []);
    pistas.get(c.track_id).push(c);
  }
  const biblioteca = colecciones.find((c) => String(c.n) === n);

  return (
    <div ref={panel} className="shop" aria-label="Detección de copyright en audio">
      <header className="shop-header">
        <div className="shop-brand">
          <Music size={23} />
          <div>
            <strong>Copyright de audio</strong>
            <span>Encuentra fragmentos de canciones originales</span>
          </div>
        </div>
        <button
          type="button"
          className="shop-button"
          onClick={() => {
            setCargando(true);
            cargar();
          }}
          disabled={busy || cargando}
          title="Actualizar biblioteca"
        >
          <RefreshCw size={16} className={cargando ? "motion-safe:animate-spin" : ""} /> Actualizar biblioteca
        </button>
      </header>
      <div className="shop-notice">
        Audio · MFCC + BoAW → coincidencias temporales · La similitud es orientativa y no demuestra una infracción
      </div>
      {error && (
        <div className="shop-error" role="alert">
          {error}
          <button aria-label="Cerrar error" onClick={() => setError("")}>
            <X size={16} />
          </button>
        </div>
      )}

      <div className="shop-intro">
        <div>
          <p className="shop-eyebrow">DETECCIÓN DE COPYRIGHT</p>
          <h1>Descubre qué canciones hay dentro de tu audio.</h1>
          <p>
            Sube una canción, un remix o un cover y el sistema la divide en bloques de 5 a 10 segundos para
            compararla con la biblioteca de originales.
          </p>
        </div>
        {!!biblioteca?.canciones && (
          <span className="shop-count">{biblioteca.canciones.toLocaleString()} canciones en esta fuente</span>
        )}
      </div>

      <form onSubmit={analizar} className="audio-layout">
        <section className="audio-card" aria-label="Audio de consulta">
          <h2>
            <Upload size={17} /> Tu audio
          </h2>
          <label
            onDragOver={(e) => {
              e.preventDefault();
              e.dataTransfer.dropEffect = busy ? "none" : "copy";
            }}
            onDrop={(e) => {
              e.preventDefault();
              if (!busy && e.dataTransfer.files.length) {
                seleccionar(e.dataTransfer.files[0]);
                e.currentTarget.querySelector("input").value = "";
              }
            }}
            className={"audio-drop" + (file ? " has-file" : "") + (busy ? " is-busy" : "")}
          >
            <Upload size={28} aria-hidden="true" />
            <strong title={file?.name}>{file?.name || "Selecciona o arrastra un audio"}</strong>
            <span>
              {file
                ? `${(file.size / 1024 / 1024).toFixed(2)} MB · Haz clic para cambiar`
                : "MP3, WAV, FLAC, OGG o M4A"}
            </span>
            <input
              type="file"
              accept=".mp3,.wav,.ogg,.flac,.m4a"
              disabled={busy}
              className="sr-only"
              aria-label="Seleccionar audio"
              onChange={(e) => seleccionar(e.target.files?.[0] || null)}
            />
          </label>
          {preview && (
            <audio
              key={preview}
              ref={player}
              src={preview}
              controls
              preload="metadata"
              onPlay={(e) => sincronizar(e.currentTarget)}
              onPause={() => setReproduciendo(null)}
              onEnded={() => setReproduciendo(null)}
              onLoadedMetadata={(e) => setDuracion(e.currentTarget.duration)}
              className="audio-player"
              aria-label="Escuchar tu audio"
            />
          )}
          <p className="audio-hint">5 s a 10 min · Máximo 50 MB</p>
        </section>

        <section className="audio-card" aria-label="Parámetros de búsqueda">
          <h2>
            <SlidersHorizontal size={17} /> Parámetros de búsqueda
          </h2>
          <fieldset disabled={busy} className="audio-fields">
            <label className="audio-field audio-wide" title="Buscar solo en una fuente compara menos canciones y responde antes">
              Fuente de búsqueda
              <select
                value={n}
                onChange={(e) => {
                  setN(e.target.value);
                  setResultado(null);
                }}
                required
              >
                {!colecciones.length && (
                  <option value="">{cargando ? "Cargando biblioteca…" : "Sin biblioteca disponible"}</option>
                )}
                {colecciones.map((c) => (
                  <option key={c.n} value={c.n}>
                    {c.nombre || c.tabla}
                    {c.canciones ? ` · ${c.canciones.toLocaleString()} canciones` : ""}
                  </option>
                ))}
              </select>
            </label>
            <label className="audio-field">
              Bloque de análisis
              <select value={params.segmento_s} onChange={(e) => cambiar("segmento_s", Number(e.target.value))}>
                <option value={5}>5 segundos</option>
                <option value={10}>10 segundos</option>
              </select>
            </label>
            <NumericField label="Vecinos (k)" min={1} max={200} value={params.k} onChange={(v) => cambiar("k", v)} />
            <NumericField
              label="Similitud BoAW mínima (%)"
              min={0}
              max={100}
              value={Math.round(params.umbral * 100)}
              onChange={(v) => cambiar("umbral", v / 100)}
            />
            <label className="audio-field">
              Método de búsqueda
              <select value={params.metodo} onChange={(e) => cambiar("metodo", e.target.value)}>
                <option value="EXACTO">Exacta</option>
                <option value="HNSW">HNSW</option>
                <option value="IVF">IVF</option>
              </select>
            </label>
          </fieldset>
          <fieldset disabled={busy} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
            <details className="audio-advanced">
              <summary>
                <Settings2 size={16} /> Ajustes avanzados
              </summary>
              <div className="audio-fields">
                <NumericField
                  label="Salto entre ventanas (s)"
                  min={0.1}
                  max={1}
                  step={0.1}
                  value={params.paso_s}
                  onChange={(v) => cambiar("paso_s", v)}
                />
                <NumericField
                  label="Votos temporales mínimos"
                  min={2}
                  max={20}
                  value={params.min_votos}
                  onChange={(v) => cambiar("min_votos", v)}
                />
                <NumericField
                  label="Similitud de secuencia mínima (%)"
                  min={0}
                  max={100}
                  value={Math.round(params.umbral_secuencia * 100)}
                  onChange={(v) => cambiar("umbral_secuencia", v / 100)}
                />
                <label className="audio-check">
                  <input
                    type="checkbox"
                    checked={params.reducir_ruido}
                    onChange={(e) => cambiar("reducir_ruido", e.target.checked)}
                  />
                  Compensar ruido de fondo
                </label>
              </div>
            </details>
          </fieldset>
          <div className="audio-actions">
            <button type="submit" className="shop-primary" disabled={!file || !n || cargando || busy}>
              {busy ? (
                <LoaderCircle size={16} className="motion-safe:animate-spin" aria-hidden="true" />
              ) : (
                <Search size={16} aria-hidden="true" />
              )}
              {busy ? "Analizando…" : "Analizar audio"}
            </button>
          </div>
        </section>
      </form>

      <div ref={resultados} aria-busy={busy}>
        {!resultado && !error && (
          <div className="audio-state" role="status">
            {busy ? (
              <LoaderCircle size={34} className="motion-safe:animate-spin" aria-hidden="true" />
            ) : (
              <Inbox size={34} strokeWidth={1.5} aria-hidden="true" />
            )}
            <h2>{busy ? "Analizando tu audio" : "Encuentra coincidencias en tu biblioteca"}</h2>
            <p>
              {busy
                ? `${estado} ${tiempo(transcurrido)} transcurridos.`
                : "Selecciona un archivo y pulsa Analizar audio para buscar fragmentos coincidentes."}
            </p>
          </div>
        )}

        {resultado && (
          <>
            <div className="shop-section-title">
              <h2>Resultado del análisis</h2>
              <button type="button" onClick={descargar} className="shop-button">
                <Download size={15} aria-hidden="true" /> Exportar informe
              </button>
            </div>
            <p className={resultado.coincidencias.length ? "shop-error" : "shop-success"} role="status">
              {resultado.conclusion}
            </p>
            <dl className="audio-stats">
              {[
                ["Canciones encontradas", pistas.size],
                ["Tramos coincidentes", resultado.coincidencias.length],
                ["Duración del audio", tiempo(resultado.duracion_s)],
                [
                  "Tiempo de análisis",
                  ((resultado.metricas.total_ms ?? resultado.metricas.tiempo_ms) / 1000).toFixed(2) + " s",
                ],
              ].map(([nombre, valor]) => (
                <div key={nombre} className="audio-stat">
                  <dt>{nombre}</dt>
                  <dd>{valor}</dd>
                </div>
              ))}
            </dl>

            <section className="audio-section">
              <div className="shop-section-title">
                <h2>Línea de tiempo</h2>
                <span>Pulsa un tramo para escucharlo</span>
              </div>
              {!pistas.size && <p className="shop-empty">Ningún fragmento superó los criterios de confirmación.</p>}
              {[...pistas.values()].map((eventos, i) => (
                <div key={eventos[0].track_id}>
                  <p className="audio-track-name" title={`${eventos[0].titulo} · ${eventos[0].artista}`}>
                    <i style={{ backgroundColor: colores[i % colores.length] }} />
                    <strong>{eventos[0].titulo}</strong>
                    <span> · {eventos[0].artista}</span>
                  </p>
                  <div className="audio-track">
                    {eventos.map((c) => (
                      <button
                        key={`${c.inicio_s}:${c.fin_s}`}
                        type="button"
                        onClick={() => escuchar(c)}
                        style={{
                          left: `${(100 * c.inicio_s) / resultado.duracion_s}%`,
                          width: `${(100 * (c.fin_s - c.inicio_s)) / resultado.duracion_s}%`,
                          backgroundColor: colores[i % colores.length],
                        }}
                        className="audio-seg"
                        title={`${tiempo(c.inicio_s)}–${tiempo(c.fin_s)} · ${c.porcentaje_similitud}% de similitud`}
                        aria-pressed={reproduciendo === claveFragmento(c)}
                        aria-label={`${reproduciendo === claveFragmento(c) ? "Pausar" : "Reproducir"} ${c.titulo} desde ${tiempo(c.inicio_s)}`}
                      >
                        {c.fin_s - c.inicio_s > resultado.duracion_s * 0.1 ? `${c.porcentaje_similitud}%` : ""}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
              <div className="audio-scale">
                <span>0:00</span>
                <span>{tiempo(resultado.duracion_s)}</span>
              </div>
            </section>

            {!!pistas.size && (
              <section className="audio-section">
                <div className="shop-section-title">
                  <h2>Detalle de coincidencias</h2>
                  <span>{resultado.coincidencias.length} tramos</span>
                </div>
                <div className="audio-table-wrap">
                  <table className="audio-table">
                    <thead>
                      <tr>
                        {["En tu audio", "Canción de referencia", "En la referencia", "Similitud", "Escuchar"].map((h) => (
                          <th key={h} scope="col">
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {resultado.coincidencias.map((c) => (
                        <tr key={`${c.track_id}:${c.inicio_s}:${c.fin_s}`}>
                          <td className="audio-time">
                            {tiempo(c.inicio_s)}–{tiempo(c.fin_s)}
                          </td>
                          <td>
                            <strong>{c.titulo}</strong>
                            <small>
                              {c.artista}
                              {c.fuente ? ` · ${c.fuente}` : ""}
                            </small>
                          </td>
                          <td className="audio-time">
                            {tiempo(c.original_inicio_s)}–{tiempo(c.original_fin_s)}
                          </td>
                          <td>
                            <span className="audio-badge">{c.porcentaje_similitud}%</span>
                            <small>{c.votos} votos temporales</small>
                          </td>
                          <td>
                            <button
                              type="button"
                              onClick={() => escuchar(c)}
                              className="shop-button audio-mini"
                              aria-pressed={reproduciendo === claveFragmento(c)}
                              aria-label={reproduciendo === claveFragmento(c) ? "Pausar tu audio" : "Reproducir tu audio"}
                            >
                              {reproduciendo === claveFragmento(c) ? (
                                <Pause size={13} aria-hidden="true" />
                              ) : (
                                <Play size={13} aria-hidden="true" />
                              )}
                              {reproduciendo === claveFragmento(c) ? "Pausar" : "Tu audio"}
                            </button>
                            {c.audio_url && (
                              <audio
                                controls
                                onPlay={(e) => sincronizar(e.currentTarget)}
                                preload="none"
                                src={`${c.audio_url}#t=${c.original_inicio_s},${c.original_fin_s}`}
                                className="audio-ref"
                                aria-label={`Referencia: ${c.titulo}`}
                              />
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {!!resultado.segmentos?.length && (
              <details className="shop-traces">
                <summary>Candidatos por histograma ({resultado.segmentos.length} bloques)</summary>
                <p>
                  La similitud BoAW preselecciona candidatos. La alineación temporal y la secuencia verifican cada
                  coincidencia.
                </p>
                {resultado.segmentos.map((segmento) => (
                  <div key={segmento.inicio_s} className="audio-candidate">
                    <strong className="audio-time">
                      {tiempo(segmento.inicio_s)}–{tiempo(segmento.fin_s)}
                    </strong>{" "}
                    · {segmento.coincidencias.length} coincidencias con evidencia temporal
                    <p>
                      {segmento.candidatos
                        .slice(0, 5)
                        .map(
                          (c) =>
                            c.titulo + " (BoAW: " + (c.porcentaje_similitud ?? (100 * c.similitud).toFixed(2)) + "%)",
                        )
                        .join(" · ") || "Sin candidatos"}
                    </p>
                  </div>
                ))}
              </details>
            )}
            <p className="audio-notice">{resultado.aviso}</p>
          </>
        )}
      </div>
    </div>
  );
}
