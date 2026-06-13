import { Skeleton } from "../skeleton";

export function CardSkeleton() {
  return (
    <div className="flex flex-col gap-4 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
      <div className="flex items-start justify-between">
        <Skeleton className="h-10 w-10 rounded-xl" />
        <Skeleton className="h-6 w-24 rounded-md" />
      </div>
      <div className="space-y-2 mt-2">
        <Skeleton className="h-6 w-3/4 rounded-md" />
        <Skeleton className="h-4 w-full rounded-md" />
        <Skeleton className="h-4 w-2/3 rounded-md" />
      </div>
      <div className="mt-4 flex items-center gap-3">
        <Skeleton className="h-8 w-8 rounded-full" />
        <Skeleton className="h-4 w-24 rounded-md" />
      </div>
    </div>
  );
}
