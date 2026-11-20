import { downloadCsv } from "./csvDownload.js";

function rupees(paise) {
  const absolute = Math.abs(paise);
  const sign = paise < 0 ? "-" : "";
  return `${sign}${Math.floor(absolute / 100)}.${String(absolute % 100).padStart(2, "0")}`;
}

export function salesCsv(report) {
  const rows = [
    "Date (IST),Payments (INR),Refunds (INR),Net sales (INR)",
    ...report.daily.map((day) => [
      day.date, rupees(day.payments_paise), rupees(day.refunds_paise), rupees(day.net_paise),
    ].join(",")),
    ["Total", rupees(report.payments_paise), rupees(report.refunds_paise), rupees(report.net_paise)].join(","),
  ];
  return rows.join("\r\n") + "\r\n";
}

export function salesCsvFilename(report) {
  const channel = report.channel?.kind === "website" ? `-website-${report.channel.website_id}`
    : report.channel?.kind === "direct" ? "-direct" : "";
  return `vyapari-sales${channel}-${report.start_date}-to-${report.end_date}.csv`;
}

export function downloadSalesCsv(report) {
  downloadCsv(salesCsv(report), salesCsvFilename(report));
}
