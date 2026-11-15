import type { Card, Chips, Intent } from "@/types/api";

export interface WineRow {
  row_id: string;
  variety: string;
  style: string;
  sweetness: string;
  body: string | null;
  oak: string | null;
  tannin: string | null;
  acidity: string | null;
  fruit_savoury: string | null;
  confidence: Record<string, number>;
  description: string;
  typical_regions: string[];
  example_producers: string[];
  review_status: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  dataset_version: string;
}

export interface DatasetArtifact {
  dataset_version: string;
  built_at: string | null;
  notes?: string;
  rows: WineRow[];
}

export type Profile = Record<string, string | null | undefined>;

/** What the engine yields, mirroring `turns/engine.py`'s TurnEvent union. The runner
 *  in ../stream.ts is what turns these into seq-stamped SSE frames. */
export type EngineEvent =
  | { t: "token"; text: string }
  | { t: "card"; row_id: string; card: Card }
  | { t: "chips"; chips: Chips }
  | { t: "citation"; row_ids: string[] }
  | {
      t: "profile";
      values: Record<string, string>;
      confidence: Record<string, { confidence: number; provenance: string }>;
    }
  | { t: "usage"; intent: Intent | "unknown"; intent_confidence: number; model: string };

export interface TurnRequest {
  utterance: string;
  selected_chip_id?: string | null;
  profile: Profile;
  previous_row_ids: string[];
}
