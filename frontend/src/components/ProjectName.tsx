import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { useWorkspace } from "../workspace";

export function ProjectName() {
  const w = useWorkspace();
  const [editing, setEditing] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const finished = useRef(false);
  useEffect(() => {
    if (editing) {
      input.current?.focus();
      input.current?.select();
    }
  }, [editing]);
  const finish = (value?: string) => {
    if (finished.current) return;
    finished.current = true;
    const name = value?.trim();
    if (name && name.length <= 128 && name !== w.design.name)
      w.edit(["name"], name);
    setEditing(false);
  };
  return editing ? (
    <input
      ref={input}
      className="project-name-input"
      aria-label="로켓 프로젝트 이름"
      title="Enter로 적용 · Esc로 취소"
      defaultValue={w.design.name}
      required
      maxLength={128}
      pattern=".*\S.*"
      onBlur={(event) => finish(event.currentTarget.value)}
      onKeyDown={(event) => {
        if (event.nativeEvent.isComposing) return;
        if (event.key === "Escape") {
          event.preventDefault();
          flushSync(() => finish());
          button.current?.focus();
        } else if (
          event.key === "Enter" ||
          ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s")
        ) {
          if (!event.currentTarget.reportValidity()) {
            event.preventDefault();
            event.stopPropagation();
            return;
          }
          if (event.key === "Enter") event.preventDefault();
          const value = event.currentTarget.value;
          // Publish the name before the workspace's Ctrl+S handler saves it.
          flushSync(() => finish(value));
          button.current?.focus();
        }
      }}
    />
  ) : (
    <button
      ref={button}
      type="button"
      className="project-name-button"
      aria-label={`${w.design.name} · 이름 변경`}
      title="클릭하여 프로젝트 이름 변경"
      onClick={() => {
        finished.current = false;
        setEditing(true);
      }}
    >
      {w.design.name}
    </button>
  );
}
