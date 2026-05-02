import React from "react";

export default function MetricCard({
  title,
  value,
  suffix,
  trend = null,
  trendDirection = "neutral",
}) {
  return (
    <article className="metric-card">
      <span className="metric-title">{title}</span>
      <p className="metric-value">
        {value}
        {suffix ? <span className="metric-suffix">{suffix}</span> : null}
      </p>
      {trend ? (
        <span className={`metric-trend metric-${trendDirection}`}>
          {trend}
        </span>
      ) : null}
    </article>
  );
}
