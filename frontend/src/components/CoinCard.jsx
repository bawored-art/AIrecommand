import { Link } from "react-router-dom";
import { formatUsd } from "../lib/format";

function RankChangeBadge({ badge, rankChange }) {
  if (badge === "NEW") {
    return (
      <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] font-bold text-emerald-400">NEW</span>
    );
  }
  if (rankChange > 0) return <span className="text-xs font-medium text-emerald-400">▲{rankChange}</span>;
  if (rankChange < 0) return <span className="text-xs font-medium text-rose-400">▼{Math.abs(rankChange)}</span>;
  return <span className="text-xs text-slate-600">–</span>;
}

export default function CoinCard({ item }) {
  return (
    <Link
      to={`/coins/${item.coin_id}`}
      className="flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-900/60 p-3 transition hover:border-sky-700"
    >
      <div className="w-7 shrink-0 text-center text-sm font-semibold text-slate-400">#{item.rank}</div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate font-semibold text-slate-100">{item.name}</span>
          <span className="text-xs uppercase text-slate-500">{item.symbol}</span>
          <RankChangeBadge badge={item.badge} rankChange={item.rank_change} />
        </div>
        <p className="mt-0.5 line-clamp-2 text-xs text-slate-400">
          {item.leading_evidence_summary || "선행 근거 요약이 아직 생성되지 않았습니다."}
        </p>
      </div>
      <div className="shrink-0 text-right">
        <div className="text-lg font-bold text-sky-400">{item.final_score?.toFixed(1)}</div>
        <div className="text-[11px] text-slate-500">신뢰도 {item.confidence_score?.toFixed(0)}</div>
        <div className="text-[11px] text-slate-500">{formatUsd(item.price_usd)}</div>
      </div>
    </Link>
  );
}
