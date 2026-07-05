import { useEffect, useState } from "react";

const BASE = import.meta.env.BASE_URL;

// public/data/*.json만 fetch한다 — API 서버 호출은 없다 (Stage4 정적 파이프라인 산출물 그대로).
export function useJsonData(path) {
  const [state, setState] = useState({ data: null, loading: true, error: null });

  useEffect(() => {
    let cancelled = false;
    setState({ data: null, loading: true, error: null });

    fetch(`${BASE}data/${path}`, { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error(`${path} 응답 오류 (HTTP ${res.status})`);
        return res.json();
      })
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, error: null });
      })
      .catch((error) => {
        if (!cancelled) setState({ data: null, loading: false, error });
      });

    return () => {
      cancelled = true;
    };
  }, [path]);

  return state;
}
