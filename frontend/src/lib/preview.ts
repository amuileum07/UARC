/** Coalesces edits; at most one request runs and only the current revision wins. */
export function previewQueue<T, R>(
  request: (value: T) => Promise<R>,
  result: (value: R) => void,
  error: (error: unknown) => void,
  delay = 120,
) {
  let revision = 0;
  let running = false;
  let pending: { value: T; revision: number } | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let disposed = false;
  async function flush() {
    if (running || !pending || disposed) return;
    const current = pending;
    pending = undefined;
    running = true;
    try {
      const response = await request(current.value);
      if (!disposed && current.revision === revision) result(response);
    } catch (reason) {
      if (!disposed && current.revision === revision) error(reason);
    } finally {
      running = false;
      if (pending && !disposed) {
        clearTimeout(timer);
        timer = setTimeout(flush, delay);
      }
    }
  }
  return {
    push(value: T) {
      if (disposed) return;
      pending = { value, revision: ++revision };
      clearTimeout(timer);
      timer = setTimeout(flush, delay);
    },
    dispose() {
      disposed = true;
      revision++;
      pending = undefined;
      clearTimeout(timer);
    },
  };
}
