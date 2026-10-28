import { useRef, useState } from "react";
import { ConfigFields } from "../../components/ConfigFields";
import { createMotor, createTank, motorLabels } from "../../lib/templates";
import type { MotorKind } from "../../lib/templates";
import type { RocketDesign } from "../../lib/types";
import { useWorkspace } from "../../workspace";
import { DragEditor } from "./DragEditor";

export function MotorEditor() {
  const w = useWorkspace();
  const [tab, setTab] = useState<"motor" | "tanks">("motor");
  const [tankRevision, setTankRevision] = useState(0);
  const cache = useRef(
    new Map<
      string,
      { motor: RocketDesign["motor"]; tanks: RocketDesign["tanks"] }
    >(),
  );
  const motor = w.design.motor;
  const kind = motor?.motor_type || (motor ? "generic" : "none");
  const canTank = kind === "liquid" || kind === "hybrid";
  const schemaName = {
    generic: "GenericMotorConfig",
    solid: "SolidMotorConfig",
    liquid: "LiquidMotorConfig",
    hybrid: "HybridMotorConfig",
    none: "",
  }[kind];
  return (
    <>
      <h2>모터 · 추진제</h2>
      <label className="field">
        모터 종류
        <select
          value={kind}
          onChange={(event) => {
            cache.current.set(kind, {
              motor: structuredClone(motor),
              tanks: structuredClone(w.design.tanks),
            });
            const next = event.target.value;
            const saved = cache.current.get(next);
            if (saved) {
              w.edit(["motor"], saved.motor);
              w.edit(["tanks"], saved.tanks || []);
              return;
            }
            if (next === "none") {
              w.edit(["motor"], null);
              w.edit(["tanks"], []);
              return;
            }
            if (!Object.hasOwn(motorLabels, next)) return;
            const type = next as MotorKind;
            w.edit(["motor"], createMotor(type, motor));
            w.edit(
              ["tanks"],
              type === "liquid" || type === "hybrid" ? [createTank()] : [],
            );
          }}
        >
          <option value="none">모터 없음 · 무추진 비행</option>
          {Object.entries(motorLabels).map(([type, label]) => (
            <option key={type} value={type}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <p className="muted">
        종류를 바꾸면 공통 입력을 유지합니다. 새로 생기는 값은 예시이므로 실제
        모터 사양으로 수정하세요. 같은 편집 화면에서 이전 종류로 돌아가면 해당
        설정을 복원합니다.
      </p>
      <fieldset className="segmented" aria-label="추진 설정">
        <button
          type="button"
          aria-pressed={tab === "motor"}
          onClick={() => setTab("motor")}
        >
          모터
        </button>
        <button
          type="button"
          aria-pressed={tab === "tanks"}
          onClick={() => setTab("tanks")}
        >
          탱크
        </button>
      </fieldset>
      {tab === "motor" && motor && (
        <>
          <ConfigFields
            schema={w.schema}
            object={w.design}
            path={[]}
            only={["motor_position"]}
          />
          <ConfigFields
            key={kind}
            schemaName={schemaName}
            object={motor}
            path={["motor"]}
          />
          <p className="muted">
            건조 질량·관성은 추진제를 제외합니다. 위치는 모터 좌표계 기준이며
            장착 위치는 기체 좌표계 기준입니다.
          </p>
        </>
      )}
      {tab === "tanks" && (
        <div key={tankRevision}>
          {!canTank ? (
            <p className="muted">탱크는 액체·하이브리드 모터에서 사용합니다.</p>
          ) : (
            <>
              {(w.design.tanks || []).map((tank, i) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: no reordering; deleting remounts the list so drafts cannot move to another tank.
                <fieldset key={`${kind}:${i}`}>
                  <legend>탱크 {i + 1}</legend>
                  <ConfigFields
                    object={tank}
                    schemaName="MassBasedTankConfig"
                    path={["tanks", String(i)]}
                  />
                  <button
                    type="button"
                    disabled={(w.design.tanks?.length || 0) <= 1}
                    onClick={() => {
                      setTankRevision((old) => old + 1);
                      w.edit(
                        ["tanks"],
                        w.design.tanks?.filter((_, j) => i !== j),
                      );
                    }}
                  >
                    이 탱크 삭제
                  </button>
                </fieldset>
              ))}
              <button
                type="button"
                onClick={() =>
                  w.edit(["tanks"], [...(w.design.tanks || []), createTank()])
                }
              >
                탱크 추가
              </button>
              <p className="muted">
                질량 곡선은 시간(s)·질량(kg)입니다. 밀도·질량·치수를 실제 값으로
                지정하고 모터 연소 시간 전체를 포함하세요.
              </p>
            </>
          )}
        </div>
      )}
    </>
  );
}
export function AssemblyEditor() {
  const w = useWorkspace();
  return (
    <>
      <h2>로켓 전체</h2>
      <ConfigFields
        schema={w.schema}
        object={w.design}
        path={[]}
        only={["name"]}
      />
      <DragEditor />
      <ConfigFields
        schema={w.schema}
        object={w.design}
        path={[]}
        only={["rail_buttons", "overrides"]}
      />
      <p className="muted">
        실측 질량·CG·관성은 모터를 제외한 기체 전체 값입니다.
      </p>
    </>
  );
}
export function FlightEditor() {
  const w = useWorkspace();
  const basic = [
    "name",
    "rail_length",
    "inclination",
    "heading",
    "terminate_on_apogee",
    "max_time",
  ];
  return (
    <>
      <h2>비행 설정</h2>
      <ConfigFields
        object={w.design.flight}
        schemaName="FlightConfig"
        path={["flight"]}
        only={basic}
      />
      <details>
        <summary>계산기 · 초기 상태</summary>
        <ConfigFields
          object={w.design.flight}
          schemaName="FlightConfig"
          path={["flight"]}
          omit={basic}
        />
        <p className="muted">
          초기 상태: t(s), x/y/z(m, z는 ASL), vx/vy/vz(m/s), 단위 쿼터니언
          e0~e3, 각속도 ω1~ω3(rad/s). 허용 오차 13성분은 시간 t를 제외한 같은
          순서입니다.
        </p>
        <p className="muted">
          최소 시간 간격은 LSODA에서만 사용합니다. 다른 계산기에서는 적용되지
          않습니다.
        </p>
      </details>
    </>
  );
}
export function ExternalAtmosphereFields() {
  const w = useWorkspace();
  const env = w.design.environment;
  return (
    <>
      <ConfigFields
        schemaName="EnvironmentConfig"
        object={env}
        path={["environment"]}
        only={[
          "atmosphere_file",
          "atmosphere_dictionary",
          "pressure_conversion_factor",
          ...(env.atmosphere_type === "ensemble" ? ["ensemble_member"] : []),
        ]}
      />
      <p className="muted">
        RocketPy 직접 자료 모드는 실행 시 원격 자료를 읽을 수 있습니다. 현재
        입력한 좌표·시각과 자료 변수를 확인하세요. 수치를 고정해 보존하려면 위의
        기상 가져오기나 CSV·Excel을 사용하세요.
      </p>
    </>
  );
}
