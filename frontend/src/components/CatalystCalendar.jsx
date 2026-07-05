export default function CatalystCalendar({ calendar }) {
  if (!calendar) return null;
  const catalysts = calendar.catalysts;

  return (
    <div className="space-y-2">
      {catalysts === null && (
        <p className="text-xs text-slate-600">LLM 미가용으로 촉매 분석이 생성되지 않았습니다.</p>
      )}
      {Array.isArray(catalysts) && catalysts.length === 0 && (
        <p className="text-xs text-slate-600">향후 3개월 내 확인된 촉매가 없습니다.</p>
      )}
      {Array.isArray(catalysts) &&
        catalysts.map((c, i) => (
          <div key={i} className="rounded-lg border border-slate-800 bg-slate-900/50 p-2 text-xs">
            <div className="flex items-center justify-between">
              <span className="rounded bg-sky-900/50 px-1.5 py-0.5 text-sky-300">{c.catalyst_type}</span>
              <span className="text-slate-500">{c.event_date || "날짜 미정"}</span>
            </div>
            <p className="mt-1 text-slate-300">{c.summary}</p>
            {c.url && (
              <a href={c.url} target="_blank" rel="noreferrer" className="text-slate-500 underline">
                출처: {c.source || "링크"}
              </a>
            )}
          </div>
        ))}
      <p className="text-[11px] text-slate-600">{calendar.token_unlock_note}</p>
    </div>
  );
}
