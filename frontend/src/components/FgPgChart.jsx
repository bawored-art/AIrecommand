import { useEffect, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const BASE = import.meta.env.BASE_URL;

// 회차별 history/*.json 스냅샷을 모아 이 코인의 FG/PG를 시계열로 재구성한다.
// 정적 호스팅은 디렉터리 목록이 없어 history/index.json으로 어떤 회차가 있는지 먼저 확인한다.
export default function FgPgChart({ coinId }) {
  const [points, setPoints] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const idxRes = await fetch(`${BASE}data/history/index.json`, { cache: "no-store" });
        if (!idxRes.ok) throw new Error("index fetch failed");
        const idx = await idxRes.json();
        const entries = idx.entries || [];

        const results = await Promise.all(
          entries.map(async (entry) => {
            const res = await fetch(`${BASE}data/history/${entry}.json`, { cache: "no-store" });
            if (!res.ok) return null;
            const snapshot = await res.json();
            const item = (snapshot.items || []).find((i) => i.coin_id === coinId);
            if (!item) return null;
            return { label: entry, fg: item.fg_raw_pct, pg: item.pg_raw_pct };
          })
        );

        if (!cancelled) setPoints(results.filter(Boolean));
      } catch {
        if (!cancelled) setError(true);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [coinId]);

  if (error) return <p className="text-xs text-slate-600">FG/PG 히스토리를 불러오지 못했습니다.</p>;
  if (points === null) return <p className="text-xs text-slate-600">불러오는 중...</p>;

  if (points.length < 2) {
    const latest = points[0];
    return (
      <p className="text-xs text-slate-600">
        FG/PG 시계열은 파이프라인이 반복 실행되며 쌓입니다. 현재 {points.length}개 회차만 있어 그래프
        대신 최신 값만 표시합니다
        {latest ? ` (FG ${latest.fg}%, PG ${latest.pg}%)` : ""}.
      </p>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={points}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
        <XAxis dataKey="label" tick={{ fontSize: 10, fill: "#64748b" }} />
        <YAxis tick={{ fontSize: 10, fill: "#64748b" }} unit="%" />
        <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", fontSize: 12 }} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        <Line type="monotone" dataKey="fg" name="FG (펀더멘털 성장)" stroke="#34d399" strokeWidth={2} dot={{ r: 2 }} connectNulls />
        <Line type="monotone" dataKey="pg" name="PG (가격 변화)" stroke="#f472b6" strokeWidth={2} dot={{ r: 2 }} connectNulls />
      </LineChart>
    </ResponsiveContainer>
  );
}
