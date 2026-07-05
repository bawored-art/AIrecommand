import { LineChart, Line, ResponsiveContainer, YAxis, Tooltip } from "recharts";

export default function Sparkline({ series, color = "#38bdf8", height = 48 }) {
  if (!series || !series.points || series.points.every((p) => p.value === null || p.value === undefined)) {
    return <div className="text-[11px] text-slate-600">데이터 없음</div>;
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={series.points}>
        <YAxis hide domain={["auto", "auto"]} />
        <Tooltip
          contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", fontSize: 11 }}
          labelStyle={{ color: "#94a3b8" }}
          formatter={(value) => [value?.toLocaleString?.() ?? value, ""]}
        />
        <Line type="monotone" dataKey="value" stroke={color} strokeWidth={2} dot={{ r: 3 }} connectNulls />
      </LineChart>
    </ResponsiveContainer>
  );
}
