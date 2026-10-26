import { useEffect, useId, useState } from "react";
import { useWorkspace } from "../workspace";

export function NumberField({
  label,
  value,
  onChange,
  unit = "",
  integer = false,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  unit?: string;
  integer?: boolean;
}) {
  const id = useId();
  const { fieldIssue } = useWorkspace();
  const [text, setText] = useState(String(value));
  const [focused, setFocused] = useState(false);
  const valid =
    text.trim() !== "" &&
    Number.isFinite(Number(text)) &&
    (!integer || Number.isInteger(Number(text)));
  useEffect(() => {
    if (!focused) setText(String(value));
  }, [value, focused]);
  useEffect(() => {
    fieldIssue(`field:${id}`, valid ? "" : `${label}: 유효한 수를 입력하세요.`);
    return () => fieldIssue(`field:${id}`, "");
  }, [valid, id, label, fieldIssue]);
  return (
    <label className="field" htmlFor={id}>
      <span>{label}</span>
      <span className="input-unit">
        <input
          id={id}
          type="text"
          inputMode={integer ? "numeric" : "decimal"}
          value={text}
          aria-invalid={!valid}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onChange={(event) => {
            const next = event.target.value;
            setText(next);
            if (
              next.trim() &&
              Number.isFinite(Number(next)) &&
              (!integer || Number.isInteger(Number(next)))
            )
              onChange(Number(next));
          }}
        />
        <small>{unit}</small>
      </span>
      {!valid && <small className="field-error">유효한 수를 입력하세요.</small>}
    </label>
  );
}
const labels: Record<string, string> = {
  position: "위치",
  length: "길이",
  outer_radius: "바깥 반경",
  thickness: "두께",
  mass: "질량",
  radius: "반경",
  root_chord: "루트 코드",
  tip_chord: "팁 코드",
  span: "스팬",
  sweep_length: "후퇴 길이",
  sweep_angle: "후퇴각",
  cant_angle: "캔트각",
  n: "핀 개수",
  haack_c: "Haack C",
  rocket_radius: "기체 반경",
  base_radius: "밑면 반경",
  power: "형상 지수",
  bluffness: "끝단 둔화 비율",
  density: "밀도",
  packed_radius: "수납 반경",
  packed_length: "수납 길이",
  canopy_area: "원단 면적",
  attachment_position: "부착 위치",
  line_mass: "줄 질량",
  lag: "전개 지연",
  drag_coefficient: "항력 계수",
  inclination: "발사 경사각",
  heading: "방위각",
  rail_length: "레일 길이",
  max_time: "최대 계산 시간",
  max_time_step: "최대 시간 간격",
};
function unit(key: string) {
  if (/angle|inclination|heading/.test(key)) return "°";
  if (/mass/.test(key)) return "kg";
  if (key === "density") return "kg/m³";
  if (/time|lag/.test(key)) return "s";
  if (key === "canopy_area") return "m²";
  if (/radius|position|length|thickness|chord|span/.test(key)) return "m";
  return "";
}
export function NumericFields({
  object,
  path,
}: {
  object: object;
  path: string[];
}) {
  const { edit } = useWorkspace();
  return (
    <>
      {Object.entries(object).map(([key, value]) => {
        if (typeof value === "number")
          return (
            <NumberField
              key={key}
              label={labels[key] || key}
              unit={unit(key)}
              value={value}
              integer={["n", "grain_number", "discretize"].includes(key)}
              onChange={(next) => edit([...path, key], next)}
            />
          );
        if (
          value &&
          typeof value === "object" &&
          !Array.isArray(value) &&
          !["terrain"].includes(key)
        )
          return (
            <fieldset key={key}>
              <legend>{key}</legend>
              <NumericFields object={value} path={[...path, key]} />
            </fieldset>
          );
        return null;
      })}
    </>
  );
}
