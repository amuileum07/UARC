import { useState } from "react";
import { desktopApi } from "../lib/bridge";
import { useWorkspace } from "../workspace";
export function DesignJson() {
  const w = useWorkspace();
  const [draft, setDraft] = useState<string | null>(null);
  const text = draft ?? JSON.stringify(w.design, null, 2);
  return (
    <div className="panel json-panel">
      <p className="muted">
        고급 입력 · 모든 설정과 추력 곡선. 적용 전에 Python 스키마로 검증합니다.
      </p>
      <label className="sr-only" htmlFor="design-json">
        설계 JSON
      </label>
      <textarea
        id="design-json"
        spellCheck={false}
        value={text}
        onChange={(e) => setDraft(e.target.value)}
      />
      <div className="button-row">
        <button
          type="button"
          onClick={() =>
            void w.act(async () => {
              const design = await (
                await desktopApi()
              ).validate_config("design", text);
              w.replace(design);
              setDraft(null);
            })
          }
        >
          검증 후 적용
        </button>
        <button
          type="button"
          onClick={() => {
            if (draft === null || window.confirm("JSON 편집 내용을 버릴까요?"))
              setDraft(null);
          }}
        >
          현재 설계 다시 읽기
        </button>
      </div>
    </div>
  );
}
