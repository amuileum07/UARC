import { useEffect, useId, useState } from "react";
import { NumberField } from "../../components/Fields";
import { desktopApi } from "../../lib/bridge";
import {
  densityLabels,
  densityUnits,
  finishFromPreset,
  materialFromPreset,
  materialInUse,
} from "../../lib/materials";
import type { MaterialCatalog } from "../../lib/materials";
import type { MaterialConfig, SurfaceFinishConfig } from "../../lib/types";
import { useWorkspace } from "../../workspace";

function useMaterialCatalog() {
  const [catalog, setCatalog] = useState<MaterialCatalog | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void desktopApi()
      .then((api) => api.get_material_catalog())
      .then((value) => {
        if (active) setCatalog(value);
      })
      .catch((reason: unknown) => {
        if (active) setError(String(reason));
      });
    return () => {
      active = false;
    };
  }, []);
  return { catalog, error };
}

function References({
  catalog,
  ids,
}: {
  catalog: MaterialCatalog;
  ids: string[];
}) {
  const w = useWorkspace();
  return (
    <div className="button-row">
      {[...new Set(ids)].map((id) => (
        <button
          key={id}
          type="button"
          title={catalog.sources[id].locator}
          onClick={() =>
            void w.act(async () => {
              await (await desktopApi()).open_material_reference(id);
            })
          }
        >
          {catalog.sources[id].title}
        </button>
      ))}
    </div>
  );
}

export function MaterialsEditor() {
  const w = useWorkspace();
  const { catalog, error } = useMaterialCatalog();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState("");
  const [name, setName] = useState("");
  const [densityType, setDensityType] =
    useState<NonNullable<MaterialConfig["density_type"]>>("bulk");
  const [density, setDensity] = useState("");
  const densityIssueId = useId();
  const [added, setAdded] = useState("");
  const materials = w.design.materials || {};
  const validDensity = Number.isFinite(Number(density)) && Number(density) > 0;
  const canAdd =
    !!name.trim() &&
    name.trim().length <= 128 &&
    validDensity &&
    Object.keys(materials).length < 64;
  const matches =
    catalog?.materials.filter((entry) =>
      `${entry.name} ${catalog.groups[entry.group].name} ${densityLabels[entry.density_type || "bulk"]}`
        .toLocaleLowerCase()
        .includes(query.toLocaleLowerCase().trim()),
    ) || [];
  const preset = matches.find((entry) => entry.id === selected) || matches[0];
  return (
    <>
      <h2>재질</h2>
      <p className="muted">
        밀도는 질량·CG·관성에 반영됩니다. 사용 중인 재질은 삭제하거나 밀도
        단위를 변경할 수 없습니다. 표면 마감은 각 동체·공력면에서 지정합니다.
      </p>
      <details open>
        <summary>재질 라이브러리</summary>
        {error && <p role="alert">재질 목록을 불러오지 못했습니다: {error}</p>}
        {!catalog && !error && (
          <p role="status">재질 목록을 불러오고 있습니다.</p>
        )}
        {catalog && (
          <>
            <p className="muted">
              제조사·공공·학술 자료로 확인한 재질 {catalog.materials.length}종 ·
              자료 확인일 {catalog.checked_on}
            </p>
            <label className="field">
              재질 검색 · 이름 / 종류 / 밀도 단위
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <label className="field">
              라이브러리 재질
              <select
                size={7}
                value={preset?.id || ""}
                onChange={(e) => setSelected(e.target.value)}
              >
                {matches.map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.name} · {entry.density}{" "}
                    {densityUnits[entry.density_type || "bulk"]}
                  </option>
                ))}
              </select>
            </label>
            {!preset && <p role="status">검색 결과가 없습니다.</p>}
            {preset && (
              <>
                <p>{preset.notes}</p>
                <p className="muted">{catalog.groups[preset.group].notes}</p>
                <References catalog={catalog} ids={preset.source_ids} />
                <details>
                  <summary>재질별 물성·표면 자료</summary>
                  <References
                    catalog={catalog}
                    ids={catalog.groups[preset.group].source_ids}
                  />
                  <p className="muted">
                    참고 문서는 각각의 제품·조건에 적용됩니다. 라이브러리 전체의
                    밀도를 제조사가 인증한 것은 아닙니다.
                  </p>
                </details>
                <button
                  type="button"
                  disabled={Object.keys(materials).length >= 64}
                  onClick={() => {
                    const id = crypto.randomUUID().replaceAll("-", "");
                    w.edit(["materials"], {
                      ...materials,
                      [id]: materialFromPreset(preset),
                    });
                    setAdded(`${preset.name}을 설계 재질에 추가했습니다.`);
                  }}
                >
                  선택 재질을 설계에 추가
                </button>
              </>
            )}
            <details>
              <summary>자료 적용 범위 · 미확인 항목</summary>
              {catalog.research_gaps.map((gap) => (
                <p key={gap.name}>
                  <strong>{gap.name}</strong>: {gap.reason}
                </p>
              ))}
            </details>
          </>
        )}
      </details>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!canAdd) return;
          const id = crypto.randomUUID().replaceAll("-", "");
          w.edit(["materials"], {
            ...materials,
            [id]: {
              name: name.trim(),
              density: Number(density),
              density_type: densityType,
            },
          });
          setAdded(`${name.trim()}을 설계 재질에 추가했습니다.`);
          setName("");
          setDensity("");
        }}
      >
        <fieldset>
          <legend>사용자 재질 추가</legend>
          <label className="field">
            새 사용자 재질 이름
            <input
              value={name}
              maxLength={128}
              required
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label className="field">
            새 재질 밀도 종류
            <select
              value={densityType}
              onChange={(event) => {
                setDensityType(event.target.value as typeof densityType);
                setDensity("");
              }}
            >
              {Object.entries(densityLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label} · {densityUnits[value as keyof typeof densityUnits]}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            새 재질 {densityLabels[densityType]}
            <span className="input-unit">
              <input
                type="text"
                inputMode="decimal"
                value={density}
                required
                aria-invalid={density !== "" && !validDensity}
                aria-describedby={densityIssueId}
                onChange={(event) => setDensity(event.target.value)}
              />
              <small>{densityUnits[densityType]}</small>
            </span>
          </label>
          <p id={densityIssueId} className="muted">
            0보다 큰 유한한 값을 입력하세요. 원단은 면밀도, 줄은 선밀도를
            사용합니다. 밀도 종류를 바꾸면 입력값을 다시 지정해야 합니다.
          </p>
          <button type="submit" disabled={!canAdd}>
            사용자 재질 추가
          </button>
          <p className="muted">
            추가한 재질은 이 설계와 함께 저장·내보내집니다. 설계에는 최대 64개의
            재질을 저장할 수 있습니다.
          </p>
        </fieldset>
      </form>
      <p role="status">{added}</p>
      <h3>이 설계의 재질</h3>
      {Object.entries(materials).map(([id, material]) => {
        const used = materialInUse(w.design, id);
        const kind = material.density_type || "bulk";
        const origin = catalog?.materials.find(
          (entry) => entry.id === material.catalog_id,
        );
        return (
          <fieldset key={id}>
            <legend>{material.name}</legend>
            <label className="field">
              이름
              <input
                value={material.name}
                maxLength={128}
                onChange={(e) =>
                  w.edit(["materials", id, "name"], e.target.value)
                }
              />
            </label>
            <label className="field">
              밀도 종류
              <select
                value={kind}
                disabled={used}
                onChange={(e) =>
                  w.edit(["materials", id], {
                    ...material,
                    density_type: e.target.value,
                    catalog_id: null,
                  })
                }
              >
                {Object.entries(densityLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label} · {densityUnits[value as keyof typeof densityUnits]}
                  </option>
                ))}
              </select>
            </label>
            <NumberField
              label={densityLabels[kind]}
              value={material.density}
              unit={densityUnits[kind]}
              onChange={(value) => w.edit(["materials", id, "density"], value)}
            />
            {origin && catalog && (
              <>
                <p className="muted">
                  {origin.density === material.density
                    ? "출처의 참고 밀도"
                    : `사용자 수정값 · 원래 밀도 ${origin.density} ${densityUnits[kind]}`}
                  {` · ${origin.notes}`}
                </p>
                <References catalog={catalog} ids={origin.source_ids} />
              </>
            )}
            <button
              type="button"
              disabled={used}
              onClick={() =>
                w.edit(
                  ["materials"],
                  Object.fromEntries(
                    Object.entries(materials).filter(([key]) => key !== id),
                  ),
                )
              }
            >
              재질 삭제
            </button>
          </fieldset>
        );
      })}
    </>
  );
}

export function SurfaceFinishEditor({
  value,
  path,
}: {
  value?: SurfaceFinishConfig | null;
  path: string[];
}) {
  const w = useWorkspace();
  const { catalog, error } = useMaterialCatalog();
  const original = catalog?.surface_finishes.find(
    (entry) => entry.id === value?.catalog_id,
  );
  const selected = value
    ? original?.roughness_m === value.roughness_m &&
      original.roughness_type === value.roughness_type
      ? original.id
      : "custom"
    : "none";
  const change = (next: SurfaceFinishConfig | null) => w.edit(path, next);
  return (
    <fieldset>
      <legend>외부 표면 마감</legend>
      <label className="field">
        표면 마감 선택
        <select
          value={selected}
          onChange={(e) => {
            if (e.target.value === "none") change(null);
            else if (e.target.value === "custom")
              change(
                value
                  ? { ...value, catalog_id: null }
                  : {
                      name: "사용자 표면",
                      roughness_m: 0,
                      roughness_type: "equivalent_sand_grain",
                    },
              );
            else {
              const preset = catalog?.surface_finishes.find(
                (entry) => entry.id === e.target.value,
              );
              if (preset) change(finishFromPreset(preset));
            }
          }}
        >
          <option value="none">미지정 · 표면 자료 없음</option>
          <option value="custom">직접 입력</option>
          {catalog?.surface_finishes.map((entry) => (
            <option key={entry.id} value={entry.id}>
              {entry.name} · {Number((entry.roughness_m * 1e6).toPrecision(10))}{" "}
              µm
            </option>
          ))}
        </select>
      </label>
      {error && (
        <p role="alert">표면 마감 목록을 불러오지 못했습니다: {error}</p>
      )}
      {value && (
        <>
          <label className="field">
            거칠기 정의
            <select
              value={value.roughness_type}
              onChange={(e) =>
                change({
                  ...value,
                  roughness_type: e.target
                    .value as SurfaceFinishConfig["roughness_type"],
                })
              }
            >
              {value.roughness_type === "openrocket" && (
                <option value="openrocket">
                  기존 파일 · OpenRocket 모델 높이
                </option>
              )}
              <option value="equivalent_sand_grain">
                등가 모래입자 거칠기 · ks
              </option>
              <option value="ra">측정 산술평균 거칠기 · Ra</option>
            </select>
          </label>
          <NumberField
            label="표면 거칠기"
            unit="µm"
            value={Number((value.roughness_m * 1e6).toPrecision(10))}
            onChange={(number) =>
              change({ ...value, roughness_m: number * 1e-6 })
            }
          />
          {original && catalog && (
            <References catalog={catalog} ids={original.source_ids} />
          )}
        </>
      )}
      <p className="muted">
        기본 거칠기 표는 제공하지 않습니다. 완성된 부품의 실측값이나 독립 자료를
        입력하세요. Ra·ks·기존 모델 높이는 자동 변환하지 않습니다. 표면 자료는
        저장되며, 형상 기반 자동 항력 모드에서는 ks를 사용합니다. 직접 입력한
        항력계수·곡선은 변경하지 않습니다.
      </p>
    </fieldset>
  );
}
