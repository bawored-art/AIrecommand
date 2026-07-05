import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "altcoin-research-watchlist";

// 워치리스트는 기기 로컬 localStorage에만 저장된다 — 기기 간 동기화는 없다 (UI에서 명시).

export function getWatchlist() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveWatchlist(list) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...new Set(list)]));
}

export function exportWatchlistJson() {
  return JSON.stringify({ version: 1, exportedAt: new Date().toISOString(), coinIds: getWatchlist() }, null, 2);
}

export function parseWatchlistJson(jsonText) {
  const parsed = JSON.parse(jsonText);
  const coinIds = Array.isArray(parsed) ? parsed : parsed.coinIds;
  if (!Array.isArray(coinIds) || !coinIds.every((id) => typeof id === "string")) {
    throw new Error("올바른 워치리스트 파일이 아닙니다.");
  }
  return coinIds;
}

export function useWatchlist() {
  const [list, setList] = useState(getWatchlist);

  useEffect(() => {
    const onStorage = (e) => {
      if (!e.key || e.key === STORAGE_KEY) setList(getWatchlist());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const isWatched = useCallback((coinId) => list.includes(coinId), [list]);

  const toggle = useCallback((coinId) => {
    setList((prev) => {
      const next = prev.includes(coinId) ? prev.filter((id) => id !== coinId) : [...prev, coinId];
      saveWatchlist(next);
      return next;
    });
  }, []);

  const importFromJson = useCallback((jsonText) => {
    const coinIds = parseWatchlistJson(jsonText);
    saveWatchlist(coinIds);
    setList(getWatchlist());
  }, []);

  const clear = useCallback(() => {
    saveWatchlist([]);
    setList([]);
  }, []);

  return { list, isWatched, toggle, importFromJson, exportJson: exportWatchlistJson, clear };
}
