"use client";

/**
 * URL-aware Explore search panel.
 *
 * Keeps the search input client-side while the actual catalog response remains
 * server-rendered through query parameters.
 */
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

import { SearchInput } from "./search-input";

type SearchPanelProps = {
  initialValue?: string;
};

/**
 * Render a debounced search box that writes to `/explore?q=...`.
 *
 * @param props - Initial search query from SSR params.
 */
export function SearchPanel({ initialValue = "" }: SearchPanelProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const handleSearch = useCallback(
    (query: string) => {
      const params = new URLSearchParams(searchParams.toString());
      if (query) {
        params.set("q", query);
      } else {
        params.delete("q");
      }
      params.set("page", "1");
      router.push(`/explore?${params.toString()}`);
    },
    [router, searchParams],
  );

  return <SearchInput initialValue={initialValue} onSearch={handleSearch} />;
}
