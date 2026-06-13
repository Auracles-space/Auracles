import { Skeleton } from "../skeleton";

export function TableSkeleton() {
  return (
    <div className="overflow-hidden rounded-2xl border border-border-default bg-surface-1 shadow-sm">
      <div className="border-b border-border-default bg-surface-2 p-4">
        <div className="flex justify-between">
          <Skeleton className="h-4 w-1/4 rounded-md" />
          <Skeleton className="h-4 w-1/4 rounded-md" />
          <Skeleton className="h-4 w-1/4 rounded-md" />
        </div>
      </div>
      <div className="divide-y divide-border-default p-4">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="flex items-center justify-between py-4">
            <Skeleton className="h-4 w-1/4 rounded-md" />
            <Skeleton className="h-4 w-1/4 rounded-md" />
            <Skeleton className="h-4 w-1/4 rounded-md" />
          </div>
        ))}
      </div>
    </div>
  );
}
