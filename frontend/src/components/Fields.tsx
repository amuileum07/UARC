import { useEffect, useId, useState } from "react";
import { useWorkspace } from "../workspace";

export function NumberField({
  label,
  value,
  onChange,
  unit = "",
  integer = false,
  readOnly = false,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  unit?: string;
  integer?: boolean;
  readOnly?: boolean;
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
    if (!focused || readOnly) setText(String(value));
  }, [value, focused, readOnly]);
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
          readOnly={readOnly}
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
