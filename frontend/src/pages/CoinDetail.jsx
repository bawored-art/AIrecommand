import { Link, useParams } from "react-router-dom";
import { useJsonData } from "../lib/useJsonData";
import { LoadingState, ErrorState } from "../components/DataState";
import { formatUsd, formatPct } from "../lib/format";
import { useWatchlist } from "../lib/watchlist";
import ScoreWaterfall from "../components/ScoreWaterfall";
import FgPgChart from "../components/FgPgChart";
import Sparkline from "../components/Sparkline";
import ConfidenceGauge from "../components/ConfidenceGauge";
import CatalystCalendar from "../components/CatalystCalendar";

const METRIC_LABELS = {
  tvl_usd: "TVL", stablecoin_inflow_usd: "스테이블코인 유입", fees_24h_usd: "24시간 수수료",
};

function Stat({ label, value }) {
  return (
    <div className="rounded-lg bg-slate-900/60 p-2">
      <div className="text-[10px] text-slate-500">{label}</div>
      <div className="text-sm font-semibold text-slate-200">{value}</div>
    </div>
  );
}

export default function CoinDetail() {
  const { coinId } = useParams();
  const { data: coin, loading, error } = useJsonData(`coins/${coinId}.json`);
  const { isWatched, toggle } = useWatchlist();

  if (loading) return <LoadingState label="코인 상세 불러오는 중..." />;
  if (error || !coin) return <ErrorState message="코인 데이터를 찾을 수 없습니다." />;

  const ov = coin.overview || {};
  const watched = isWatched(coin.coin_id);
  const metricSeries = Object.entries(coin.metric_series || {}).filter(([, series]) => series);

  return (
    <div className="space-y-4">
      <Link to="/" className="text-xs text-slate-500 hover:text-slate-300">
        ← 대시보드로
      </Link>

      <div className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h1 className="text-lg font-bold text-slate-100">
              #{coin.rank} {coin.name} <span className="text-sm uppercase text-slate-500">{coin.symbol}</span>
            </h1>
            {ov.one_liner && <p className="text-sm text-slate-300">{ov.one_liner}</p>}
          </div>
          <button
            onClick={() => toggle(coin.coin_id)}
            className={`shrink-0 rounded-lg px-3 py-1.5 text-xs font-medium ${
              watched ? "bg-amber-500 text-slate-950" : "bg-slate-800 text-slate-300 hover:bg-slate-700"
            }`}
          >
            {watched ? "★ 관심 코인" : "☆ 관심 등록"}
          </button>
        </div>

        {ov.description_summary ? (
          <p className="text-sm text-slate-400">
            {ov.description_summary}{" "}
            {ov.description_source && <span className="text-[11px] text-slate-600">(출처: {ov.description_source})</span>}
          </p>
        ) : (
          <p className="text-xs text-slate-600">코인 개요 요약이 아직 생성되지 않았습니다.</p>
        )}

        {ov.categories?.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {ov.categories.slice(0, 6).map((c) => (
              <span key={c} className="rounded bg-slate-800 px-2 py-0.5 text-[11px] text-slate-400">
                {c}
              </span>
            ))}
          </div>
        )}

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="체인" value={ov.chain || "N/A"} />
          <Stat label="출시연도" value={ov.launch_year || "N/A"} />
          <Stat label="현재가" value={formatUsd(coin.price_usd)} />
          <Stat label="시가총액" value={formatUsd(coin.market_cap_usd)} />
        </div>
        {ov.primary_use_case && <p className="text-xs text-slate-500">주요 용도: {ov.primary_use_case}</p>}
      </div>

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h2 className="mb-2 text-sm font-semibold text-slate-200">FG(펀더멘털 성장) vs PG(가격 변화)</h2>
        <FgPgChart coinId={coin.coin_id} />
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-200">점수 분해</h2>
          <span className="text-lg font-bold text-sky-400">{coin.score.final_score.toFixed(1)}</span>
        </div>
        <ScoreWaterfall breakdown={coin.score.breakdown} overheatPenalty={coin.overheat?.penalty} />
        {coin.score.summary && <p className="mt-2 text-[11px] text-slate-600">{coin.score.summary}</p>}
      </section>

      {metricSeries.length > 0 && (
        <section className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h2 className="text-sm font-semibold text-slate-200">지표 30/90일 추이</h2>
          {metricSeries.map(([key, series]) => (
            <div key={key}>
              <div className="mb-1 text-xs text-slate-400">{METRIC_LABELS[key] || key}</div>
              <Sparkline series={series} />
            </div>
          ))}
        </section>
      )}

      {coin.detailed_reasons?.length > 0 && (
        <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h2 className="mb-2 text-sm font-semibold text-slate-200">상세 추천 이유</h2>
          <ul className="list-disc space-y-1 pl-4 text-sm text-slate-300">
            {coin.detailed_reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h2 className="mb-2 text-sm font-semibold text-slate-200">리스크 요약</h2>
        <p className="text-sm text-slate-300">{coin.risk_summary || "리스크 요약이 아직 생성되지 않았습니다."}</p>
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h2 className="mb-2 text-sm font-semibold text-slate-200">향후 촉매/이벤트</h2>
        <CatalystCalendar calendar={coin.upcoming_catalysts} />
      </section>

      <section className="rounded-xl border border-amber-900/30 bg-slate-900/60 p-4">
        <h2 className="mb-2 text-sm font-semibold text-slate-200">
          참고 정보{" "}
          <span className="rounded bg-amber-900/40 px-1.5 py-0.5 text-[10px] text-amber-300">점수 미반영</span>
        </h2>
        <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
          <Stat label="RSI(14)" value={coin.technical_reference?.rsi_14 ?? "N/A"} />
          <Stat label="200일MA 괴리율" value={formatPct(coin.technical_reference?.ma_200d_deviation_pct)} />
          <Stat label="30일 수익률" value={formatPct(coin.technical_reference?.return_30d_pct)} />
          <Stat label="90일 수익률" value={formatPct(coin.technical_reference?.return_90d_pct)} />
        </div>
      </section>

      {coin.ai_summary && (
        <section className="rounded-xl border border-sky-900/40 bg-sky-950/20 p-4">
          <h2 className="mb-2 text-sm font-semibold text-sky-300">AI 총평</h2>
          <p className="text-sm text-slate-200">{coin.ai_summary}</p>
        </section>
      )}

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h2 className="mb-2 text-sm font-semibold text-slate-200">Confidence</h2>
        <ConfidenceGauge confidence={coin.confidence} />
      </section>
    </div>
  );
}
