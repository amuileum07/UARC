/** Create a usable WebGL 2 context, with one retry without multisampling. */
export function createWebGL2Canvas(): {
  canvas: HTMLCanvasElement;
  context: WebGL2RenderingContext;
} {
  const failures: string[] = [];
  for (const antialias of [true, false]) {
    const canvas = document.createElement("canvas");
    let context: WebGL2RenderingContext | null = null;
    try {
      context = canvas.getContext("webgl2", { antialias, alpha: true });
      if (!context) throw new Error("WebGL 2 is unavailable");
      if (context.isContextLost())
        throw new Error("WebGL 2 context was lost during creation");
      const vertex = context.getShaderPrecisionFormat(
        context.VERTEX_SHADER,
        context.HIGH_FLOAT,
      );
      const fragment = context.getShaderPrecisionFormat(
        context.FRAGMENT_SHADER,
        context.HIGH_FLOAT,
      );
      if (!vertex || !fragment)
        throw new Error(
          `Shader precision unavailable (lost=${context.isContextLost()}, error=${context.getError()})`,
        );
      return { canvas, context };
    } catch (error) {
      failures.push(`antialias=${antialias}: ${String(error)}`);
      context?.getExtension("WEBGL_lose_context")?.loseContext();
    }
  }
  // Retry only without MSAA; never fabricate shader capabilities or loop forever.
  throw new Error(`WebGL 2 initialization failed. ${failures.join("; ")}`);
}
