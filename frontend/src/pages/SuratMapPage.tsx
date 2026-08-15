import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import neighborhoods from "../data/surat-neighborhoods.json";
import { DataState, EmptyState, PageHeader } from "../components/Ui";
import { dashboardApi } from "../lib/api";
import { useApi } from "../hooks";

const CITY = { minLon: 72.70, maxLon: 72.90, minLat: 21.13, maxLat: 21.26 };
const SATELLITE = new Set([
  "sachin",
  "hazira",
  "ichchapor",
  "olpad",
  "bardoli",
  "kamrej",
  "navsari",
  "vyara",
  "mandvi",
]);

const GAZETTEER: Record<string, [number, number]> = {
  textile: [72.831, 21.195],
  station: [72.841, 21.205],
  ringroad: [72.828, 21.188],
  "ghod dod": [72.808, 21.182],
  majura: [72.822, 21.186],
  rustampura: [72.83, 21.191],
  nanpura: [72.818, 21.193],
  sagrampura: [72.826, 21.19],
  begampura: [72.82, 21.198],
  chowk: [72.819, 21.196],
  makaipul: [72.824, 21.2],
  punagam: [72.88, 21.186],
  vedroad: [72.825, 21.21],
  kapodra: [72.86, 21.21],
  parvat: [72.87, 21.2],
  "yogi chowk": [72.868, 21.208],
  dindoli: [72.86, 21.14],
};

type Feature = {
  properties: { name: string; center: number[] };
  geometry: { coordinates: number[][][] };
};

const features = neighborhoods.features as Feature[];
const polygonNames = new Set(features.map((feature) => feature.properties.name.toLowerCase()));

function project(lon: number, lat: number) {
  return {
    x: ((lon - CITY.minLon) / (CITY.maxLon - CITY.minLon)) * 980,
    y: (1 - (lat - CITY.minLat) / (CITY.maxLat - CITY.minLat)) * 640,
  };
}

function inCity(lon: number, lat: number) {
  return lon >= CITY.minLon && lon <= CITY.maxLon && lat >= CITY.minLat && lat <= CITY.maxLat;
}

export default function SuratMapPage() {
  const navigate = useNavigate();
  const geo = useApi(() => dashboardApi.geo());
  const [hover, setHover] = useState<{ name: string; x: number; y: number } | null>(null);
  const counts = useMemo(() => {
    const map = new Map<string, { count: number; avg: number; products: string[] }>();
    for (const entry of geo.data?.data ?? []) {
      map.set(entry.neighborhood.toLowerCase(), {
        count: entry.count,
        avg: entry.avg_severity,
        products: entry.top_products || [],
      });
    }
    return map;
  }, [geo.data]);

  const openPlace = (name: string) => {
    navigate(`/intel?neighborhood=${encodeURIComponent(name.toLowerCase())}`);
  };

  const satelliteRows = useMemo(() => {
    const rows = [...SATELLITE].map((name) => ({
      name,
      stats: counts.get(name),
    }));
    return rows.sort((a, b) => (b.stats?.count || 0) - (a.stats?.count || 0));
  }, [counts]);

  const cityList = useMemo(() => {
    const names = new Set<string>([
      ...features.map((feature) => feature.properties.name.toLowerCase()),
      ...Object.keys(GAZETTEER),
    ]);
    return [...names]
      .filter((name) => !SATELLITE.has(name))
      .map((name) => ({ name, stats: counts.get(name) }))
      .sort((a, b) => (b.stats?.count || 0) - (a.stats?.count || 0) || a.name.localeCompare(b.name));
  }, [counts]);

  return (
    <div>
      <PageHeader
        eyebrow="INVESTIGATE"
        title="Surat map"
        description="City-scale schematic with a side index. Satellite towns stay off the canvas so labels do not collide."
      />
      <DataState loading={geo.loading} error={geo.error} retry={geo.reload} code={geo.errorCode}>
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_280px]">
          <div className="relative overflow-hidden rounded-xl border border-border bg-surface">
            <svg viewBox="0 0 980 640" className="h-[min(74vh,680px)] w-full">
              {features.map((feature) => {
                const key = feature.properties.name.toLowerCase();
                const stats = counts.get(key);
                const points = feature.geometry.coordinates[0]
                  .map(([lon, lat]) => {
                    const point = project(lon, lat);
                    return `${point.x},${point.y}`;
                  })
                  .join(" ");
                const center = project(feature.properties.center[0], feature.properties.center[1]);
                return (
                  <g
                    key={feature.properties.name}
                    className="cursor-pointer"
                    onClick={() => openPlace(key)}
                    onPointerEnter={() => setHover({ name: key, x: center.x, y: center.y })}
                    onPointerLeave={() => setHover(null)}
                  >
                    <polygon
                      points={points}
                      fill={stats ? `rgba(46,230,199,${Math.min(0.16 + stats.count / 18, 0.62)})` : "#15202b"}
                      stroke={hover?.name === key ? "#2ee6c7" : "#243140"}
                      strokeWidth={hover?.name === key ? 2 : 1}
                    />
                    <text
                      x={center.x}
                      y={center.y}
                      fill="#e7eef4"
                      fontSize="11"
                      textAnchor="middle"
                    >
                      {feature.properties.name}
                    </text>
                  </g>
                );
              })}
              {Object.entries(GAZETTEER)
                .filter(([name, center]) => !polygonNames.has(name) && inCity(center[0], center[1]))
                .map(([name, center]) => {
                  const point = project(center[0], center[1]);
                  const stats = counts.get(name);
                  return (
                    <g
                      key={name}
                      className="cursor-pointer"
                      onClick={() => openPlace(name)}
                      onPointerEnter={() => setHover({ name, x: point.x, y: point.y })}
                      onPointerLeave={() => setHover(null)}
                    >
                      <circle cx={point.x} cy={point.y} r={stats ? 5 : 3.5} fill={stats ? "#f5c16c" : "#8aa0b2"} />
                    </g>
                  );
                })}
            </svg>
            {hover && (
              <div className="pointer-events-none absolute top-3 left-3 max-w-xs rounded-lg border border-border bg-bg/95 px-3 py-2 text-xs">
                <p className="font-semibold capitalize">{hover.name}</p>
                <p className="text-muted">
                  {counts.get(hover.name)
                    ? `${counts.get(hover.name)?.count} records · avg ${counts.get(hover.name)?.avg}`
                    : "No geo-tagged intel yet"}
                </p>
                {!!counts.get(hover.name)?.products.length && (
                  <p className="mt-1 text-navy">{counts.get(hover.name)?.products.slice(0, 4).join(", ")}</p>
                )}
              </div>
            )}
          </div>
          <aside className="space-y-4">
            <section className="rounded-xl border border-border bg-surface p-4">
              <h2 className="mb-2 text-sm font-semibold">City neighbourhoods</h2>
              <ul className="max-h-[46vh] space-y-1 overflow-y-auto text-sm">
                {cityList.map((row) => (
                  <li key={row.name}>
                    <button
                      className="flex w-full items-center justify-between rounded px-2 py-1 text-left hover:bg-raised"
                      onClick={() => openPlace(row.name)}
                    >
                      <span className="capitalize">{row.name}</span>
                      <span className="font-mono text-xs text-muted">{row.stats?.count ?? 0}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
            <section className="rounded-xl border border-border bg-surface p-4">
              <h2 className="mb-2 text-sm font-semibold">Satellite towns</h2>
              <ul className="space-y-1 text-sm">
                {satelliteRows.map((row) => (
                  <li key={row.name}>
                    <button
                      className="flex w-full items-center justify-between rounded px-2 py-1 text-left hover:bg-raised"
                      onClick={() => openPlace(row.name)}
                    >
                      <span className="capitalize">{row.name}</span>
                      <span className="font-mono text-xs text-muted">{row.stats?.count ?? 0}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          </aside>
        </div>
        {!geo.data?.data?.length && (
          <div className="mt-4">
            <EmptyState
              title="No geo heat yet"
              detail="Neighbourhoods remain on the map; counts appear after live intel is processed."
            />
          </div>
        )}
      </DataState>
    </div>
  );
}
