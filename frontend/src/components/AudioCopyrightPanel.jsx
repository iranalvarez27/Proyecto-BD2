import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  CircleAlert,
  Download,
  Inbox,
  LoaderCircle,
  Music,
  Play,
  Pause,
  RefreshCw,
  Search,
  Settings2,
  Upload,
} from "lucide-react";
import { uploadMediaApi } from "../utils/api";

const tiempo = (s) =>
  `${Math.floor(Math.max(0, s) / 60)}:${String(Math.floor(Math.max(0, s)) % 60).padStart(2, "0")}`;
const claveFragmento = (c) => `${c.track_id}:${c.inicio_s}:${c.fin_s}`;
const colores = ["#0369a1", "#6d28d9", "#047857", "#be185d", "#a16207"];
const campo =
  "w-full min-w-0 rounded-md border border-slate-300 bg-white px-2.5 py-2 text-xs text-slate-700 outline-sky-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200";
const etiqueta =
  "block text-[11px] font-medium text-slate-500 dark:text-slate-400";
const titulo =
  "flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300";
const tarjeta =
  "rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900";
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
    <label className={etiqueta}>
      <span className="mb-1 block">{label}</span>
      <input
        className={campo}
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
    <section
      ref={panel}
      aria-label="Detección de copyright en audio"
      className="@container flex h-full min-h-0 flex-col overflow-y-auto bg-slate-50 text-slate-800 dark:bg-slate-950 dark:text-slate-100"
    >
      <header className="shrink-0 space-y-3 border-b border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="rounded-lg border border-sky-200 bg-sky-50 p-2 text-sky-600 dark:border-sky-800 dark:bg-sky-950">
              <Music className="size-4" aria-hidden="true" />
            </div>
            <div>
              <h2 className={titulo}>Detección de copyright en audio</h2>
              <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
                Búsqueda de fragmentos musicales con MFCC, BoAW y alineación
                temporal.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => {
              setCargando(true);
              cargar();
            }}
            disabled={busy || cargando}
            title="Actualizar biblioteca"
            aria-label="Actualizar biblioteca"
            className="app-tool-button disabled:opacity-40"
          >
            <RefreshCw
              aria-hidden="true"
              className={
                "size-3.5 " + (cargando ? "motion-safe:animate-spin" : "")
              }
            />
          </button>
        </div>
        <form onSubmit={analizar}>
          <fieldset
            disabled={busy}
            className="grid grid-cols-1 items-end gap-2.5 disabled:opacity-70 @min-[640px]:grid-cols-3 @min-[1100px]:grid-cols-[minmax(180px,2fr)_minmax(100px,1fr)_minmax(90px,.7fr)_minmax(120px,1fr)_minmax(150px,1fr)_auto]"
          >
            <label className={etiqueta}>
              <span className="mb-1 block">Biblioteca</span>
              <select
                className={campo}
                value={n}
                onChange={(e) => {
                  setN(e.target.value);
                  setResultado(null);
                }}
                required
              >
                {!colecciones.length && (
                  <option value="">
                    {cargando
                      ? "Cargando biblioteca…"
                      : "Sin biblioteca disponible"}
                  </option>
                )}
                {colecciones.map((c) => (
                  <option key={c.n} value={c.n}>
                    {c.nombre || c.tabla}
                    {c.canciones
                      ? ` · ${c.canciones.toLocaleString()} canciones`
                      : ""}
                  </option>
                ))}
              </select>
            </label>
            <label className={etiqueta}>
              <span className="mb-1 block">Bloque de análisis</span>
              <select
                className={campo}
                value={params.segmento_s}
                onChange={(e) => cambiar("segmento_s", Number(e.target.value))}
              >
                <option value={5}>5 segundos</option>
                <option value={10}>10 segundos</option>
              </select>
            </label>
            <NumericField
              label="Vecinos (k)"
              min={1}
              max={200}
              value={params.k}
              onChange={(v) => cambiar("k", v)}
            />
            <NumericField
              label="Similitud BoAW mínima (%)"
              min={0}
              max={100}
              value={Math.round(params.umbral * 100)}
              onChange={(v) => cambiar("umbral", v / 100)}
            />
            <label className={etiqueta}>
              <span className="mb-1 block">Método de búsqueda</span>
              <select
                className={campo}
                value={params.metodo}
                onChange={(e) => cambiar("metodo", e.target.value)}
              >
                <option value="EXACTO">Exacta</option>
                <option value="HNSW">HNSW</option>
                <option value="IVF">IVF</option>
              </select>
            </label>
            <button
              type="submit"
              disabled={!file || !n || cargando}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-sky-700 px-5 py-2 text-xs font-semibold text-white transition hover:bg-sky-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 disabled:opacity-40"
            >
              {busy ? (
                <LoaderCircle
                  className="size-4 motion-safe:animate-spin"
                  aria-hidden="true"
                />
              ) : (
                <Search className="size-4" aria-hidden="true" />
              )}
              {busy ? "Analizando…" : "Analizar audio"}
            </button>
          </fieldset>
        </form>
        <p className="text-[11px] text-slate-500 dark:text-slate-400">
          Audio · MFCC + BoAW → coincidencias temporales
        </p>
      </header>
      <div className="flex flex-1 flex-col @min-[760px]:min-h-0 @min-[760px]:flex-row">
        <aside
          className="shrink-0 space-y-3 border-b border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900 @min-[760px]:w-60 @min-[760px]:overflow-y-auto @min-[760px]:border-r @min-[760px]:border-b-0"
          aria-label="Audio de consulta"
        >
          <h3 className={titulo}>
            <Upload className="size-3.5 text-sky-600" aria-hidden="true" />
            Tu audio
          </h3>
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
            className={
              "block rounded-lg border-2 border-dashed px-3 py-5 text-center transition focus-within:outline-2 focus-within:outline-sky-600 " +
              (busy
                ? "cursor-wait opacity-50"
                : "cursor-pointer hover:border-sky-500") +
              (file
                ? " border-sky-200 bg-sky-50 dark:border-sky-800 dark:bg-sky-950/40"
                : " border-slate-300 bg-slate-50 dark:border-slate-700 dark:bg-slate-950/40")
            }
          >
            <Upload
              className="mx-auto mb-2 size-7 text-sky-600 dark:text-sky-400"
              aria-hidden="true"
            />
            <span
              className="block truncate text-xs font-semibold"
              title={file?.name}
            >
              {file?.name || "Selecciona o arrastra un audio"}
            </span>
            <span className="mt-1 block text-[10px] text-slate-500">
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
              className="h-9 w-full"
              aria-label="Escuchar tu audio"
            />
          )}
          <p className="text-center text-[10px] text-slate-500 dark:text-slate-400">
            5 s a 10 min · Máximo 50 MB
          </p>
          {!!biblioteca?.canciones && (
            <div className="rounded-md bg-slate-50 px-3 py-2 text-[11px] text-slate-500 dark:bg-slate-950/50 dark:text-slate-400">
              <strong className="font-semibold text-slate-700 dark:text-slate-200">
                {biblioteca.canciones.toLocaleString()} canciones
              </strong>{" "}
              disponibles para comparar.
            </div>
          )}
          <fieldset disabled={busy} className="disabled:opacity-50">
            <details className="rounded-lg border border-slate-200 text-xs dark:border-slate-800">
              <summary className="cursor-pointer px-3 py-2.5 font-medium text-slate-600 dark:text-slate-300">
                <Settings2
                  className="mr-1 inline size-3.5"
                  aria-hidden="true"
                />
                Ajustes avanzados
              </summary>
              <div className="space-y-3 border-t border-slate-200 p-3 dark:border-slate-800">
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
                <label className="flex items-center gap-2 text-[11px] text-slate-500">
                  <input
                    type="checkbox"
                    checked={params.reducir_ruido}
                    onChange={(e) => cambiar("reducir_ruido", e.target.checked)}
                    className="accent-sky-600"
                  />
                  Compensar ruido de fondo
                </label>
              </div>
            </details>
          </fieldset>
        </aside>
        <div
          ref={resultados}
          className="min-w-0 flex-1 space-y-3 p-4 @min-[760px]:overflow-y-auto"
          aria-busy={busy}
        >
          {error && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-200"
            >
              <CircleAlert className="size-4 shrink-0" aria-hidden="true" />
              <p>{error}</p>
            </div>
          )}
          {!resultado && !error && (
            <div className="flex min-h-56 flex-col items-center justify-center gap-3 py-8 text-center @min-[760px]:h-full">
              <div className="rounded-full border border-sky-200 bg-sky-50 p-4 text-sky-600 dark:border-sky-900 dark:bg-sky-950/50">
                {busy ? (
                  <LoaderCircle
                    className="size-8 motion-safe:animate-spin"
                    aria-hidden="true"
                  />
                ) : (
                  <Inbox className="size-8 stroke-1" aria-hidden="true" />
                )}
              </div>
              <h3 className="text-sm font-semibold">
                {busy
                  ? "Analizando tu audio"
                  : "Encuentra coincidencias en tu biblioteca"}
              </h3>
              <p
                role="status"
                className="max-w-sm text-xs leading-relaxed text-slate-500 dark:text-slate-400"
              >
                {busy
                  ? `${estado} ${tiempo(transcurrido)} transcurridos.`
                  : "Selecciona un archivo y pulsa Analizar audio para buscar fragmentos coincidentes."}
              </p>
            </div>
          )}
          {resultado && (
            <>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className={titulo}>
                    <Activity
                      className="size-3.5 text-sky-600"
                      aria-hidden="true"
                    />
                    Resultado del análisis
                  </h3>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {resultado.conclusion}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={descargar}
                  className="app-tool-button"
                >
                  <Download className="size-3.5" aria-hidden="true" />
                  Exportar informe
                </button>
              </div>
              <dl className="grid grid-cols-2 gap-2 text-xs @min-[900px]:grid-cols-4">
                {[
                  ["Canciones encontradas", pistas.size],
                  ["Tramos coincidentes", resultado.coincidencias.length],
                  ["Duración del audio", tiempo(resultado.duracion_s)],
                  [
                    "Tiempo de análisis",
                    (
                      (resultado.metricas.total_ms ??
                        resultado.metricas.tiempo_ms) / 1000
                    ).toFixed(2) + " s",
                  ],
                ].map(([nombre, valor]) => (
                  <div key={nombre} className={tarjeta + " px-3 py-2.5"}>
                    <dt className={etiqueta}>{nombre}</dt>
                    <dd className="mt-1 font-mono text-base font-semibold text-sky-700 dark:text-sky-300">
                      {valor}
                    </dd>
                  </div>
                ))}
              </dl>
              <div className={tarjeta + " space-y-3 p-3"}>
                <div className="flex flex-wrap items-center justify-between gap-1">
                  <h3 className={titulo}>
                    <Music
                      className="size-3.5 text-sky-600"
                      aria-hidden="true"
                    />
                    Línea de tiempo
                  </h3>
                  <span className="text-[10px] text-slate-500">
                    Pulsa un tramo para escucharlo
                  </span>
                </div>
                {!pistas.size && (
                  <p className="rounded-md bg-slate-50 p-3 text-xs text-slate-500 dark:bg-slate-950/40">
                    Ningún fragmento superó los criterios de confirmación.
                  </p>
                )}
                {[...pistas.values()].map((eventos, i) => (
                  <div key={eventos[0].track_id}>
                    <p
                      className="mb-1.5 truncate text-xs font-medium"
                      title={`${eventos[0].titulo} · ${eventos[0].artista}`}
                    >
                      <span
                        className="mr-1.5 inline-block size-2 rounded-full"
                        style={{ backgroundColor: colores[i % colores.length] }}
                      />
                      {eventos[0].titulo}
                      <span className="font-normal text-slate-500">
                        {" "}
                        · {eventos[0].artista}
                      </span>
                    </p>
                    <div className="relative h-8 overflow-hidden rounded-md border border-slate-200 bg-slate-100 dark:border-slate-700 dark:bg-slate-800">
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
                          className="absolute h-full overflow-hidden rounded font-mono text-[10px] font-semibold text-white hover:brightness-110 focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-white"
                          title={`${tiempo(c.inicio_s)}–${tiempo(c.fin_s)} · ${c.porcentaje_similitud}% de similitud`}
                          aria-pressed={reproduciendo === claveFragmento(c)}
                          aria-label={`${reproduciendo === claveFragmento(c) ? "Pausar" : "Reproducir"} ${c.titulo} desde ${tiempo(c.inicio_s)}`}
                        >
                          {c.fin_s - c.inicio_s > resultado.duracion_s * 0.1
                            ? `${c.porcentaje_similitud}%`
                            : ""}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
                <div className="flex justify-between font-mono text-[10px] text-slate-500">
                  <span>0:00</span>
                  <span>{tiempo(resultado.duracion_s)}</span>
                </div>
              </div>
              {!!pistas.size && (
                <div className={tarjeta + " overflow-hidden"}>
                  <h3
                    className={
                      titulo +
                      " border-b border-slate-200 px-3 py-2.5 dark:border-slate-800"
                    }
                  >
                    Detalle de coincidencias
                  </h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-slate-50 text-[10px] uppercase text-slate-500 dark:bg-slate-950/40">
                        <tr>
                          {[
                            "En tu audio",
                            "Canción de referencia",
                            "En la referencia",
                            "Similitud",
                            "Escuchar",
                          ].map((h) => (
                            <th
                              key={h}
                              scope="col"
                              className="whitespace-nowrap px-3 py-2"
                            >
                              {h}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                        {resultado.coincidencias.map((c) => (
                          <tr
                            key={`${c.track_id}:${c.inicio_s}:${c.fin_s}`}
                            className="even:bg-slate-50/60 hover:bg-sky-50 dark:even:bg-slate-950/20 dark:hover:bg-slate-800/60"
                          >
                            <td className="whitespace-nowrap px-3 py-3 font-mono">
                              {tiempo(c.inicio_s)}–{tiempo(c.fin_s)}
                            </td>
                            <td className="px-3 py-3">
                              <p className="font-semibold">{c.titulo}</p>
                              <p className="mt-0.5 text-[10px] text-slate-500">
                                {c.artista}
                                {c.fuente ? ` · ${c.fuente}` : ""}
                              </p>
                            </td>
                            <td className="whitespace-nowrap px-3 py-3 font-mono">
                              {tiempo(c.original_inicio_s)}–
                              {tiempo(c.original_fin_s)}
                            </td>
                            <td className="px-3 py-3">
                              <span className="rounded bg-sky-50 px-1.5 py-1 font-mono font-semibold text-sky-700 dark:bg-sky-950 dark:text-sky-300">
                                {c.porcentaje_similitud}%
                              </span>
                              <p className="mt-1.5 text-[10px] text-slate-500">
                                {c.votos} votos temporales
                              </p>
                            </td>
                            <td className="px-3 py-3">
                              <button
                                type="button"
                                onClick={() => escuchar(c)}
                                className="app-tool-button"
                                aria-pressed={
                                  reproduciendo === claveFragmento(c)
                                }
                                aria-label={
                                  reproduciendo === claveFragmento(c)
                                    ? "Pausar tu audio"
                                    : "Reproducir tu audio"
                                }
                              >
                                {reproduciendo === claveFragmento(c) ? (
                                  <Pause
                                    className="size-3"
                                    aria-hidden="true"
                                  />
                                ) : (
                                  <Play className="size-3" aria-hidden="true" />
                                )}
                                {reproduciendo === claveFragmento(c)
                                  ? "Pausar"
                                  : "Tu audio"}
                              </button>
                              {c.audio_url && (
                                <audio
                                  controls
                                  onPlay={(e) => sincronizar(e.currentTarget)}
                                  preload="none"
                                  src={`${c.audio_url}#t=${c.original_inicio_s},${c.original_fin_s}`}
                                  className="mt-2 h-8 w-40"
                                  aria-label={`Referencia: ${c.titulo}`}
                                />
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
              {!!resultado.segmentos?.length && (
                <details className={tarjeta + " p-3 text-xs"}>
                  <summary className="cursor-pointer font-semibold text-slate-600 dark:text-slate-300">
                    Candidatos por histograma ({resultado.segmentos.length}{" "}
                    bloques)
                  </summary>
                  <p className="mt-3 text-[11px] text-slate-500">
                    La similitud BoAW preselecciona candidatos. La alineación
                    temporal y la secuencia verifican cada coincidencia.
                  </p>
                  <div className="mt-3 space-y-2">
                    {resultado.segmentos.map((segmento) => (
                      <div
                        key={segmento.inicio_s}
                        className="rounded-md border border-slate-200 bg-slate-50 p-2 dark:border-slate-800 dark:bg-slate-950/40"
                      >
                        <p>
                          <span className="font-mono font-medium">
                            {tiempo(segmento.inicio_s)}–{tiempo(segmento.fin_s)}
                          </span>{" "}
                          · {segmento.coincidencias.length} coincidencias con
                          evidencia temporal
                        </p>
                        <p className="mt-1 text-[11px] text-slate-500">
                          {segmento.candidatos
                            .slice(0, 5)
                            .map(
                              (c) =>
                                c.titulo +
                                " (BoAW: " +
                                (c.porcentaje_similitud ??
                                  (100 * c.similitud).toFixed(2)) +
                                "%)",
                            )
                            .join(" · ") || "Sin candidatos"}
                        </p>
                      </div>
                    ))}
                  </div>
                </details>
              )}
              <p className="text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">
                {resultado.aviso}
              </p>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
