import { desktopApi } from "../../lib/bridge";
import { componentRemovalIssue } from "../../lib/edit";
import type { ReactNode } from "react";
import { ConfigFields } from "../../components/ConfigFields";
import { NumberField } from "../../components/Fields";
import { ProjectName } from "../../components/ProjectName";
import {
  createComponent,
  createSurface,
  surfaceLabels,
} from "../../lib/templates";
import type { ComponentKind } from "../../lib/templates";
import { compatibleMaterial, densityUnits } from "../../lib/materials";
import { useWorkspace } from "../../workspace";
import { AssemblyEditor, FlightEditor, MotorEditor } from "./Settings";
import { OpenRocketImporter } from "./OpenRocket";
import { MaterialsEditor, SurfaceFinishEditor } from "./Materials";

function DeleteComponent() {
  const w = useWorkspace();
  const issue = componentRemovalIssue(w.design, w.selection);
  return (
    <div>
      <button
        type="button"
        className="danger"
        disabled={!!issue}
        title={issue || "선택한 부품을 설계에서 삭제합니다."}
        onClick={() => w.removeComponent(w.selection)}
      >
        선택 부품 삭제
      </button>
      {issue && <p className="muted">{issue}</p>}
    </div>
  );
}

export function Explorer() {
  const w = useWorkspace();
  const add = (kind: ComponentKind) => {
    const materials = w.design.materials || {};
    const componentKind =
      kind in surfaceLabels
        ? "surface"
        : (kind as "body_tube" | "mass" | "line" | "parachute");
    const material =
      Object.entries(materials).find(([, entry]) =>
        compatibleMaterial(entry, componentKind),
      )?.[0] || crypto.randomUUID().replaceAll("-", "");
    if (kind !== "mass" && !Object.hasOwn(materials, material))
      w.edit(["materials"], {
        ...materials,
        [material]:
          kind === "line"
            ? { name: "사용자 줄", density: 0.001, density_type: "line" }
            : { name: "사용자 재질", density: 1000 },
      });
    const radius = w.preview?.result.simulation.rocket.radius || 0.025;
    const part = createComponent(
      kind,
      crypto.randomUUID().replaceAll("-", ""),
      material,
      radius,
    );
    w.edit(["components"], [...w.design.components, part]);
    w.setSelection(part.id);
  };
  return (
    <div className="panel scroll">
      <p className="eyebrow">ROCKET DESIGN</p>
      <h2>
        <ProjectName />
      </h2>
      <div className="panel-toolbar">
        <button
          type="button"
          onClick={() =>
            void w.act(async () => {
              const design = await (await desktopApi()).import_design_file();
              if (design) w.replace(design);
            })
          }
        >
          설계 파일 열기
        </button>
        <button
          type="button"
          disabled={
            w.previewState !== "ready" ||
            Object.keys(w.problems).some((key) => key.startsWith("field:"))
          }
          onClick={() =>
            void w.act(async () => {
              await (
                await desktopApi()
              ).export_design_file(JSON.stringify(w.design));
            })
          }
        >
          설계 파일 내보내기
        </button>
      </div>
      <fieldset className="tree" aria-label="로켓 부품">
        <button
          type="button"
          className={w.selection === "assembly" ? "selected" : ""}
          onClick={() => w.setSelection("assembly")}
        >
          로켓 전체 · 항력 · 실측값
        </button>
        {w.design.components.map((component) => (
          <button
            type="button"
            key={component.id}
            className={w.selection === component.id ? "selected" : ""}
            onClick={() => w.setSelection(component.id)}
          >
            <span aria-hidden="true">◇</span> {component.name || component.id}
          </button>
        ))}
        <button
          type="button"
          className={w.selection === "motor" ? "selected" : ""}
          onClick={() => w.setSelection("motor")}
        >
          ◈ 모터 · 추진제
        </button>
        <button
          type="button"
          className={w.selection === "flight" ? "selected" : ""}
          onClick={() => w.setSelection("flight")}
        >
          ↗ 비행 설정
        </button>
        <button
          type="button"
          className={w.selection === "materials" ? "selected" : ""}
          onClick={() => w.setSelection("materials")}
        >
          ▦ 재질
        </button>
      </fieldset>
      <DeleteComponent />
      <h3>부품 추가</h3>
      <div className="button-row">
        {Object.entries({
          body_tube: "동체",
          ...surfaceLabels,
          mass: "질량",
          line: "줄 · 웨빙",
          parachute: "낙하산",
        }).map(([kind, label]) => (
          <button
            type="button"
            key={kind}
            disabled={w.design.components.length >= 64}
            onClick={() => add(kind as ComponentKind)}
          >
            {label}
          </button>
        ))}
      </div>
      <OpenRocketImporter />
      <h3>저장한 설계</h3>
      {w.saved.length === 0 && (
        <p className="muted">저장하면 여기에 표시됩니다.</p>
      )}
      {w.saved.map((item) => (
        <button
          type="button"
          className="document"
          key={item.design_id}
          onClick={() =>
            void w.act(async () =>
              w.replace(
                await (await desktopApi()).get_saved_design(item.design_id),
                true,
              ),
            )
          }
        >
          {item.name}
          <small>{new Date(item.created_at).toLocaleString()}</small>
        </button>
      ))}
    </div>
  );
}
export function Properties() {
  const w = useWorkspace();
  const index = w.design.components.findIndex((c) => c.id === w.selection);
  const component = w.design.components[index];
  let content: ReactNode;
  if (w.selection === "materials") content = <MaterialsEditor />;
  else if (w.selection === "flight") content = <FlightEditor />;
  else if (w.selection === "motor") content = <MotorEditor />;
  else if (w.selection === "assembly") content = <AssemblyEditor />;
  else if (!component) content = <p>부품을 선택하세요.</p>;
  else {
    const base = ["components", String(index)];
    const schemaName = {
      body_tube: "BodyTubeDesign",
      surface: "SurfaceDesign",
      mass: "MassComponentDesign",
      line: "LineDesign",
      parachute: "ParachuteDesign",
    }[component.component_type || "mass"];
    content = (
      <>
        <p className="eyebrow">COMPONENT PROPERTIES</p>
        <h2>{component.name || component.id}</h2>
        <DeleteComponent />
        {"material" in component && (
          <label className="field">
            재질
            <select
              value={component.material}
              onChange={(event) =>
                w.edit([...base, "material"], event.target.value)
              }
            >
              {Object.entries(w.design.materials || {}).map(
                ([id, material]) =>
                  compatibleMaterial(material, component.component_type) && (
                    <option key={id} value={id}>
                      {material.name} ·{" "}
                      {densityUnits[material.density_type || "bulk"]}
                    </option>
                  ),
              )}
            </select>
          </label>
        )}
        {"material" in component && (
          <button type="button" onClick={() => w.setSelection("materials")}>
            재질 라이브러리 열기
          </button>
        )}
        {"surface" in component && (
          <label className="field">
            공력면 종류
            <select
              value={component.surface.surface_type || "nose"}
              onChange={(event) => {
                if (!Object.hasOwn(surfaceLabels, event.target.value)) return;
                const next = createSurface(
                  event.target.value as keyof typeof surfaceLabels,
                  component.surface.rocket_radius,
                );
                next.position = component.surface.position;
                w.edit([...base, "surface"], next);
              }}
            >
              {Object.entries(surfaceLabels).map(([kind, label]) => (
                <option key={kind} value={kind}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        )}
        <ConfigFields
          key={component.id}
          object={component}
          schemaName={schemaName}
          path={base}
          omit={[
            "material",
            "surface_finish",
            "line_material",
            ...(component.component_type === "parachute"
              ? ["line_length", "line_mass"]
              : []),
            ...(component.component_type === "parachute" &&
            w.design.materials?.[component.material]?.density_type === "surface"
              ? ["thickness"]
              : []),
          ]}
        />
        {(component.component_type === "body_tube" ||
          component.component_type === "surface") && (
          <SurfaceFinishEditor
            key={component.id}
            value={component.surface_finish}
            path={[...base, "surface_finish"]}
          />
        )}
        {component.component_type === "parachute" && (
          <fieldset>
            <legend>낙하산 원단 · 줄</legend>
            <p className="muted">
              원단의 면밀도(kg/m²)는 원단 면적과 곱하며 두께는 사용하지
              않습니다. 줄은 수동 질량 또는 선밀도 × 전체 길이로 계산합니다.
            </p>
            <label className="field">
              줄 재질
              <select
                value={component.line_material || ""}
                onChange={(event) =>
                  w.edit(base, {
                    ...component,
                    line_material: event.target.value || null,
                    line_length: event.target.value
                      ? component.line_length || 1
                      : component.line_length,
                  })
                }
              >
                <option value="">수동 줄 질량</option>
                {Object.entries(w.design.materials || {})
                  .filter(([, entry]) => entry.density_type === "line")
                  .map(([id, entry]) => (
                    <option key={id} value={id}>
                      {entry.name} · {entry.density} kg/m
                    </option>
                  ))}
              </select>
            </label>
            {component.line_material ? (
              <NumberField
                label="줄 전체 길이 · 모든 줄의 합"
                unit="m"
                value={component.line_length || 0}
                onChange={(number) => w.edit([...base, "line_length"], number)}
              />
            ) : (
              <NumberField
                label="줄 질량"
                unit="kg"
                value={component.line_mass || 0}
                onChange={(number) => w.edit([...base, "line_mass"], number)}
              />
            )}
          </fieldset>
        )}
        <p className="muted">
          위치 기준: 동체 뒤끝 / 노즈 끝 / 핀 루트 앞전 / 수납 부품 CG. 단위 m.
          실측 관성은 부품 자체 CG 기준입니다.
        </p>
      </>
    );
  }
  return <div className="panel scroll">{content}</div>;
}
