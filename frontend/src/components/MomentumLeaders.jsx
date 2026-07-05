import { useState } from "react";
import { formatPct } from "../lib/format";

export default function MomentumLeaders({ data }) {
  const [open, setOpen] = useState(false);
  if (!data || data.count === 0) return null;

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40">
      <button onClick={() => setOpen((v) => !v)} className="flex w-full items-center justify-between px-4 py-3 text-left">
        <span className="text-sm font-semibold text-slate-200">
          모멘텀 리더 ({data.count})
          <span className="ml-2 rounded bg-slate-700 px-1.5 py-0.5 text-[10px] font-semibold text-slate-300">
            참고용 — 추천 아님
          </span>
        </span>
        <span className="text-slate-500">{open ? "접기 ▲" : "펼치기 ▼"}</span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-slate-800 px-4 py-3">
          <p className="text-xs text-slate-500">
            과열 필터(30일 +60% 또는 90일 +150% 초과)에 걸려 Top20에서 제외된 코인입니다. 펀더멘털
            점수가 아니라 이미 가격이 크게 오른 상태이므로 추천 목록이 아닙니다.
          </p>
          {data.items.map((coin) => (
            <div key={coin.coin_id} className="rounded-lg bg-slate-900 p-2 text-sm">
              <div className="flex items-center justify-between">
                <span className="font-medium text-slate-200">
                  {coin.name} <span className="text-xs uppercase text-slate-500">{coin.symbol}</span>
                </span>
                <span className="text-xs text-slate-400">기본점수 {coin.base_score?.toFixed(1)}</span>
              </div>
              <div className="mt-1 text-xs text-slate-500">
                30일 {formatPct(coin.return_30d_pct)} · 90일 {formatPct(coin.return_90d_pct)}
              </div>
              {coin.excluded_reasons?.length > 0 && (
                <ul className="mt-1 list-disc pl-4 text-[11px] text-slate-500">
                  {coin.excluded_reasons.map((reason, i) => (
                    <li key={i}>{reason}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
