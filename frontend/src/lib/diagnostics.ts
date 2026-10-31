type ErrorKind =
  | "error"
  | "unhandledrejection"
  | "react"
  | "renderer"
  | "resource";
interface ErrorReport {
  kind: ErrorKind;
  message: string;
  stack: string;
  source: string;
  component_stack: string;
}

const pending: ErrorReport[] = [];
let sending = false;

async function flushErrors() {
  const api = window.pywebview?.api;
  if (sending || typeof api?.report_frontend_error !== "function") return;
  sending = true;
  try {
    while (pending.length) {
      const report = pending.shift();
      if (report) await api.report_frontend_error(JSON.stringify(report));
    }
  } catch {
    // A broken bridge must not produce another unhandled rejection or retry loop.
  } finally {
    sending = false;
  }
}

export function reportFrontendError(
  kind: ErrorKind,
  error: unknown,
  source = "",
  componentStack = "",
) {
  let message = "Unknown frontend error";
  let stack = "";
  try {
    message =
      (error instanceof Error ? error.message : String(error)) || message;
    stack = error instanceof Error ? (error.stack ?? "") : "";
  } catch {
    // Rejection reasons may be objects whose string conversion throws.
  }
  // At most 20 reports wait for startup/IPC; the backend also limits reports/minute.
  // Character limits keep even four-byte UTF-8 text within the 32 KiB envelope.
  if (pending.length >= 20) pending.shift();
  const report = {
    kind,
    message: message.slice(0, 1024),
    stack: stack.slice(0, 4096),
    source: source.slice(0, 512),
    component_stack: componentStack.slice(0, 2048),
  };
  while (new TextEncoder().encode(JSON.stringify(report)).length > 32_768) {
    report.stack = report.stack.slice(0, report.stack.length / 2);
    report.component_stack = report.component_stack.slice(
      0,
      report.component_stack.length / 2,
    );
  }
  pending.push(report);
  void flushErrors();
}

export function installErrorReporting() {
  const capture = { capture: true };
  const onError = (event: ErrorEvent) => {
    if (event.message) {
      reportFrontendError(
        "error",
        event.error ?? event.message,
        `${event.filename}:${event.lineno}:${event.colno}`,
      );
    } else if (event.target instanceof HTMLElement) {
      reportFrontendError(
        "resource",
        "Resource failed to load",
        event.target.getAttribute("src") ??
          event.target.getAttribute("href") ??
          "",
      );
    }
  };
  const onRejection = (event: PromiseRejectionEvent) =>
    reportFrontendError("unhandledrejection", event.reason);
  const onContextLost = () =>
    reportFrontendError("renderer", "WebGL context lost");
  window.addEventListener("error", onError, capture);
  window.addEventListener("unhandledrejection", onRejection);
  window.addEventListener("webglcontextlost", onContextLost, capture);
  window.addEventListener("pywebviewready", flushErrors);
  void flushErrors();
  return () => {
    window.removeEventListener("error", onError, capture);
    window.removeEventListener("unhandledrejection", onRejection);
    window.removeEventListener("webglcontextlost", onContextLost, capture);
    window.removeEventListener("pywebviewready", flushErrors);
  };
}
