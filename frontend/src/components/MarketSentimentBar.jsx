import { formatPct } from "../lib/format";

const FEAR_GREED_COLORS = {
  "Extreme Fear": "text-rose-400",
  Fear: "text-orange-400",
  Neutral: "text-amber-300",
  Greed: "text-lime-400",
  "Extreme Greed": "text-emerald-400",
};

export default function MarketSentimentBar({ market }) {
  if (!market) return null;
  const fg = market.fear_greed;
  return (
    <div className="grid grid-cols-3 gap-2 rounded-xl border border-slate-800 bg-slate-900/60 p-3 text-center">
      <div>
        <div className="text-[11px] text-slate-500">BTC 도미넌스</div>
        <div className="font-semibold text-slate-100">{formatPct(market.btc_dominance_pct)}</div>
      </div>
      <div>
        <div className="text-[11px] text-slate-500">ETH 도미넌스</div>
        <div className="font-semibold text-slate-100">{formatPct(market.eth_dominance_pct)}</div>
      </div>
      <div>
        <div className="text-[11px] text-slate-500">Fear &amp; Greed</div>
        {fg ? (
          <div className={`font-semibold ${FEAR_GREED_COLORS[fg.classification] || "text-slate-100"}`}>
            {fg.value} · {fg.classification}
          </div>
        ) : (
          <div className="text-slate-500">N/A</div>
        )}
      </div>
    </div>
  );
}
