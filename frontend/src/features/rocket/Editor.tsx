import { desktopApi } from "../../lib/bridge";
import { NumericFields } from "../../components/Fields";
import { useWorkspace } from "../../workspace";

export function Explorer() {
  const w = useWorkspace();
  return (
    <div className="panel scroll">
      <p className="eyebrow">ROCKET DESIGN</p>
      <h2>{w.design.name}</h2>
      <div className="tree" role="group" aria-label="로켓 부품">
        {w.design.components.map((component) => (
          <button
            key={component.id}
            className={w.selection === component.id ? "selected" : ""}
            onClick={() => w.setSelection(component.id)}
          >
            <span aria-hidden="true">◇</span> {component.name || component.id}
          </button>
        ))}
        <button
          className={w.selection === "motor" ? "selected" : ""}
          onClick={() => w.setSelection("motor")}
        >
          ◈ 모터 · 추진제
        </button>
        <button
          className={w.selection === "flight" ? "selected" : ""}
          onClick={() => w.setSelection("flight")}
        >
          ↗ 비행 설정
        </button>
        <button
          className={w.selection === "materials" ? "selected" : ""}
          onClick={() => w.setSelection("materials")}
        >
          ▦ 재질
        </button>
      </div>
      <h3>부품 추가</h3>
      <div className="button-row">
        {["body_tube", "surface", "mass", "parachute"].map((kind) => (
          <button
            key={kind}
            onClick={() => {
              const template = w.design.components.find(
                (c) => c.component_type === kind,
              );
              if (!template) return;
              const part = {
                ...structuredClone(template),
                id: crypto.randomUUID().replaceAll("-", "").slice(0, 16),
                name: `${template.name} copy`,
              };
              w.edit(["components"], [...w.design.components, part]);
              w.setSelection(part.id);
            }}
          >
            {
              {
                body_tube: "동체",
                surface: "공력면",
                mass: "질량",
                parachute: "낙하산",
              }[kind]
            }
          </button>
        ))}
      </div>
      <h3>저장한 설계</h3>
      {w.saved.length === 0 && (
        <p className="muted">저장하면 여기에 표시됩니다.</p>
      )}
      {w.saved.map((item) => (
        <button
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
  if (w.selection === "materials")
    return (
      <div className="panel scroll">
        <h2>재질</h2>
        <p className="muted">
          밀도 변경은 이 재질을 사용하는 모든 부품에 반영됩니다.
        </p>
        <NumericFields object={w.design.materials || {}} path={["materials"]} />
      </div>
    );
  if (w.selection === "flight")
    return (
      <div className="panel scroll">
        <h2>비행 설정</h2>
        <NumericFields object={w.design.flight} path={["flight"]} />
      </div>
    );
  if (w.selection === "motor")
    return (
      <div className="panel scroll">
        <h2>모터 · 추진제</h2>
        <p className="muted">
          위치는 모터 좌표계 기준입니다. 모터 형식과 추력 곡선은 아래 JSON에서
          편집할 수 있습니다.
        </p>
        {w.design.motor && (
          <NumericFields object={w.design.motor} path={["motor"]} />
        )}
        <h3>탱크</h3>
        {w.design.tanks?.map((tank, i) => (
          <NumericFields key={i} object={tank} path={["tanks", String(i)]} />
        ))}
      </div>
    );
  if (!component) return <div className="panel">부품을 선택하세요.</div>;
  const base = ["components", String(index)];
  return (
    <div className="panel scroll">
      <p className="eyebrow">COMPONENT PROPERTIES</p>
      <h2>{component.name || component.id}</h2>
      <label className="field">
        이름
        <input
          value={component.name || ""}
          onChange={(e) => w.edit([...base, "name"], e.target.value)}
        />
      </label>
      {"material" in component && (
        <label className="field">
          재질
          <select
            value={component.material}
            onChange={(e) => w.edit([...base, "material"], e.target.value)}
          >
            {Object.entries(w.design.materials || {}).map(([id, material]) => (
              <option key={id} value={id}>
                {material.name}
              </option>
            ))}
          </select>
        </label>
      )}
      {"surface" in component && "kind" in component.surface && (
        <label className="field">
          노즈 형상
          <select
            value={component.surface.kind}
            onChange={(e) =>
              w.edit([...base, "surface", "kind"], e.target.value)
            }
          >
            {[
              "haack",
              "conical",
              "ogive",
              "elliptical",
              "parabolic",
              "vonkarman",
              "lvhaack",
              "powerseries",
            ].map((kind) => (
              <option key={kind}>{kind}</option>
            ))}
          </select>
        </label>
      )}
      <NumericFields object={component} path={base} />
      <p className="muted">
        위치 기준: 동체 뒤끝 / 노즈 끝 / 핀 루트 앞전 / 수납 부품 CG. 단위 m.
      </p>
      <button
        className="danger"
        disabled={w.design.components.length < 2}
        onClick={() => {
          w.edit(
            ["components"],
            w.design.components.filter((c) => c.id !== component.id),
          );
          w.setSelection(
            w.design.components.find((c) => c.id !== component.id)?.id ||
              "motor",
          );
        }}
      >
        부품 삭제
      </button>
    </div>
  );
}
