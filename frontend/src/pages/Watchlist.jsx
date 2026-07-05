import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useJsonData } from "../lib/useJsonData";
import { useWatchlist } from "../lib/watchlist";
import { LoadingState } from "../components/DataState";

const BASE = import.meta.env.BASE_URL;

// 워치리스트에 있지만 최신 Top20에는 없는 코인은 개별 coins/{id}.json을 조회해 마지막으로
// 알려진 점수를 보여준다 (없으면 한 번도 Top20에 노출된 적 없다는 뜻).
function useMissingCoinDetails(watchedIds, recommendations) {
  const [details, setDetails] = useState({});
  const key = watchedIds.join(",");

  useEffect(() => {
    let cancelled = false;
    const inTop20 = new Set((recommendations?.items || []).map((i) => i.coin_id));
    const missing = watchedIds.filter((id) => !inTop20.has(id));

    if (missing.length === 0) {
      setDetails({});
      return undefined;
    }

    Promise.all(
      missing.map(async (id) => {
        try {
          const res = await fetch(`${BASE}data/coins/${id}.json`, { cache: "no-store" });
          if (!res.ok) return [id, null];
          const data = await res.json();
          return [id, {
            coin_id: id, symbol: data.symbol, name: data.name,
            final_score: data.score?.final_score, rank: null, notInTop20: true,
          }];
        } catch {
          return [id, null];
        }
      })
    ).then((results) => {
      if (!cancelled) setDetails(Object.fromEntries(results));
    });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, recommendations]);

  return details;
}

export default function Watchlist() {
  const { list, toggle, importFromJson, exportJson, clear } = useWatchlist();
  const { data: recommendations, loading } = useJsonData("recommendations.json");
  const [importError, setImportError] = useState(null);
  const [importSuccess, setImportSuccess] = useState(false);

  const missingDetails = useMissingCoinDetails(list, recommendations);
  const itemsById = Object.fromEntries((recommendations?.items || []).map((i) => [i.coin_id, i]));

  function handleExport() {
    const blob = new Blob([exportJson()], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "watchlist.json";
    a.click();
    URL.revokeObjectURL(url);
  }

  function handleImportFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        importFromJson(String(reader.result));
        setImportError(null);
        setImportSuccess(true);
        setTimeout(() => setImportSuccess(false), 2500);
      } catch (err) {
        setImportError(err.message);
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  }

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold text-slate-100">워치리스트</h1>
        <p className="mt-1 text-xs text-slate-500">
          이 기기(브라우저)의 localStorage에만 저장됩니다. 다른 기기·브라우저와 자동으로
          동기화되지 않으니, 옮기려면 아래 내보내기/가져오기를 사용하세요.
        </p>
      </header>

      <div className="flex flex-wrap gap-2">
        <button
          onClick={handleExport}
          className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700"
        >
          JSON 내보내기
        </button>
        <label className="cursor-pointer rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700">
          JSON 가져오기
          <input type="file" accept="application/json" className="hidden" onChange={handleImportFile} />
        </label>
        {list.length > 0 && (
          <button
            onClick={clear}
            className="rounded-lg bg-rose-950/50 px-3 py-1.5 text-xs font-medium text-rose-300 hover:bg-rose-900/50"
          >
            전체 삭제
          </button>
        )}
      </div>
      {importError && <p className="text-xs text-rose-400">가져오기 실패: {importError}</p>}
      {importSuccess && <p className="text-xs text-emerald-400">가져오기 완료.</p>}

      {loading ? (
        <LoadingState />
      ) : list.length === 0 ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-6 text-center text-sm text-slate-400">
          관심 코인이 없습니다. 코인 상세 페이지에서 "☆ 관심 등록"을 눌러 추가하세요.
        </div>
      ) : (
        <div className="space-y-2">
          {list.map((coinId) => {
            const item = itemsById[coinId] || missingDetails[coinId];
            return (
              <div key={coinId} className="flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-900/60 p-3">
                <div className="min-w-0 flex-1">
                  {item ? (
                    <Link to={`/coins/${coinId}`} className="font-semibold text-slate-100 hover:text-sky-400">
                      {item.name} <span className="text-xs uppercase text-slate-500">{item.symbol}</span>
                    </Link>
                  ) : (
                    <span className="font-semibold text-slate-400">{coinId}</span>
                  )}
                  {item?.rank ? (
                    <div className="mt-0.5 text-xs text-slate-500">
                      현재 {item.rank}위
                      {typeof item.rank_change === "number" && item.rank_change !== 0 && (
                        <span className={item.rank_change > 0 ? "ml-1 text-emerald-400" : "ml-1 text-rose-400"}>
                          ({item.rank_change > 0 ? "▲" : "▼"}
                          {Math.abs(item.rank_change)})
                        </span>
                      )}
                      {item.badge === "NEW" && <span className="ml-1 text-emerald-400">NEW</span>}
                    </div>
                  ) : (
                    <div className="mt-0.5 text-xs text-slate-600">
                      {item ? "현재 Top20 밖" : "데이터를 찾을 수 없습니다 (Top20에 노출된 적 없음)"}
                    </div>
                  )}
                </div>
                {item?.final_score !== undefined && (
                  <div className="shrink-0 text-right text-sm font-bold text-sky-400">{item.final_score?.toFixed(1)}</div>
                )}
                <button
                  onClick={() => toggle(coinId)}
                  className="shrink-0 rounded-lg bg-slate-800 px-2 py-1 text-xs text-slate-400 hover:bg-rose-950/50 hover:text-rose-300"
                >
                  삭제
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
