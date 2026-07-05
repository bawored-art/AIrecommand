import { PolarAngleAxis, RadialBar, RadialBarChart, ResponsiveContainer } from "recharts";

export default function ConfidenceGauge({ confidence }) {
  if (!confidence) return null;
  const score = confidence.score ?? 0;
  const color = score >= 70 ? "#34d399" : score >= 40 ? "#facc15" : "#f87171";
  const data = [{ name: "confidence", value: score, fill: color }];

  return (
    <div className="flex items-center gap-4">
      <div className="h-24 w-24 shrink-0">
        <ResponsiveContainer>
          <RadialBarChart innerRadius="70%" outerRadius="100%" data={data} startAngle={90} endAngle={-270}>
            <PolarAngleAxis type="number" domain={[0, 100]} angleAxisId={0} tick={false} />
            <RadialBar dataKey="value" background={{ fill: "#1e293b" }} cornerRadius={8} />
          </RadialBarChart>
        </ResponsiveContainer>
      </div>
      <div>
        <div className="text-2xl font-bold text-slate-100">{score.toFixed(0)}</div>
        <div className="text-xs text-slate-500">
          커버리지 {(confidence.coverage * 100).toFixed(0)}% · 신선도 {(confidence.freshness * 100).toFixed(0)}% ·
          일관성 {(confidence.consistency * 100).toFixed(0)}%
        </div>
      </div>
    </div>
  );
}
