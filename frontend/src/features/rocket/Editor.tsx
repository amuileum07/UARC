import { desktopApi } from "../../lib/bridge";
import type { ReactNode } from "react";
import { ConfigFields } from "../../components/ConfigFields";
import {
  createComponent,
  createSurface,
  surfaceLabels,
} from "../../lib/templates";
import type { ComponentKind } from "../../lib/templates";
import { useWorkspace } from "../../workspace";
import {
  AssemblyEditor,
  FlightEditor,
  MaterialsEditor,
  MotorEditor,
} from "./Settings";
import { OpenRocketImporter } from "./OpenRocket";

export function Explorer() {
  const w = useWorkspace();
  const add = (kind: ComponentKind) => {
    const materials = w.design.materials || {};
    const material =
      Object.keys(materials)[0] || crypto.randomUUID().replaceAll("-", "");
    if (!Object.keys(materials).length)
      w.edit(["materials"], {
        [material]: { name: "사용자 재질", density: 1000 },
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
      <h2>{w.design.name}</h2>
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
      <h3>부품 추가</h3>
      <div className="button-row">
        {Object.entries({
          body_tube: "동체",
          ...surfaceLabels,
          mass: "질량",
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
      parachute: "ParachuteDesign",
    }[component.component_type || "mass"];
    content = (
      <>
        <p className="eyebrow">COMPONENT PROPERTIES</p>
        <h2>{component.name || component.id}</h2>
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
                ([id, material]) => (
                  <option key={id} value={id}>
                    {material.name}
                  </option>
                ),
              )}
            </select>
          </label>
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
          omit={["material"]}
        />
        <p className="muted">
          위치 기준: 동체 뒤끝 / 노즈 끝 / 핀 루트 앞전 / 수납 부품 CG. 단위 m.
          실측 관성은 부품 자체 CG 기준입니다.
        </p>
        <button
          type="button"
          className="danger"
          disabled={w.design.components.length < 2}
          onClick={() => {
            w.edit(
              ["components"],
              w.design.components.filter((c) => c.id !== component.id),
            );
            w.setSelection(
              w.design.components.find((c) => c.id !== component.id)?.id ||
                "assembly",
            );
          }}
        >
          부품 삭제
        </button>
      </>
    );
  }
  return <div className="panel scroll">{content}</div>;
}
