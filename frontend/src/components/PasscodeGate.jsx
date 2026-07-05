import { useState } from "react";

const STORAGE_KEY = "altcoin-research-gate-unlocked";
// 빌드 시점에 번들에 그대로 포함되는 값이라 완전한 보안이 아니다 (README에도 명시).
// 값을 비워두면(.env 미설정) 게이트 자체가 비활성화된다.
const PASSCODE = import.meta.env.VITE_ACCESS_PASSCODE || "";

export default function PasscodeGate({ children }) {
  const [unlocked, setUnlocked] = useState(
    () => !PASSCODE || localStorage.getItem(STORAGE_KEY) === "true"
  );
  const [input, setInput] = useState("");
  const [error, setError] = useState(false);

  if (unlocked) return children;

  function handleSubmit(e) {
    e.preventDefault();
    if (input === PASSCODE) {
      localStorage.setItem(STORAGE_KEY, "true");
      setUnlocked(true);
    } else {
      setError(true);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 p-6">
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-4 rounded-2xl bg-slate-900 p-6 shadow-xl">
        <h1 className="text-lg font-semibold text-slate-100">접근 코드 입력</h1>
        <p className="text-sm text-slate-400">
          이 화면은 완전한 보안이 아니라 간단한 접근 제한입니다. 코드가 클라이언트 코드에
          포함되어 있어 완전히 비공개로 유지되지는 않습니다.
        </p>
        <input
          type="password"
          autoFocus
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            setError(false);
          }}
          className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-slate-100 outline-none focus:border-sky-500"
          placeholder="접근 코드"
        />
        {error && <p className="text-sm text-rose-400">코드가 올바르지 않습니다.</p>}
        <button
          type="submit"
          className="w-full rounded-lg bg-sky-500 px-3 py-2 font-medium text-slate-950 hover:bg-sky-400"
        >
          입장
        </button>
      </form>
    </div>
  );
}
