// Projection from the existing Control Room snapshot; never infer calendar
// success from a sent command or a previous day's boot.
export function calendarRebootView(status) {
  const state = String(status?.state || "unknown");
  const source = String(status?.source || "");
  const when = status?.verified_at || status?.last_boot_at;
  const timestamp = when && Number.isFinite(new Date(when).getTime())
    ? new Intl.DateTimeFormat("da-DK", {
        timeZone: "Europe/Copenhagen", hour: "2-digit", minute: "2-digit",
      }).format(new Date(when))
    : null;
  if (state === "completed") {
    const calendar = source === "calendar";
    return {
      label: timestamp
        ? `${calendar ? "Kalendergenstart" : "Opstart"} ${timestamp}`
        : (calendar ? "Kalendergenstart i dag" : "Opstart i dag"),
      color: "success",
      title: source === "calendar"
        ? "Kalendergenstart verificeret med nyt boot-ID"
        : "Klienten er startet i dag. Genstartens årsag er ikke dokumenteret som kalender.",
    };
  }
  if (state === "error") return { label: "Genstart fejl", color: "error", title: "Dagens kalendergenstart er ikke verificeret" };
  if (state === "not_scheduled") return { label: "Ingen åbning i dag", color: "default", title: "Ingen kalenderstyret genstart planlagt i dag" };
  if (state === "pending") return { label: "Genstart afventer", color: "warning", title: "Afventer dagens kalenderstyrede åbning eller bekræftelse" };
  return { label: "Genstart ukendt", color: "default", title: "Manglende, forældet eller offline status – ikke en bekræftet genstart" };
}
