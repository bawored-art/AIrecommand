import { useState } from "react";

const LABELS = {
  vpd: "VPD", onchain_growth: "온체인", developer: "개발자", user_ecosystem: "사용자",
  catalyst: "촉매", valuation: "밸류에이션", risk: "리스크",
};

export default function ScoreWaterfall({ breakdown, overheatPenalty }) {
  const [openKey, setOpenKey] = useState(null);
  const entries = Object.entries(breakdown || {});
  const maxWeight = Math.max(...entries.map(([, v]) => v.weight || 1), 1);

  return (
    <div className="space-y-2">
      {entries.map(([key, cat]) => {
        const widthPct = Math.max(4, Math.abs(cat.points / maxWeight) * 100);
        const isOpen = openKey === key;
        const percentile = cat.percentile ?? cat.sector_percentile;
        return (
          <div key={key}>
            <button onClick={() => setOpenKey(isOpen ? null : key)} className="flex w-full items-center gap-2 text-left">
              <span className="w-20 shrink-0 text-xs text-slate-400">{LABELS[key] || key}</span>
              <span className="relative h-4 flex-1 overflow-hidden rounded bg-slate-800">
                <span
                  className={`absolute inset-y-0 left-0 rounded ${cat.missing ? "bg-slate-600" : "bg-sky-500"}`}
                  style={{ width: `${widthPct}%` }}
                />
              </span>
              <span className="w-16 shrink-0 text-right text-xs font-semibold text-slate-200">
                {cat.points >= 0 ? "+" : ""}
                {cat.points?.toFixed(1)} / {cat.weight}
              </span>
            </button>
            {isOpen && (
              <div className="ml-20 mt-1 rounded-lg bg-slate-900 p-2 text-xs text-slate-400">
                {cat.missing && <span className="mr-1 text-amber-400">[데이터 없음 — 중립 점수 부여]</span>}
                {cat.reason}
                {percentile !== undefined && percentile !== null && (
                  <div className="mt-1 text-slate-500">유니버스 백분위: {percentile}</div>
                )}
              </div>
            )}
          </div>
        );
      })}
      <div className="flex items-center gap-2 pt-1 text-xs text-rose-400">
        <span className="w-20 shrink-0">과열필터</span>
        <span className="flex-1" />
        <span className="w-16 shrink-0 text-right font-semibold">-{(overheatPenalty ?? 0).toFixed(1)}</span>
      </div>
    </div>
  );
}
