(async () => {
  const scenario = /* SCENARIO */ {};
  let stage = "frontend startup";
  const errors = [];
  window.addEventListener("error", (event) => errors.push(event.message));
  window.addEventListener("unhandledrejection", (event) => errors.push(String(event.reason)));
  const visible = (node) => node && node.getClientRects().length > 0;
  const text = (node) => node.textContent.trim();
  async function wait(label, read, timeout = 45000) {
    stage = label;
    const deadline = performance.now() + timeout;
    while (performance.now() < deadline) {
      if (errors.length) throw Error(errors.join("\n"));
      const value = await read();
      if (value) return value;
      await new Promise((resolve) => setTimeout(resolve, 150));
    }
    throw Error(`Timed out: ${label}`);
  }
  async function painted() {
    // React may commit synthetic input/click updates on a later browser task.
    // Wait through a frame and the following task before the next user action.
    await new Promise(requestAnimationFrame);
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  async function click(label, selector, value) {
    const button = await wait(label, () => [...document.querySelectorAll(selector)]
      .find((node) => visible(node) && !node.disabled && text(node) === value));
    button.click();
    await painted();
  }
  async function openPanel(title) {
    // The app header mounts before Dockview's onReady initializes its API.
    const tab = await wait(`dock tab ${title}`, () => [...document.querySelectorAll('[role="tab"]')]
      .find((node) => node.getAttribute("aria-label") === title));
    document.querySelector(".view-menu").open = true;
    await click(`open ${title}`, ".view-menu button", title);
    document.querySelector(".view-menu").open = false;
    await wait(`active panel ${title}`, () => tab.getAttribute("aria-selected") === "true");
    await painted();
  }
  async function rename(name) {
    (await wait("project name button", () => document.querySelector(".app-header .project-name-button"))).click();
    const input = await wait("project name input", () => document.querySelector('.app-header input[aria-label="로켓 프로젝트 이름"]'));
    input.value = name;
    input.dispatchEvent(new KeyboardEvent("keydown", {key: "Enter", bubbles: true}));
    await wait("renamed design", () => document.querySelector(".app-header .project-name-button")?.textContent.trim() === name);
  }
  async function save(name) {
    await click("save through UI", ".app-header button", "저장");
    await wait("committed design", async () => (await api.list_designs()).some((item) => item.name === name));
    await wait("clean editor", () => !document.querySelector(".project-title").textContent.includes("수정됨"));
  }
  async function load(name) {
    await openPanel("프로젝트");
    const button = await wait("saved design in explorer", () => [...document.querySelectorAll("button.document")]
      .find((node) => visible(node) && node.firstChild.textContent.trim() === name));
    button.click();
    await wait("loaded design name", () => document.querySelector(".app-header .project-name-button")?.textContent.trim() === name);
  }
  async function editPayloadMass() {
    // Exercise the controlled JSON editor and Python validation through the UI.
    await openPanel("설계 JSON");
    const editor = await wait("design JSON editor", () => document.querySelector("#design-json"));
    const design = JSON.parse(editor.value);
    design.components.find((component) => component.id === "payload").mass = 1.05;
    const payload = JSON.stringify(design);
    editor.focus();
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(editor, payload);
    editor.dispatchEvent(new Event("input", {bubbles: true}));
    await painted();
    await click("validate changed mass", ".json-panel button", "검증 후 적용");
    // Applying replaces the draft with formatted, validated JSON. Read the live
    // editor, rather than React's internal synchronization of defaultValue.
    await wait("JSON edit applied", () => {
      const current = document.querySelector("#design-json");
      return current.value !== payload && JSON.parse(current.value).components.find((component) => component.id === "payload").mass === 1.05;
    });
  }
  async function canvas(selector) {
    const node = await wait("rendered 3D canvas", () => [...document.querySelectorAll(selector)]
      .find((element) => visible(element) && element.dataset.rendered === "true" && element.width > 0 && element.height > 0));
    const gl = node.getContext("webgl2") || node.getContext("webgl");
    if (!gl || gl.isContextLost()) throw Error("WebGL context is unavailable or lost");
    const info = gl.getExtension("WEBGL_debug_renderer_info");
    return {width: node.width, height: node.height, version: gl.getParameter(gl.VERSION),
      renderer: gl.getParameter(info ? info.UNMASKED_RENDERER_WEBGL : gl.RENDERER),
      antialias: gl.getContextAttributes()?.antialias,
      msaa_samples: node.dataset.msaaSamples ? Number(node.dataset.msaaSamples) : null};
  }
  async function networkFailures() {
    await openPanel("설계 JSON");
    const baseline = document.querySelector("#design-json").value;
    const design = JSON.parse(baseline);
    const original = {get_terrain: api.get_terrain, get_weather: api.get_weather};
    const cases = [];
    const recovered = [];
    const services = [
      {method: "get_terrain", tab: "위치 · 지형", button: "주변 2 km 고도 자료 가져오기"},
      {method: "get_weather", tab: "시각 · 기상", button: "고도별 기상 가져오기"},
    ];
    async function environment(tab) {
      await openPanel("발사 환경");
      await click("environment tab", 'fieldset[aria-label="발사 환경 설정"] button', tab);
    }
    const warnings = () => [...document.querySelector('fieldset[aria-label="발사 환경 설정"]').parentElement
      .querySelectorAll('.notice.warning[role="status"]')].filter(visible);
    async function unchanged() {
      await openPanel("설계 JSON");
      if (document.querySelector("#design-json").value !== baseline)
        throw Error("A failed network request changed the design");
    }
    try {
      for (const service of services) {
        await environment(service.tab);
        if (service.method === "get_terrain") {
          const source = [...document.querySelectorAll("label")]
            .find((node) => visible(node) && node.textContent.includes("고도 자료 소스"))?.querySelector("select");
          if (!source) throw Error("Terrain source selector is unavailable");
          source.value = "opentopodata";
          source.dispatchEvent(new Event("change", {bubbles: true}));
          await painted();
        }
        for (const failure of ["HTTP 500", "timeout", "offline"]) {
          const message = `UARC network probe ${service.method} ${failure}`;
          let called = false;
          let rejectRequest;
          api[service.method] = () => new Promise((_resolve, reject) => {
            called = true;
            rejectRequest = () => reject(Error(message));
          });
          await click("request unavailable service", "button", service.button);
          await wait("network request started", () => called);
          if (failure === "timeout") {
            await openPanel("속성");
            rejectRequest();
            await painted();
            await environment(service.tab);
          } else rejectRequest();
          await wait("local network warning and retry", () => called &&
            warnings().some((node) => node.textContent.includes(message)) &&
            [...document.querySelectorAll("button")]
              .some((node) => visible(node) && !node.disabled && text(node) === service.button));
          cases.push({service: service.method, failure});
          await unchanged();
          await environment(service.tab);
        }
        let called = false;
        api[service.method] = async (payload) => {
          called = true;
          if (service.method === "get_terrain") return structuredClone(design.environment.terrain);
          const request = JSON.parse(payload);
          return {request, source: "Open-Meteo", retrieved_at: request.date,
            grid_latitude: request.latitude, grid_longitude: request.longitude,
            response_sha256: "a".repeat(64), notes: [],
            levels: [
              {altitude_m: 0, pressure_pa: 101325, temperature_k: 288, wind_u_m_s: 0, wind_v_m_s: 0},
              {altitude_m: 20000, pressure_pa: 5500, temperature_k: 217, wind_u_m_s: 0, wind_v_m_s: 0},
            ]};
        };
        await click("retry recovered service", "button", service.button);
        await wait("recovered request", () => called &&
          !warnings().length &&
          [...document.querySelectorAll("button")]
            .some((node) => visible(node) && !node.disabled && text(node) === service.button));
        if (service.method === "get_weather")
          await wait("weather recovery preview", () => [...document.querySelectorAll("button")]
            .some((node) => visible(node) && !node.disabled && text(node) === "이 기상 적용"));
        recovered.push(service.method);
        await unchanged();
      }
      if (errors.length) throw Error(errors.join("\n"));
      return {ok: true, phase: "network", cases, recovered, unchanged: true};
    } finally {
      Object.assign(api, original);
    }
  }
  let api;
  try {
    await wait("shipping frontend and bridge", () => document.querySelector(".app-header") && window.pywebview?.api?.list_runs);
    api = window.pywebview.api;
    if (scenario.phase === "network") return await networkFailures();
    if (scenario.phase === "first") {
      // Only the startup terrain fixture is injected by the launcher.
      await editPayloadMass();
      await rename(scenario.name);
      await save(scenario.name);
      await rename(`${scenario.name} 다른 설계`);
      await save(`${scenario.name} 다른 설계`);
    }
    await load(scenario.name);
    const saved = await api.list_designs();
    const selected = saved.find((item) => item.name === scenario.name);
    const stored = await api.get_saved_design(selected.design_id);
    if (stored.components.find((component) => component.id === "payload").mass !== 1.05 || saved.length !== 2)
      throw Error("UI edit/save/load did not preserve the design");
    await click("rocket view", ".app-nav > button", "설계");
    await click("rocket 3D view", 'fieldset[aria-label="로켓 보기"] button', "3D");
    await wait("rocket 3D initialization", () => {
      const error = document.querySelector('fieldset[aria-label="로켓 보기"]')?.closest("section")?.querySelector(".notice");
      if (visible(error)) throw Error(text(error));
      return document.querySelector('[aria-label="로켓 3D 형상"] canvas');
    });
    const rocket = await canvas('[aria-label="로켓 3D 형상"] canvas');
    let run;
    if (scenario.phase === "first") {
      await click("simulate through UI", ".app-header button", "↗ 시뮬레이션 실행");
      run = await wait("completed simulation", async () => {
        const runs = await api.list_runs();
        if (runs.some((item) => ["failed", "cancelled", "interrupted"].includes(item.state)))
          throw Error(JSON.stringify(runs));
        return runs.find((item) => item.state === "succeeded");
      }, 60000);
    } else {
      await openPanel("작업 · 문제");
      await click("persisted run in history", "button.text-button", scenario.run_id.slice(0, 8));
      run = (await api.list_runs()).find((item) => item.run_id === scenario.run_id && item.state === "succeeded");
      if (!run) throw Error("Saved simulation is unavailable after relaunch");
    }
    await wait("result heading and chart", () => [...document.querySelectorAll("h2")]
      .some((node) => visible(node) && text(node) === `비행 결과 · ${run.run_id.slice(0, 8)}`) &&
      [...document.querySelectorAll("svg.chart polyline")].some((node) => visible(node) && node.getAttribute("points").trim().split(/\s+/).length > 2));
    await wait("result metrics", () => [...document.querySelectorAll(".metrics strong")]
      .filter(visible).length >= 3);
    const terrain = await canvas(".cesium-widget canvas");
    if (rocket.antialias !== false || terrain.antialias !== false || terrain.msaa_samples !== 1)
      throw Error("A renderer enabled multisampling despite the single-sample configuration");
    const mapInfo = await wait("map information disclosure", () => document.querySelector(".map-info"));
    if (mapInfo.open) throw Error("Map information should start collapsed");
    mapInfo.querySelector("summary").click();
    await painted();
    await wait("local terrain and saved trajectory", () => [...document.querySelectorAll(".caption")]
      .some((node) => visible(node) && node.textContent.includes("Local CI terrain fixture")) &&
      [...document.querySelectorAll('.caption[role="status"]')].some((node) => visible(node) && node.textContent.includes(`${run.run_id.slice(0, 8)} · 3D 궤적`)));
    if (document.body.textContent.includes("지도 렌더링 실패") || document.body.textContent.includes("지도를 시작할 수 없습니다"))
      throw Error("Terrain viewer reported a rendering failure");
    if ((await api.list_runs()).length !== 1) throw Error("Unexpected extra simulation runs");
    const summary = await api.get_summary(run.run_id);
    if (!(summary.max_altitude_agl_m > 0) || !(summary.duration_s > 0) || summary.ground_model !== "terrain") throw Error("Invalid flight result");
    mapInfo.querySelector("summary").click();
    await painted();
    return {ok: true, phase: scenario.phase, name: scenario.name, run_id: run.run_id, summary, rocket, terrain};
  } catch (error) {
    return {ok: false, phase: scenario.phase, stage, error: String(error), errors,
      url: location.href, body: document.body?.innerText.slice(-12000),
      active_tabs: [...document.querySelectorAll('[role="tab"][aria-selected="true"]')].map((node) => node.getAttribute("aria-label")),
      editor: document.querySelector("#design-json")?.value.slice(0, 2000)};
  }
})()
