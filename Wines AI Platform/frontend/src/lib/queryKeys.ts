export const qk = {
  ready: ["ready"] as const,
  ageStatus: ["age-status"] as const,
  tasteAxes: ["meta", "taste-axes"] as const,
  datasetVersion: ["meta", "dataset-version"] as const,
  usage: ["meta", "usage"] as const,
  conversations: (archived: boolean, q: string) => ["conversations", { archived, q }] as const,
  conversation: (cid: string) => ["conversation", cid] as const,
};
