(async () => {
  const phase = "diagnostics";
  const prefix = "UARC diagnostic probe";
  const received = new Set();
  let restore;
  let script;
  async function wait(read) {
    const deadline = performance.now() + 20000;
    while (performance.now() < deadline) {
      if (read()) return;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    throw Error("Frontend diagnostics did not reach the Python bridge");
  }
  try {
    await wait(() => document.querySelector(".app-header") && window.pywebview?.api?.report_frontend_error);
    const api = window.pywebview.api;
    const original = api.report_frontend_error;
    api.report_frontend_error = async (payload) => {
      const accepted = await original(payload);
      const report = JSON.parse(payload);
      if (accepted && report.message.startsWith(prefix)) received.add(report.kind);
      if (accepted && report.kind === "renderer" && report.message === "WebGL context lost") received.add("renderer");
      return accepted;
    };
    restore = () => { api.report_frontend_error = original; };
    window.dispatchEvent(new ErrorEvent("error", {
      message: `${prefix} window`, error: new Error(`${prefix} window`),
      filename: "diagnostic-probe.js", lineno: 1, colno: 1,
    }));
    // Qt runJavaScript() rejections can be console-only. A page-owned script
    // exercises the same unhandled-rejection event as production UI code.
    script = document.createElement("script");
    script.textContent = `void Promise.reject(new Error(${JSON.stringify(`${prefix} rejection`)}));`;
    document.head.append(script);
    window.dispatchEvent(new Event("webglcontextlost"));
    await wait(() => ["error", "unhandledrejection", "renderer"].every((kind) => received.has(kind)));
    let rejected = false;
    try { await api.validate_config("environment", "{}"); }
    catch { rejected = true; }
    if (!rejected) throw Error("Invalid IPC input unexpectedly passed validation");
    return {ok: true, phase, kinds: [...received]};
  } catch (error) {
    return {ok: false, phase, error: String(error), kinds: [...received]};
  } finally {
    script?.remove();
    restore?.();
  }
})()
