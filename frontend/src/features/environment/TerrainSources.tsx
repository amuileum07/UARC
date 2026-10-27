import { useState } from "react";
import { NumberField } from "../../components/Fields";
import { desktopApi } from "../../lib/bridge";
import { alignLaunchElevation, terrainReferences } from "../../lib/terrain";
import type { TerrainGrid, TerrainRequest } from "../../lib/types";
import { useWorkspace } from "../../workspace";

export function TerrainSources() {
  const w = useWorkspace();
  const provider = w.terrainSource;
  const { radius_m: radius, spacing_m: spacing } = w.terrainArea;
  const [apiKey, setApiKey] = useState("");
  const [dataset, setDataset] = useState<TerrainRequest["dataset"]>("SRTMGL1");
  const [reference, setReference] =
    useState<TerrainGrid["reference"]>("unknown");
  const [epsg, setEpsg] = useState<number | null>(null);
  const [heightScale, setHeightScale] = useState<1 | 0.3048>(1);
  const env = w.design.environment;
  const grid = env.terrain;
  const aligned = alignLaunchElevation(env);
  const openPortal = (source: "aws" | "local" | "opentopography") =>
    void w.act(async () => {
      await (await desktopApi()).open_terrain_portal(source);
    });
  return (
    <fieldset disabled={w.terrainBusy}>
      <legend>지형 자료</legend>
      <label className="field">
        고도 자료 소스
        <select
          value={provider}
          disabled={w.terrainBusy}
          onChange={(event) => {
            const value = event.target.value;
            if (
              value !== "aws" &&
              value !== "local" &&
              value !== "opentopography" &&
              value !== "opentopodata"
            )
              return;
            w.setTerrainSource(value);
            if (value === "opentopography") openPortal(value);
          }}
        >
          <option value="aws">AWS Open Data · Terrain Tiles · 기본</option>
          <option value="local">국토정보플랫폼 · 로컬 DEM 원본</option>
          <option value="opentopography">OpenTopography · API 키</option>
          <option value="opentopodata">Open Topo Data · 기존 SRTM90m</option>
        </select>
      </label>
      <NumberField
        label="지형 조회 반경"
        unit="m · 100~5000"
        value={radius}
        onChange={(value) =>
          w.setTerrainArea({ ...w.terrainArea, radius_m: value })
        }
      />
      {provider !== "opentopodata" && (
        <NumberField
          label="목표 표본 간격"
          unit="m · 5~1000"
          value={spacing}
          onChange={(value) =>
            w.setTerrainArea({ ...w.terrainArea, spacing_m: value })
          }
        />
      )}
      {provider === "aws" && (
        <p className="muted">
          발사장 위치가 정해지면 AWS 고도를 자동으로 가져옵니다. AWS 계정·키는
          필요하지 않습니다. 다른 자료는 소스를 변경해 가져오세요.
        </p>
      )}
      {provider === "local" && (
        <>
          <button type="button" onClick={() => openPortal("local")}>
            국토정보플랫폼 다운로드 사이트 열기
          </button>
          <p className="muted">
            내려받은 IMG·GeoTIFF·ASC·HGT에서 현재 발사장 주변을 읽습니다. 파일에
            좌표계가 없을 때만 EPSG를 직접 지정하세요.
          </p>
          <label className="field">
            원본 고도 기준
            <select
              value={reference}
              onChange={(e) =>
                setReference(e.target.value as TerrainGrid["reference"])
              }
            >
              {Object.entries(terrainReferences).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={epsg !== null}
              onChange={(e) => setEpsg(e.target.checked ? 5186 : null)}
            />{" "}
            원본 좌표계 EPSG 직접 지정
          </label>
          {epsg !== null && (
            <NumberField
              label="원본 EPSG 코드"
              unit="자료 설명서 확인"
              value={epsg}
              onChange={setEpsg}
            />
          )}
          <label className="field">
            원본 고도 단위
            <select
              value={heightScale}
              onChange={(e) =>
                setHeightScale(e.target.value === "1" ? 1 : 0.3048)
              }
            >
              <option value="1">m</option>
              <option value="0.3048">ft → m</option>
            </select>
          </label>
        </>
      )}
      {provider === "opentopography" && (
        <>
          <button type="button" onClick={() => openPortal("opentopography")}>
            API 키 발급 사이트 다시 열기
          </button>
          <p className="muted">
            portal.opentopography.org → My Account에서 발급합니다. 키는
            설정·설계·실행 파일에 저장하지 않습니다.
          </p>
          <label className="field">
            OpenTopography API 키
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              maxLength={256}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </label>
          <label className="field">
            고도 데이터셋
            <select
              value={dataset}
              onChange={(e) =>
                setDataset(e.target.value as TerrainRequest["dataset"])
              }
            >
              <option value="SRTMGL1">SRTM GL1 · 30m · EGM96</option>
              <option value="SRTMGL3">SRTM GL3 · 90m · EGM96</option>
              <option value="COP30">Copernicus DSM · 30m · EGM2008</option>
            </select>
          </label>
        </>
      )}
      <button
        type="button"
        disabled={
          w.terrainBusy ||
          radius < 100 ||
          radius > 5000 ||
          (provider !== "opentopodata" && (spacing < 5 || spacing > 1000)) ||
          (provider === "opentopography" && !apiKey.trim()) ||
          (provider === "local" &&
            epsg !== null &&
            (!Number.isInteger(epsg) || epsg < 1024 || epsg > 100000))
        }
        onClick={() =>
          void w.loadTerrain(
            {
              provider,
              radius_m: radius,
              spacing_m: provider === "opentopodata" ? 30 : spacing,
              dataset,
              api_key: provider === "opentopography" ? apiKey.trim() : "",
            },
            provider === "local"
              ? { reference, crs_epsg: epsg, height_scale: heightScale }
              : undefined,
          )
        }
      >
        {w.terrainBusy
          ? "고도 자료 가져오는 중…"
          : provider === "aws"
            ? "AWS 지형 새로고침"
            : provider === "local"
              ? "DEM 파일 선택하여 가져오기"
              : `주변 ${(2 * radius) / 1000} km 고도 자료 가져오기`}
      </button>
      <p className="muted">
        최대 257×257 표본으로 보존합니다. 지도와 지형 충돌 계산은 같은 고도를
        사용합니다. 온라인 조회는 현재 좌표를 서비스에 전송합니다.
      </p>
      {w.terrainAutoError && (
        <p className="notice warning" role="status">
          {w.terrainAutoError}
        </p>
      )}
      {grid && (
        <p className="muted">
          {grid.source.split(";")[0]} · {grid.heights.length}×
          {grid.heights[0].length} · 실제 표본 간격{" "}
          {grid.sampling_distance_m.toFixed(1)} m ·{" "}
          {terrainReferences[grid.reference]}
        </p>
      )}
      {env.elevation_mode !== "terrain" && (
        <button
          type="button"
          disabled={w.terrainBusy || !aligned}
          onClick={() => {
            if (!aligned) return;
            w.edit(["environment"], {
              ...aligned,
              terrain_mode: "terrain",
            });
          }}
        >
          발사 고도·기준을 지형 + 발사대로 맞추기
        </button>
      )}
      {!grid && (
        <p className="muted">
          지형을 가져오면 발사 고도를 지면에 맞출 수 있습니다.
        </p>
      )}
      {grid?.reference === "unknown" && (
        <p className="notice" role="status">
          원본 고도 기준이 미지정입니다. 자료 설명서에서 확인한 뒤 다시 가져와야
          지형 충돌 계산에 사용할 수 있습니다.
        </p>
      )}
      <p className="muted">
        VWorld 위성영상은 지도 상단의 배경 소스에서 선택합니다. 위성영상은 고도
        자료와 별개입니다.
      </p>
    </fieldset>
  );
}
