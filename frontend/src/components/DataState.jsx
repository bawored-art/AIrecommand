export function LoadingState({ label = "불러오는 중..." }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-sm text-slate-400">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-600 border-t-sky-400" />
      {label}
    </div>
  );
}

export function ErrorState({ message = "데이터를 불러오지 못했습니다." }) {
  return (
    <div className="rounded-xl border border-rose-900/50 bg-rose-950/40 p-6 text-center text-sm text-rose-300">
      {message}
      <div className="mt-1 text-xs text-rose-400/80">
        네트워크 상태를 확인하거나 잠시 후 다시 시도해 주세요.
      </div>
    </div>
  );
}

export function EmptyState({ message = "표시할 데이터가 없습니다." }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-6 text-center text-sm text-slate-400">
      {message}
    </div>
  );
}
