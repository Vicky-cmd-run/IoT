import React from "react";
import { Activity, Car, Timer, Zap, TrendingUp, TrendingDown, Minus } from "lucide-react";

const getIcon = (title) => {
  const lowerTitle = title.toLowerCase();
  if (lowerTitle.includes("speed")) return <Zap size={20} />;
  if (lowerTitle.includes("density")) return <Activity size={20} />;
  if (lowerTitle.includes("time")) return <Timer size={20} />;
  return <Car size={20} />;
};

export default function MetricCard({ title, value, suffix, trend = null, trendDirection = "neutral" }) {
  return (
    <article className="metric-card">
      <div>
        <div className="metric-header">
          <h3>{title}</h3>
          <div className="metric-icon">
            {getIcon(title)}
          </div>
        </div>
        <p className="metric-value">
          {value}
          <span style={{ fontSize: "1.2rem", color: "var(--muted)", marginLeft: "4px" }}>{suffix}</span>
        </p>
      </div>
      
      {trend && (
        <div className={`metric-trend ${trendDirection}`}>
          {trendDirection === "up" && <TrendingUp size={16} />}
          {trendDirection === "down" && <TrendingDown size={16} />}
          {trendDirection === "neutral" && <Minus size={16} />}
          <span>{trend}</span>
        </div>
      )}
    </article>
  );
}
