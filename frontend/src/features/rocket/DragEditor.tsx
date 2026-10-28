import { ConfigFields } from "../../components/ConfigFields";
import { useWorkspace } from "../../workspace";

export function DragEditor() {
  const w = useWorkspace();
  const automatic = w.design.automatic_drag != null;
  const highSpeed = w.design.automatic_drag?.model === "compressible_v1";
  const report =
    w.previewState === "ready" && w.preview?.design === w.design
      ? w.preview.result.mass_properties.aerodynamics
      : null;
  return (
    <fieldset>
      <legend>기체 항력</legend>
      <label className="field">
        항력 계산 방식
        <select
          value={w.design.automatic_drag?.model ?? "manual"}
          onChange={(event) => {
            const model = event.target.value;
            w.edit(
              ["automatic_drag"],
              model === "subsonic_v1" || model === "compressible_v1"
                ? { model }
                : null,
            );
          }}
        >
          <option value="manual">직접 입력 · 측정 곡선</option>
          <option value="compressible_v1">
            형상 기반 Cd₀ · Mach 0–3 예비 추정
          </option>
          <option value="subsonic_v1">형상 기반 Cd₀ · 기존 아음속 모델</option>
        </select>
      </label>
      {automatic ? (
        <>
          {highSpeed ? (
            <p className="muted">
              Mach 0–3의 영 받음각 축방향 항력 추정입니다. 원뿔형 노즈
              (길이/직경 3–10), 동일 직경의 연속 동체, 사다리꼴 핀 3·4개를
              지원합니다. 핀은 양 끝이 뾰족한 대칭 쐐기 단면을 가정하며,
              두께/시위는 전체 폭에서 5% 이하, 중간 시위선 후퇴각은 ±10°
              이내여야 합니다. 핀 질량·3D 형상은 평판 근사이므로, 실제 다듬은
              핀은 부품의 실측 질량을 입력하세요.
            </p>
          ) : (
            <p className="muted">
              기존 Mach 0–0.7 모델입니다. 뾰족한 노즈와 유선형 단면의 무경사
              핀을 가정합니다. 천음속·초음속 항력은 포함하지 않습니다.
            </p>
          )}
          <p className="muted">
            {highSpeed &&
              "초음속 원뿔 압력 계산은 NASA 기준표와 대조했습니다. 천음속·핀 포함 전체 항력의 독립 실험 검증은 완료되지 않았습니다. "}
            핀 끝·부품 간섭, 돌출물, 받음각 증가와 박리 항력은 포함하지
            않습니다. 지원 범위를 넘는 형상·속도는 오류로 중단됩니다.
          </p>
          <p className="muted">
            부품 표면의 등가 모래 거칠기 ks를 반영합니다. 미지정 표면은 매끈한
            표면으로 가정하며 Ra는 자동 변환하지 않습니다. 실제 비행에서는
            설정한 위치·기상의 레이놀즈수를 매 시간 적용합니다.
          </p>
          {report ? (
            <>
              <table>
                <caption>
                  기준 대기 {report.reference_temperature_k.toFixed(2)} K ·{" "}
                  {report.reference_pressure_pa.toFixed(0)} Pa, A ={" "}
                  {report.reference_area_m2.toPrecision(5)} m²
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Mach</th>
                    <th scope="col">연소 후 C_D</th>
                    <th scope="col">연소 중 C_D</th>
                  </tr>
                </thead>
                <tbody>
                  {report.samples.map((sample) => (
                    <tr key={sample.mach}>
                      <th scope="row">{sample.mach.toFixed(1)}</th>
                      <td>{sample.total_off.toFixed(4)}</td>
                      <td>{sample.total_on.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <details>
                <summary>항력 성분 · 모델 가정</summary>
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Mach</th>
                      <th scope="col">마찰</th>
                      <th scope="col">형상 보정</th>
                      {highSpeed && <th scope="col">노즈 압력</th>}
                      {highSpeed && <th scope="col">핀 압력</th>}
                      <th scope="col">기저 · 연소 후</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.samples.map((sample) => (
                      <tr key={sample.mach}>
                        <th scope="row">{sample.mach.toFixed(1)}</th>
                        <td>{sample.skin_friction.toFixed(4)}</td>
                        <td>{sample.form.toFixed(4)}</td>
                        {highSpeed && (
                          <td>{sample.nose_pressure?.toFixed(4)}</td>
                        )}
                        {highSpeed && (
                          <td>{sample.fin_pressure?.toFixed(4)}</td>
                        )}
                        <td>{sample.base_off.toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <ul>
                  {report.notes.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              </details>
            </>
          ) : (
            <p className="muted">
              {w.previewState === "invalid"
                ? "자동 항력을 계산할 수 없습니다. 입력 오류를 확인하세요."
                : "항력 미리보기를 계산하고 있습니다."}
            </p>
          )}
        </>
      ) : (
        <>
          <ConfigFields
            schema={w.schema}
            object={w.design}
            path={[]}
            only={["power_off_drag", "power_on_drag"]}
          />
          <p className="muted">
            항력 표의 x축은 Mach입니다. 이 모드에서는 입력한 계수·곡선을 그대로
            사용합니다. 모드를 바꿔도 직접 입력한 값은 보존됩니다.
          </p>
        </>
      )}
    </fieldset>
  );
}
