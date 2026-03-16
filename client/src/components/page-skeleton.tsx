import { Skeleton } from "@/components/ui/skeleton";

interface PageSkeletonProps {
  /** Optional: number of KPI/card placeholders (default 4) */
  cards?: number;
  /** Optional: show a chart placeholder (default true) */
  chart?: boolean;
}

export function PageSkeleton({ cards = 4, chart = true }: PageSkeletonProps) {
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6 animate-fade-in">
      <div className="flex justify-between items-center">
        <div>
          <Skeleton className="h-7 w-48 mb-2" />
          <Skeleton className="h-4 w-32" />
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-9 w-24" />
          <Skeleton className="h-9 w-24" />
        </div>
      </div>
      <Skeleton className="h-20 w-full" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {Array.from({ length: cards }).map((_, i) => (
          <Skeleton key={i} className="h-24 w-full rounded-lg" />
        ))}
      </div>
      {chart && (
        <>
          <Skeleton className="h-10 w-full max-w-md" />
          <Skeleton className="h-64 w-full rounded-lg" />
        </>
      )}
    </div>
  );
}
