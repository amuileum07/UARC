import { lazy, Suspense, useState } from "react";
import { finVertices, previewParts } from "../../lib/geometry";
import { useWorkspace } from "../../workspace";

const Rocket3D = lazy(() =>
  import("./Rocket3D").then((module) => ({ default: module.Rocket3D })),
);
const colors = { body: "#bcbcbc", fin: "#888888", internal: "#dddddd" };
export function RocketView() {
  const w = useWorkspace();
  const [mode, setMode] = useState<"2D" | "3D">("2D");
  const [interior, setInterior] = useState(false);
  const [error, setError] = useState("");
  const preview = w.preview;
  const parts = preview
    ? previewParts(preview.design, preview.result.mass_properties)
    : [];
  const positions = parts.flatMap((part) => part.profile.map(([z]) => z));
  const low = Math.min(0, ...positions),
    high = Math.max(1, ...positions);
  const length = high - low;
  const radius = Math.max(
    0.08,
    ...parts.flatMap((part) => part.profile.map(([, r]) => Math.abs(r))),
  );
  return (
    <section className="view-panel">
      <div className="panel-toolbar">
        <fieldset className="segmented" aria-label="로켓 보기">
          {(["2D", "3D"] as const).map((view) => (
            <button
              type="button"
              key={view}
              aria-pressed={mode === view}
              onClick={() => setMode(view)}
            >
              {view}
            </button>
          ))}
        </fieldset>
        <label>
          <input
            type="checkbox"
            checked={interior}
            onChange={(e) => setInterior(e.target.checked)}
          />{" "}
          내부 표시
        </label>
        <span className="muted" role="status">
          {w.previewState === "ready"
            ? "최신 설계"
            : w.previewState === "pending"
              ? "계산 중 · 이전 형상"
              : "입력 확인 · 이전 형상"}
        </span>
      </div>
      {error && <p className="notice">{error}</p>}
      {preview ? (
        <>
          <div className="viewport">
            {mode === "3D" ? (
              <Suspense
                fallback={<p className="empty">3D 엔진을 불러오는 중…</p>}
              >
                <Rocket3D
                  design={preview.design}
                  report={preview.result.mass_properties}
                  interior={interior}
                  selection={w.selection}
                  select={w.setSelection}
                  fallback={(message) => {
                    setError(message);
                    setMode("2D");
                  }}
                />
              </Suspense>
            ) : (
              <svg
                className="rocket-svg"
                viewBox={`${low - length * 0.08} ${-radius * 1.7} ${length * 1.16} ${radius * 3.4}`}
                aria-label="로켓 2D 측면도"
              >
                <line
                  x1={low - length * 0.04}
                  x2={high + length * 0.04}
                  y1="0"
                  y2="0"
                  stroke="#bcbcbc"
                  strokeWidth={length / 1000}
                  strokeDasharray={`${length / 100} ${length / 100}`}
                />
                {parts
                  .filter((p) => interior || p.type !== "internal")
                  .flatMap((part) => {
                    let outlines: { id: string; points: number[][] }[];
                    if (part.type === "fin") {
                      const raw =
                        preview.result.mass_properties.components.find(
                          (p) => p.id === part.id,
                        )?.fin_outline_m || [];
                      outlines = Array.from({ length: part.count }, (_, i) => ({
                        id: `${part.id}-fin-${i}`,
                        points: finVertices(part, raw, i).map(([x, y]) => [
                          y,
                          x,
                        ]),
                      }));
                    } else
                      outlines = [
                        {
                          id: part.id,
                          points: [
                            ...part.profile,
                            ...part.profile
                              .slice()
                              .reverse()
                              .map(([z, r]) => [z, -r]),
                          ],
                        },
                      ];
                    return outlines.map(({ id, points }) => (
                      // biome-ignore lint/a11y/useSemanticElements: SVG polygons cannot be HTML buttons; keyboard activation and the component tree both support selection.
                      <polygon
                        key={id}
                        role="button"
                        tabIndex={0}
                        aria-label={part.name}
                        aria-pressed={part.id === w.selection}
                        points={points.map(([z, r]) => `${z},${r}`).join(" ")}
                        fill={
                          part.id === w.selection
                            ? "#666666"
                            : colors[part.type]
                        }
                        fillOpacity={
                          interior && part.type === "body" ? 0.25 : 0.85
                        }
                        stroke={part.id === w.selection ? "#111111" : "#555555"}
                        strokeWidth={length / 700}
                        onClick={() => w.setSelection(part.id)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            w.setSelection(part.id);
                          }
                        }}
                      >
                        <title>{part.name}</title>
                      </polygon>
                    ));
                  })}
                <circle
                  cx={preview.result.mass_properties.effective.center_of_mass_m}
                  cy="0"
                  r={length / 150}
                  fill="#666666"
                />
                <text
                  x={preview.result.mass_properties.effective.center_of_mass_m}
                  y={radius * 1.5}
                  textAnchor="middle"
                  fontSize={length / 45}
                  fill="#333333"
                >
                  CG · 기체만
                </text>
              </svg>
            )}
          </div>
          <div className="metrics">
            <span>
              기체 질량{" "}
              <strong>
                {preview.result.mass_properties.effective.mass_kg.toFixed(3)} kg
              </strong>
            </span>
            <span>
              기체 CG{" "}
              <strong>
                {preview.result.mass_properties.effective.center_of_mass_m.toFixed(
                  4,
                )}{" "}
                m
              </strong>
            </span>
            <span>
              관성 I₁₁{" "}
              <strong>
                {preview.result.mass_properties.effective.inertia_kg_m2[0].toPrecision(
                  4,
                )}{" "}
                kg·m²
              </strong>
            </span>
          </div>
          <p className="caption">
            CG·관성은 모터 제외. 내부 형상은 배치 확인용 근사이며 구조·열 해석을
            나타내지 않습니다.
          </p>
        </>
      ) : (
        <p className="empty">설계 형상을 계산하고 있습니다.</p>
      )}
    </section>
  );
}
