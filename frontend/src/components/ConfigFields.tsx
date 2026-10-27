import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import { desktopApi } from "../lib/bridge";
import {
  fieldLabels,
  fieldUnit,
  matchesSchema,
  parseNumericTable,
  resolveSchema,
  seedValue,
  variants,
} from "../lib/forms";
import type { InputSchema } from "../lib/forms";
import { useWorkspace } from "../workspace";
import { NumberField } from "./Fields";

const files = new Set([
  "thrust_source",
  "power_off_drag",
  "power_on_drag",
  "pressure",
  "temperature",
  "wind_u",
  "wind_v",
  "liquid_mass",
  "gas_mass",
  "atmosphere_file",
]);
const stateLabels = [
  "x",
  "y",
  "z (ASL)",
  "vx",
  "vy",
  "vz",
  "e0",
  "e1",
  "e2",
  "e3",
  "ω1",
  "ω2",
  "ω3",
];
function branchLabel(schema: InputSchema, key: string) {
  if (schema.type === "null") return "자동 · 미지정";
  if (schema.const === false) return "사용 안함";
  if (schema.const === "apogee") return "최고점";
  if (schema.type === "number" || schema.type === "integer")
    return key === "trigger" ? "하강 중 지정 AGL 고도 (m)" : "단일 값";
  if (schema.type === "string")
    return files.has(key) ? "파일" : "이름으로 지정";
  if (schema.type === "array") {
    if (schema.items?.type === "array") return "수치 표";
    if (key.includes("inertia"))
      return schema.maxItems === 3 ? "주축 3성분" : "전체 6성분";
    return "성분별 값 · 구간";
  }
  return "직접 지정";
}
function NumericTable({
  value,
  path,
  label,
  axis,
}: {
  value: unknown[][];
  path: string[];
  label: string;
  axis: string;
}) {
  const w = useWorkspace();
  const id = useId();
  const original = value.map((row) => row.join(", ")).join("\n");
  const [text, setText] = useState(original);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!dirty) setText(original);
  }, [original, dirty]);
  useEffect(() => {
    w.fieldIssue(
      `field:${id}`,
      dirty ? `${label}: 표의 변경 내용을 적용하세요.` : "",
    );
    return () => w.fieldIssue(`field:${id}`, "");
  }, [dirty, id, label, w.fieldIssue]);
  return (
    <div>
      <label className="field">
        {axis} · 각 행에 x, y
        <textarea
          className="numeric-table-input"
          value={text}
          rows={6}
          spellCheck={false}
          aria-invalid={!!error}
          onChange={(event) => {
            setText(event.target.value);
            setDirty(true);
            setError("");
          }}
        />
      </label>
      <p className="muted">
        숫자 두 열을 붙여넣을 수 있습니다. x는 증가 순서, 최대 4096행입니다.
      </p>
      <button
        type="button"
        disabled={!dirty}
        onClick={() => {
          try {
            w.edit(path, parseNumericTable(text));
            setDirty(false);
            setError("");
          } catch (reason) {
            setError(reason instanceof Error ? reason.message : String(reason));
          }
        }}
      >
        표 적용
      </button>
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
function Mapping({ value, path }: { value: object; path: string[] }) {
  const w = useWorkspace();
  const [key, setKey] = useState("");
  return (
    <div>
      {Object.entries(value).map(([name, item]) => (
        <div key={name} className="mapping-row">
          <label className="field">
            {name}
            <input
              value={typeof item === "string" ? item : ""}
              placeholder="미지정"
              onChange={(event) =>
                w.edit([...path, name], event.target.value || null)
              }
            />
          </label>
          <button
            type="button"
            aria-label={`${name} 매핑 삭제`}
            onClick={() =>
              w.edit(
                path,
                Object.fromEntries(
                  Object.entries(value).filter(([entry]) => entry !== name),
                ),
              )
            }
          >
            삭제
          </button>
        </div>
      ))}
      <label className="field">
        추가할 변수 이름
        <input
          value={key}
          maxLength={128}
          onChange={(event) => setKey(event.target.value)}
        />
      </label>
      <button
        type="button"
        disabled={
          !key.trim() ||
          ["__proto__", "prototype", "constructor"].includes(key.trim()) ||
          Object.hasOwn(value, key.trim())
        }
        onClick={() => {
          w.edit(path, { ...value, [key.trim()]: null });
          setKey("");
        }}
      >
        매핑 추가
      </button>
    </div>
  );
}
export function ConfigField({
  schema,
  value,
  path,
}: {
  schema: InputSchema;
  value: unknown;
  path: string[];
}) {
  const w = useWorkspace();
  const key = path.at(-1) || "";
  const label = fieldLabels[key] || schema.title || key;
  let options = variants(schema, w.schema);
  // Editable component designs are axial; 3D positions are only for raw solver assemblies.
  if (key === "position" && path[0] === "components")
    options = options.filter((item) => item.type !== "array");
  const index = Math.max(
    0,
    options.findIndex((item) => matchesSchema(value, item)),
  );
  const selected = options[index];
  const unit = fieldUnit(key);
  const change = (next: unknown) => w.edit(path, next);
  const [picking, setPicking] = useState(false);
  const latestDesign = useRef(w.design);
  latestDesign.current = w.design;
  const pickFile = () => {
    const source = w.design;
    setPicking(true);
    void w.act(async () => {
      try {
        const file = await (await desktopApi()).select_input_file();
        if (!file) return;
        if (latestDesign.current !== source)
          throw new Error("파일 선택 중 설계가 바뀌었습니다. 다시 선택하세요.");
        change(file.path);
      } finally {
        setPicking(false);
      }
    });
  };
  if (selected.const !== undefined && options.length === 1) return null;
  const title =
    options.length > 1 ? (
      <label className="field">
        {label}
        <select
          value={index}
          onChange={(event) => {
            const next = options[Number(event.target.value)];
            if (
              next.type === "string" &&
              files.has(key) &&
              key !== "atmosphere_file"
            ) {
              pickFile();
              return;
            }
            let seed =
              schema.default !== undefined &&
              matchesSchema(schema.default, next)
                ? structuredClone(schema.default)
                : seedValue(next, w.schema, key);
            const report = w.preview?.result.mass_properties;
            const component =
              path[0] === "components"
                ? w.design.components[Number(path[1])]
                : null;
            const measured = component
              ? report?.components.find((item) => item.id === component.id)
              : report?.effective;
            if (measured && path[0] === "overrides") {
              if (key === "mass" && next.type === "number")
                seed = measured.mass_kg;
              if (key === "center_of_mass" && next.type === "number")
                seed = measured.center_of_mass_m;
            }
            if (measured && key === "mass_override" && next.type === "number")
              seed = measured.mass_kg;
            if (measured && key === "inertia" && next.type === "array")
              seed = measured.inertia_kg_m2.slice(0, next.maxItems || 6);
            if (key === "gravity" && next.type === "number") seed = 9.80665;
            if (key === "pressure" && next.type === "number") seed = 101325;
            if (key === "temperature" && next.type === "number") seed = 288.15;
            if (key === "initial_solution" && Array.isArray(seed))
              seed[3] = w.design.environment.elevation;
            if (
              Array.isArray(seed) &&
              Array.isArray(value) &&
              !seed.some(Array.isArray) &&
              !value.some(Array.isArray)
            )
              seed = seed.map((item, i) => value[i] ?? item);
            change(seed);
          }}
        >
          {options.map((item, i) => (
            <option
              key={`${item.type}:${item.maxItems ?? ""}:${String(item.const)}`}
              value={i}
            >
              {branchLabel(item, key)}
            </option>
          ))}
        </select>
      </label>
    ) : null;
  let input: ReactNode;
  if (selected.const !== undefined || selected.type === "null") input = null;
  else if (selected.enum)
    input = (
      <label className="field">
        {label}
        <select
          value={
            typeof value === "string"
              ? value
              : typeof selected.default === "string"
                ? selected.default
                : selected.enum[0]
          }
          onChange={(event) => change(event.target.value)}
        >
          {selected.enum.map((option) => (
            <option key={option}>{option}</option>
          ))}
        </select>
      </label>
    );
  else if (selected.type === "boolean")
    input = (
      <label className="check">
        <input
          type="checkbox"
          checked={value === true}
          onChange={(event) => change(event.target.checked)}
        />
        {label}
      </label>
    );
  else if (selected.type === "number" || selected.type === "integer")
    input = (
      <NumberField
        label={options.length > 1 ? `${label} 값` : label}
        value={typeof value === "number" ? value : 0}
        unit={key === "trigger" ? "m AGL" : unit}
        integer={selected.type === "integer"}
        onChange={change}
      />
    );
  else if (selected.type === "string")
    input = (
      <>
        <label className="field">
          {options.length > 1 ? `${label} 값` : label}
          <input
            value={typeof value === "string" ? value : ""}
            readOnly={files.has(key) && key !== "atmosphere_file"}
            onChange={(event) => change(event.target.value)}
          />
        </label>
        {files.has(key) && (
          <button type="button" disabled={picking} onClick={pickFile}>
            {picking ? "선택 중…" : "자료 파일 선택"}
          </button>
        )}
      </>
    );
  else if (selected.type === "object") {
    const object = value && typeof value === "object" ? value : {};
    input = selected.properties ? (
      <ConfigFields schema={selected} object={object} path={path} />
    ) : (
      <Mapping value={object} path={path} />
    );
  } else if (selected.type === "array" && Array.isArray(value)) {
    if (value.every((row) => Array.isArray(row)))
      input = (
        <NumericTable
          key={path.join(".")}
          value={value}
          path={path}
          label={label}
          axis={
            key.includes("drag")
              ? "Mach, Cd"
              : key === "thrust_source"
                ? "시간 (s), 추력 (N)"
                : ["pressure", "temperature", "wind_u", "wind_v"].includes(key)
                  ? `고도 (m ASL), 값 (${unit})`
                  : `시간 (s), 값 (${unit})`
          }
        />
      );
    else {
      let names = value.map((_, i) => `${i + 1}`);
      if (key.includes("inertia"))
        names = ["I11", "I22", "I33", "I12", "I13", "I23"];
      if (key === "noise") names = ["평균 (Pa)", "표준편차 (Pa)", "상관계수"];
      if (key === "initial_solution") names = ["t", ...stateLabels];
      if (key === "rtol" || key === "atol") names = stateLabels;
      if (key === "burn_time" || key === "flux_time")
        names = ["시작 (s)", "종료 (s)"];
      if (key === "reshape_thrust_curve")
        names = ["연소 시간 (s)", "총 임펄스 (N·s)"];
      input = (
        <div>
          {value.map((item, i) => (
            <NumberField
              key={names[i]}
              label={names[i]}
              value={typeof item === "number" ? item : 0}
              unit={
                [
                  "initial_solution",
                  "noise",
                  "reshape_thrust_curve",
                  "rtol",
                  "atol",
                ].includes(key)
                  ? ""
                  : unit
              }
              onChange={(next) =>
                change(value.map((old, j) => (i === j ? next : old)))
              }
            />
          ))}
        </div>
      );
    }
  } else input = <p className="field-error">이 값의 입력 형식을 확인하세요.</p>;
  if (selected.type === "array" || selected.type === "object")
    return (
      <fieldset className="config-field" data-field={path.join(".")}>
        <legend>{label}</legend>
        {title}
        {input}
      </fieldset>
    );
  return (
    <div className="config-field" data-field={path.join(".")}>
      {title}
      {input}
    </div>
  );
}
export function ConfigFields({
  object,
  path,
  schemaName,
  schema,
  only,
  omit = [],
}: {
  object: object;
  path: string[];
  schemaName?: string;
  schema?: InputSchema;
  only?: string[];
  omit?: string[];
}) {
  const w = useWorkspace();
  const definition =
    schema || (schemaName ? w.schema.$defs?.[schemaName] : w.schema);
  if (!definition) return <p role="alert">설정 정의를 불러올 수 없습니다.</p>;
  return (
    <>
      {Object.entries(resolveSchema(definition, w.schema).properties || {})
        .filter(
          ([key]) =>
            ![
              "id",
              "schema_version",
              "component_type",
              "surface_type",
              "motor_type",
            ].includes(key) &&
            !omit.includes(key) &&
            (!only || only.includes(key)),
        )
        .map(([key, item]) => {
          if (key === "haack_c" && Reflect.get(object, "kind") !== "haack")
            return null;
          if (key === "power" && Reflect.get(object, "kind") !== "powerseries")
            return null;
          let resolved = resolveSchema(item, w.schema);
          const value: unknown = Object.hasOwn(object, key)
            ? Reflect.get(object, key)
            : item.default;
          if (item.oneOf && value && typeof value === "object") {
            resolved =
              item.oneOf
                .map((branch) => resolveSchema(branch, w.schema))
                .find((branch) =>
                  Object.entries(branch.properties || {}).every(
                    ([name, property]) =>
                      property.const === undefined ||
                      Reflect.get(value, name) === property.const,
                  ),
                ) || resolved;
          }
          return (
            <ConfigField
              key={key}
              schema={resolved}
              value={value}
              path={[...path, key]}
            />
          );
        })}
    </>
  );
}
