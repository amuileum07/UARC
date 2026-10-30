// Intel Mac virtual GPUs can remain unusable after the first MSAA request:
// https://github.com/actions/runner-images/issues/14836
// Use single-sample contexts from the start in both renderers.
export const webglContextAttributes = { antialias: false } as const;

/** Create a single-sample WebGL 2 context with real shader capabilities. */
export function createWebGL2Canvas(): {
  canvas: HTMLCanvasElement;
  context: WebGL2RenderingContext;
} {
  const canvas = document.createElement("canvas");
  let context: WebGL2RenderingContext | null = null;
  try {
    context = canvas.getContext("webgl2", {
      ...webglContextAttributes,
      alpha: true,
    });
    if (!context) throw new Error("WebGL 2 is unavailable");
    if (context.isContextLost())
      throw new Error(
        "WebGL 2 context was lost during creation (MSAA disabled)",
      );
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
    context?.getExtension("WEBGL_lose_context")?.loseContext();
    throw error;
  }
}
