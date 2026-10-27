import { useRef, useState } from "react";
import { desktopApi } from "../../lib/bridge";
import type { LocationResult } from "../../lib/types";
import { useWorkspace } from "../../workspace";

export function SiteSearch() {
  const w = useWorkspace();
  const [query, setQuery] = useState("");
  const latestQuery = useRef(query);
  latestQuery.current = query;
  const [results, setResults] = useState<LocationResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  return (
    <section aria-label="발사장 선택">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (busy || query.trim().length < 2) return;
          const requested = query;
          setBusy(true);
          setMessage("");
          void w.act(async () => {
            try {
              const found = await (
                await desktopApi()
              ).search_locations(JSON.stringify({ query: requested }));
              if (latestQuery.current === requested) {
                setResults(found);
                setMessage(
                  found.length
                    ? `${found.length}개 장소 · 사용할 위치를 선택하세요.`
                    : "검색 결과가 없습니다. 영문 지명이나 지도 선택을 사용하세요.",
                );
              }
            } finally {
              setBusy(false);
            }
          });
        }}
      >
        <label className="field">
          장소명 검색
          <input
            type="search"
            maxLength={120}
            value={query}
            placeholder="예: 울산 / Ulsan"
            onChange={(event) => {
              setQuery(event.target.value);
              setResults([]);
              setMessage("");
            }}
          />
        </label>
        <button type="submit" disabled={busy || query.trim().length < 2}>
          {busy ? "검색 중…" : "장소 검색"}
        </button>
      </form>
      <p className="muted">
        Open-Meteo / GeoNames 지명 검색. 도시·우편번호 중심이며 정확한 발사점은
        지도에서 선택하세요.
      </p>
      <p role="status">{message}</p>
      {results.map((place) => (
        <button
          type="button"
          className="document"
          key={place.id}
          onClick={() => {
            w.placeSite(place.latitude, place.longitude);
            setResults([]);
            setMessage(
              `${place.name} 위치를 적용했습니다. 발사 고도와 시간대를 확인하세요.`,
            );
          }}
        >
          {place.name}
          <small>{place.region}</small>
          <small>
            {place.latitude.toFixed(5)}°, {place.longitude.toFixed(5)}° ·{" "}
            {place.timezone}
          </small>
        </button>
      ))}
      <button
        type="button"
        aria-pressed={w.pickingSite}
        onClick={() => {
          w.setMapMode("design");
          w.setPickingSite(!w.pickingSite);
        }}
      >
        {w.pickingSite ? "지도 선택 취소" : "지도에서 발사점 선택"}
      </button>
      <p className="muted">
        위치 선택은 WGS84로 적용합니다. 고도는 유지하며 이전 지형·지오이드 값은
        해제됩니다.
      </p>
    </section>
  );
}
