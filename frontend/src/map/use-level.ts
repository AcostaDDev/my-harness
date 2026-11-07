// React binding of a `LevelLoader` (P002-T022): one loader per path, shared by the map levels and the requests
// panel. A new path disposes the old loader, so its late answers are never applied, and the state of another path is
// never returned (a level never sees the pages of the level it replaced).
import { useCallback, useEffect, useRef, useState } from "react";
import { read } from "./api.ts";
import type { Paged } from "./api.ts";
import { LevelLoader } from "./loader.ts";
import type { LevelState } from "./loader.ts";

export type Loaded<T extends Paged> = { state: LevelState<T>; reload: () => void; loadMore: () => void; canLoadMore: boolean };
const IDLE: LevelState<never> = { pages: [], skipped: 0, loading: false, missing: false, recovered: false };

export function useLevel<T extends Paged>(path: string | null): Loaded<T> {
  const fresh = (): LevelState<T> => path ? { ...IDLE, loading: true } : IDLE;
  const [entry, setEntry] = useState<{ path: string | null; state: LevelState<T> }>(() => ({ path, state: fresh() }));
  const loader = useRef<LevelLoader<T> | undefined>(undefined);
  useEffect(() => {
    if (!path) { loader.current = undefined; setEntry({ path, state: IDLE }); return; }
    const current = new LevelLoader<T>(path, read, next => setEntry({ path, state: next }));
    loader.current = current;
    setEntry({ path, state: current.state });
    current.reload();
    return () => current.dispose();
  }, [path]);
  const reload = useCallback(() => loader.current?.reload(), []);
  const loadMore = useCallback(() => loader.current?.loadMore(), []);
  const state = entry.path === path ? entry.state : fresh();
  return { state, reload, loadMore, canLoadMore: !!loader.current && loader.current.path === path && loader.current.canLoadMore };
}
