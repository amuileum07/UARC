import { useEffect, useRef, useState } from "react";
import { desktopApi } from "../../lib/bridge";
import type { LocationResult } from "../../lib/types";
import { useWorkspace } from "../../workspace";

export function SiteSearch() {
  const w = useWorkspace();
  const [query, setQuery] = useState("");
  const [country, setCountry] = useState<"KR" | "all">("KR");
  const revision = useRef(0);
  const [results, setResults] = useState<LocationResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(
    () => () => {
      revision.current++;
    },
    [],
  );
  return (
    <section aria-label="발사장 선택">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (busy || query.trim().length < 2) return;
          const requested = ++revision.current;
          setBusy(true);
          setMessage("");
          void (async () => {
            try {
              const found = await (
                await desktopApi()
              ).search_locations(JSON.stringify({ query, country }));
              if (revision.current === requested) {
                setResults(found);
                setMessage(
                  found.length
                    ? `${found.length}개 장소 · 사용할 위치를 선택하세요.`
                    : "검색 결과가 없습니다. 시·군·구를 함께 입력하거나 지도에서 선택하세요.",
                );
              }
            } catch (error) {
              if (revision.current === requested)
                setMessage(
                  error instanceof Error ? error.message : String(error),
                );
            } finally {
              setBusy(false);
            }
          })();
        }}
      >
        <label className="field">
          장소명 검색
          <input
            type="search"
            maxLength={120}
            value={query}
            placeholder="예: 울산, UNIST, 유니스트길 50"
            onKeyDown={(event) => {
              if (event.key === "Enter" && event.nativeEvent.isComposing)
                event.preventDefault();
            }}
            onChange={(event) => {
              revision.current++;
              setQuery(event.target.value);
              setResults([]);
              setMessage("");
            }}
          />
        </label>
        <label className="field">
          검색 범위
          <select
            value={country}
            onChange={(event) => {
              revision.current++;
              setCountry(event.target.value === "all" ? "all" : "KR");
              setResults([]);
              setMessage("");
            }}
          >
            <option value="KR">대한민국</option>
            <option value="all">전 세계</option>
          </select>
        </label>
        <button type="submit" disabled={busy || query.trim().length < 2}>
          {busy ? "검색 중…" : "장소 검색"}
        </button>
      </form>
      <p className="muted">
        한국어·영문 장소명과 도로명 주소를 검색합니다. 검색 위치는 장소의
        대표점이므로 정확한 발사점은 지도에서 선택하세요.
      </p>
      <p className="caption">
        Photon / ©{" "}
        <a
          className="text-button"
          href="https://www.openstreetmap.org/copyright"
          target="_blank"
          rel="noreferrer"
        >
          OpenStreetMap
        </a>
        {" · "}도시 검색 보완: Open-Meteo / GeoNames
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
          <small>
            {place.category && `${place.category} · `}
            {place.region}
          </small>
          <small>
            {place.latitude.toFixed(5)}°, {place.longitude.toFixed(5)}° ·{" "}
            {place.timezone || "시간대 확인 필요"} · {place.source}
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
