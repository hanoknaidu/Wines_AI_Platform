import { TITLE_MAX_CHARS } from "./constants";
import type { ConversationSummary } from "@/types/api";

/** Today / Last 7 days / Older, as the architecture diagram groups the sidebar. */
export type GroupLabel = "Today" | "Last 7 days" | "Older";

export interface ConversationGroup {
  label: GroupLabel;
  items: ConversationSummary[];
}

function startOfToday(now: Date): number {
  const d = new Date(now);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

export function groupConversations(
  items: ConversationSummary[],
  now: Date = new Date(),
): ConversationGroup[] {
  const today = startOfToday(now);
  const weekAgo = today - 6 * 86_400_000;
  const buckets: Record<GroupLabel, ConversationSummary[]> = {
    Today: [],
    "Last 7 days": [],
    Older: [],
  };
  for (const item of items) {
    const at = new Date(item.updated_at).getTime();
    if (at >= today) buckets.Today.push(item);
    else if (at >= weekAgo) buckets["Last 7 days"].push(item);
    else buckets.Older.push(item);
  }
  return (["Today", "Last 7 days", "Older"] as GroupLabel[])
    .map((label) => ({ label, items: buckets[label] }))
    .filter((group) => group.items.length > 0);
}

export function relativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso).getTime();
  const seconds = Math.round((now.getTime() - then) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function truncateTitle(title: string): string {
  if (title.length <= TITLE_MAX_CHARS) return title;
  return `${title.slice(0, TITLE_MAX_CHARS).trimEnd()}...`;
}

/** Cost is reported, never estimated. $0.00 is a real and meaningful value here —
 *  the Phase-1 engine runs no model at all. */
export function formatCost(usd: number): string {
  if (usd === 0) return "$0.00";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

export function formatLatency(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function formatCount(n: number): string {
  return n.toLocaleString();
}

/** "fruit_savoury" -> "fruit / savoury". Axis IDS are not wine words; the LABELS
 *  that go with them always come from the server. */
export function axisIdToTitle(axisId: string): string {
  return axisId.replace(/_/g, " / ");
}
