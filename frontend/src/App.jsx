import { HashRouter, NavLink, Route, Routes } from "react-router-dom";
import PasscodeGate from "./components/PasscodeGate";
import Disclaimer from "./components/Disclaimer";
import Dashboard from "./pages/Dashboard";
import CoinDetail from "./pages/CoinDetail";
import Watchlist from "./pages/Watchlist";

function Nav() {
  const linkClass = ({ isActive }) =>
    `rounded-lg px-3 py-2 text-sm font-medium ${
      isActive ? "bg-slate-800 text-sky-400" : "text-slate-400 hover:text-slate-200"
    }`;
  return (
    <nav className="sticky top-0 z-10 flex gap-1 border-b border-slate-800 bg-slate-950/90 px-3 py-2 backdrop-blur">
      <NavLink to="/" end className={linkClass}>
        대시보드
      </NavLink>
      <NavLink to="/watchlist" className={linkClass}>
        워치리스트
      </NavLink>
    </nav>
  );
}

export default function App() {
  return (
    <PasscodeGate>
      <HashRouter>
        <Disclaimer />
        <Nav />
        <main className="mx-auto max-w-3xl px-3 pb-16 pt-4">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/coins/:coinId" element={<CoinDetail />} />
            <Route path="/watchlist" element={<Watchlist />} />
          </Routes>
        </main>
      </HashRouter>
    </PasscodeGate>
  );
}
