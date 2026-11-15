import { Pill } from "@/components/ui/Badge";

export function RegionPills({ regions }: { regions: string[] }) {
  if (!regions.length) return null;
  return (
    <div>
      <h4 className="mb-1.5 text-micro font-medium uppercase tracking-wide text-subtle">
        Typical regions
      </h4>
      <div className="flex flex-wrap gap-1.5">
        {regions.map((region) => (
          <Pill key={region}>{region}</Pill>
        ))}
      </div>
    </div>
  );
}
