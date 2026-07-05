import { useJsonData } from "../lib/useJsonData";
import { LoadingState, ErrorState, EmptyState } from "../components/DataState";
import MarketSentimentBar from "../components/MarketSentimentBar";
import MomentumLeaders from "../components/MomentumLeaders";
import CoinCard from "../components/CoinCard";
import { formatKstDateTime } from "../lib/format";

export default function Dashboard() {
  const { data: meta, loading: metaLoading, error: metaError } = useJsonData("meta.json");
  const { data: recommendations, loading: recLoading, error: recError } = useJsonData("recommendations.json");
  const { data: market } = useJsonData("market.json");
  const { data: momentumLeaders } = useJsonData("momentum-leaders.json");

  if (metaLoading || recLoading) return <LoadingState label="Top20 불러오는 중..." />;
  if (metaError || recError) return <ErrorState message="대시보드 데이터를 불러오지 못했습니다." />;

  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <h1 className="text-xl font-bold text-slate-100">Top20 펀더멘털 리서치</h1>
        {meta && (
          <p className="text-xs text-slate-500">
            마지막 업데이트 {formatKstDateTime(meta.last_updated_kst)} · 다음 갱신 예정{" "}
            {formatKstDateTime(meta.next_update_kst)}
            {meta.status === "degraded" && (
              <span className="ml-2 rounded bg-amber-900/50 px-1.5 py-0.5 text-amber-300">일부 데이터 지연/결측</span>
            )}
          </p>
        )}
      </header>

      <MarketSentimentBar market={market} />

      {recommendations?.relaxed_mode && (
        <div className="rounded-lg border border-amber-900/50 bg-amber-950/30 px-3 py-2 text-xs text-amber-300">
          유니버스 내 과열되지 않은 후보가 20개 미만이라 완화된 기준으로 순위가 산출되었습니다.
        </div>
      )}

      <section className="space-y-2">
        {recommendations?.items?.length ? (
          recommendations.items.map((item) => <CoinCard key={item.coin_id} item={item} />)
        ) : (
          <EmptyState message="표시할 Top20 데이터가 없습니다." />
        )}
      </section>

      {recommendations?.exited_since_last_run?.length > 0 && (
        <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-3 text-xs text-slate-500">
          전 회차 대비 이탈: {recommendations.exited_since_last_run.map((c) => c.name).join(", ")}
        </section>
      )}

      <MomentumLeaders data={momentumLeaders} />
    </div>
  );
}
