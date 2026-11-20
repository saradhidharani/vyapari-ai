import React from "react";

// Shared by Analytics and the agency dashboard so both use the same periods,
// INR formatting, and stat card layout.
export const salesPeriods = ["last 7 days", "today", "yesterday", "this week", "last week", "this month", "last month"];

export const periodLabel = (period) => period[0].toUpperCase() + period.slice(1);

export const money = (value) =>
  "₹" + Number(value).toLocaleString("en-IN");

export function Stat({ label, value, change, icon: Icon }) {
  return (
    <div className="stat">
      <div className="stat-top">
        <span>{label}</span>

        <span className="stat-icon">
          <Icon size={19} />
        </span>
      </div>

      <strong>{value}</strong>
      <small>{change}</small>
    </div>
  );
}
