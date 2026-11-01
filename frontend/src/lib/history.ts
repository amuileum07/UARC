import { desktopApi } from "./bridge.ts";
import type { RunRecord, SavedDesignRecord } from "./types";

export function watchHistory(
  changed: (runs: RunRecord[], designs: SavedDesignRecord[]) => void,
  failed: (error: unknown) => void,
) {
  let active = true;
  let loading = false;
  let pending = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  async function refresh() {
    if (!active) return;
    if (loading) {
      pending = true;
      return;
    }
    clearTimeout(timer);
    loading = true;
    try {
      const api = await desktopApi();
      const [runs, designs] = await Promise.all([
        api.list_runs(),
        api.list_designs(),
      ]);
      if (active) changed(runs, designs);
    } catch (error) {
      if (active) failed(error);
    } finally {
      loading = false;
      if (active) {
        if (pending) {
          pending = false;
          void refresh();
        } else {
          // Recover from a lost native notification without constant idle IPC.
          timer = setTimeout(refresh, 30_000);
        }
      }
    }
  }
  window.addEventListener("uarc:history-changed", refresh);
  window.addEventListener("focus", refresh);
  void refresh();
  return () => {
    active = false;
    clearTimeout(timer);
    window.removeEventListener("uarc:history-changed", refresh);
    window.removeEventListener("focus", refresh);
  };
}
