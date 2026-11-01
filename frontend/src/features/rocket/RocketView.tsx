import { lazy, Suspense, useId, useMemo, useState } from "react";
import { finVertices, geometryGuide, previewParts } from "../../lib/geometry";
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
  const guide = useMemo(() => {
    if (!preview) return null;
    const current = geometryGuide(
      preview.design,
      w.geometryField,
      preview.result.mass_properties,
    );
    return current?.componentId && current.componentId !== w.selection
      ? null
      : current;
  }, [preview, w.geometryField, w.selection]);
  const marker = useId().replaceAll(":", "");
  const parts = preview
    ? previewParts(preview.design, preview.result.mass_properties)
    : [];
  const guidePoints = guide ? [guide.origin, guide.from, guide.to] : [];
  const positions = [
    ...parts.flatMap((part) => part.profile.map(([z]) => z)),
    ...guidePoints.map((point) => point[1]),
  ];
  const low = Math.min(0, ...positions),
    high = Math.max(1, ...positions);
  const length = high - low;
  const radius = Math.max(
    0.08,
    guide ? length * 0.08 : 0,
    ...parts.flatMap((part) => part.profile.map(([, r]) => Math.abs(r))),
    ...guidePoints.map((point) => Math.abs(point[0])),
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
              onClick={() => {
                setError("");
                setMode(view);
              }}
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
                  guide={guide}
                  fallback={(message) => {
                    setError(message);
                    setMode("2D");
                  }}
                />
              </Suspense>
            ) : (
              <svg
                className="rocket-svg"
                viewBox={`${low - length * 0.08} ${-radius * (guide ? 2.1 : 1.7)} ${length * (guide ? 1.3 : 1.16)} ${radius * (guide ? 4.2 : 3.4)}`}
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
                        points={points.map(([z, r]) => `${z},${-r}`).join(" ")}
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
                {guide && (
                  <g
                    className="geometry-axes"
                    aria-label="좌표와 치수 안내"
                    pointerEvents="none"
                    data-guide-field={guide.field}
                  >
                    <defs>
                      {["#2464a6", "#137354", "#b65400"].map((color, index) => (
                        <marker
                          key={color}
                          id={`${marker}-${index}`}
                          viewBox="0 0 10 10"
                          refX="8"
                          refY="5"
                          markerWidth="6"
                          markerHeight="6"
                          orient="auto-start-reverse"
                        >
                          <path d="M 0 0 L 10 5 L 0 10 z" fill={color} />
                        </marker>
                      ))}
                    </defs>
                    <line
                      x1={guide.origin[1]}
                      y1={-guide.origin[0]}
                      x2={guide.origin[1] + length * 0.12}
                      y2={-guide.origin[0]}
                      stroke="#2464a6"
                      markerEnd={`url(#${marker}-0)`}
                    />
                    <text
                      x={guide.origin[1] + length * 0.13}
                      y={-guide.origin[0]}
                      fontSize={length / 60}
                      fill="#2464a6"
                    >
                      +z
                    </text>
                    <line
                      x1={guide.origin[1]}
                      y1={-guide.origin[0]}
                      x2={guide.origin[1]}
                      y2={-guide.origin[0] - radius * 0.8}
                      stroke="#137354"
                      markerEnd={`url(#${marker}-1)`}
                    />
                    <text
                      x={guide.origin[1]}
                      y={-guide.origin[0] - radius * 0.9}
                      fontSize={length / 60}
                      fill="#137354"
                    >
                      +r
                    </text>
                    <line
                      x1={guide.from[1]}
                      y1={-guide.from[0]}
                      x2={guide.to[1]}
                      y2={-guide.to[0]}
                      stroke="#b65400"
                      markerStart={`url(#${marker}-2)`}
                      markerEnd={`url(#${marker}-2)`}
                    />
                    <circle
                      cx={guide.origin[1]}
                      cy={-guide.origin[0]}
                      r={length / 180}
                      fill="#ffffff"
                      stroke="#b65400"
                    />
                    {Object.entries({ from: guide.from, to: guide.to }).map(
                      ([end, point]) => (
                        <circle
                          key={end}
                          cx={point[1]}
                          cy={-point[0]}
                          r={length / 220}
                          fill="#b65400"
                        />
                      ),
                    )}
                  </g>
                )}
              </svg>
            )}
            {guide && (
              <div
                className="geometry-guide"
                role="status"
                aria-live="polite"
                data-guide-field={guide.field}
              >
                <button
                  type="button"
                  aria-label="좌표 안내 닫기"
                  title="Esc"
                  onClick={() => w.setGeometryField(null)}
                >
                  ×
                </button>
                <strong>
                  {guide.label} · {Number(guide.value.toPrecision(7))} m
                </strong>
                <span>{guide.reference}</span>
                <span>
                  기준점 · z = {Number(guide.origin[1].toPrecision(6))} m · r ={" "}
                  {Number(guide.origin[0].toPrecision(6))} m
                </span>
                <span>
                  <b className="guide-z">+z</b> 꼬리 → 노즈 ·{" "}
                  <b className="guide-r">+r</b> 중심축 → 바깥
                </span>
                {mode === "2D" && guide.from[2] !== guide.to[2] && (
                  <span>
                    2D는 측면 투영입니다. 면에 수직인 치수는 3D에서 확인하세요.
                  </span>
                )}
              </div>
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
