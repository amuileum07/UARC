import { useRef, useState } from "react";
import { NumberField } from "../../components/Fields";
import { desktopApi } from "../../lib/bridge";
import type {
  OpenRocketImport,
  OpenRocketOptions,
  RocketDesign,
} from "../../lib/types";
import { useWorkspace } from "../../workspace";

export function OpenRocketImporter() {
  const w = useWorkspace();
  const latest = useRef(w.design);
  latest.current = w.design;
  const [busy, setBusy] = useState(false);
  const [trigger, setTrigger] = useState<"none" | "apogee" | "altitude">(
    "none",
  );
  const [altitude, setAltitude] = useState(200);
  const [pending, setPending] = useState<{
    result: OpenRocketImport;
    source: RocketDesign;
    name: string;
  } | null>(null);
  const [message, setMessage] = useState("");
  return (
    <details>
      <summary>OpenRocket 가져오기 (.ork)</summary>
      <p className="muted">
        현재 발사 환경·비행·모터·항력 설정을 사용해 부품을 변환합니다. 파일의
        비행 설정을 자동 추정하지 않습니다.
      </p>
      <label className="field">
        가져올 낙하산의 전개 조건
        <select
          value={trigger}
          onChange={(event) => {
            if (["none", "apogee", "altitude"].includes(event.target.value))
              setTrigger(event.target.value as typeof trigger);
          }}
        >
          <option value="none">지정 안함 · 낙하산이 없는 설계</option>
          <option value="apogee">최고점</option>
          <option value="altitude">하강 중 지정 AGL 고도</option>
        </select>
      </label>
      {trigger === "altitude" && (
        <NumberField
          label="전개 고도"
          unit="m AGL"
          value={altitude}
          onChange={setAltitude}
        />
      )}
      <button
        type="button"
        disabled={busy || w.previewState !== "ready"}
        onClick={() => {
          setBusy(true);
          setMessage("");
          void w.act(async () => {
            try {
              const source = w.design;
              const api = await desktopApi();
              const asset = await api.select_input_file();
              if (!asset) return;
              const options: OpenRocketOptions = {
                environment: source.environment,
                flight: source.flight,
                power_off_drag: source.power_off_drag,
                power_on_drag: source.power_on_drag,
                motor: source.motor,
                motor_position: source.motor_position,
                tanks: source.tanks,
                parachute_trigger:
                  trigger === "none"
                    ? null
                    : trigger === "apogee"
                      ? "apogee"
                      : altitude,
              };
              const result = await api.import_openrocket(
                asset.path,
                JSON.stringify(options),
              );
              if (latest.current === source)
                setPending({ result, source, name: asset.original_name });
              else
                setMessage(
                  "처리 중 설계가 바뀌었습니다. 파일을 다시 선택하세요.",
                );
            } finally {
              setBusy(false);
            }
          });
        }}
      >
        {busy ? "변환 중…" : ".ork 선택 · 변환 미리보기"}
      </button>
      {pending && (
        <div className="notice">
          <strong>{pending.name}</strong>
          <p>
            {pending.result.design.name} ·{" "}
            {pending.result.design.components.length}개 부품
          </p>
          {pending.result.warnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
          {pending.source !== w.design && (
            <p>설정이 바뀌었습니다. 다시 가져오세요.</p>
          )}
          <button
            type="button"
            disabled={pending.source !== w.design}
            onClick={() => w.replace(pending.result.design)}
          >
            이 설계 적용
          </button>
        </div>
      )}
      <p role="status">{message}</p>
    </details>
  );
}
