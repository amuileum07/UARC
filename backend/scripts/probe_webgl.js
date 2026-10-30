(async () => {
  const scenario = /* SCENARIO */ {};
  let gl;
  try {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 4;
    document.body.append(canvas);
    await new Promise(requestAnimationFrame);
    gl = canvas.getContext("webgl2", {antialias: false, alpha: false});
    if (!gl || gl.isContextLost()) throw Error("Native WebGL 2 context is unavailable or lost before the app loads");
    const compile = (type, source) => {
      const shader = gl.createShader(type);
      if (!shader) throw Error("Native shader creation failed");
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw Error(gl.getShaderInfoLog(shader));
      return shader;
    };
    const vertex = compile(gl.VERTEX_SHADER, `#version 300 es
      const vec2 points[3] = vec2[3](vec2(-1.0,-1.0), vec2(3.0,-1.0), vec2(-1.0,3.0));
      void main() { gl_Position = vec4(points[gl_VertexID], 0.0, 1.0); }`);
    const fragment = compile(gl.FRAGMENT_SHADER, `#version 300 es
      precision highp float;
      out vec4 color;
      void main() { color = vec4(1.0, 0.0, 0.0, 1.0); }`);
    const program = gl.createProgram();
    if (!program) throw Error("Native program creation failed");
    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(program));
    gl.useProgram(program);
    gl.viewport(0, 0, 4, 4);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.finish();
    const pixel = new Uint8Array(4);
    gl.readPixels(1, 1, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
    if (gl.isContextLost() || gl.getError() !== gl.NO_ERROR || pixel.join(",") !== "255,0,0,255")
      throw Error(`Native triangle readback failed: ${pixel}`);
    const info = gl.getExtension("WEBGL_debug_renderer_info");
    return {ok: true, phase: scenario.phase, pixel: Array.from(pixel),
      renderer: gl.getParameter(info ? info.UNMASKED_RENDERER_WEBGL : gl.RENDERER),
      version: gl.getParameter(gl.VERSION), antialias: gl.getContextAttributes()?.antialias};
  } catch (error) {
    return {ok: false, phase: scenario.phase, error: String(error),
      context_lost: gl?.isContextLost(), error_code: gl?.getError(), user_agent: navigator.userAgent};
  } finally {
    // Finish GPU work before this disposable native process closes its window.
    gl?.finish();
  }
})()
