"use client";

import * as React from "react";
import { MoonIcon, SunIcon } from "@radix-ui/react-icons";
import { useTheme } from "next-themes";

export function ThemeToggle() {
  const { setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => {
    setMounted(true);
  }, []);
  return (
    <button
      className="flex h-10 w-10 items-center justify-center rounded-xl border border-border-default bg-surface-1 text-foreground-muted outline-none transition hover:bg-surface-2 hover:text-foreground focus-visible:ring-2 focus-visible:ring-accent"
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
      title={`Toggle theme (current: ${mounted ? resolvedTheme : "system"})`}
      aria-label="Toggle theme"
    >
      {!mounted ? (
        <span className="h-5 w-5" />
      ) : resolvedTheme === "dark" ? (
        <SunIcon className="h-5 w-5" />
      ) : (
        <MoonIcon className="h-5 w-5" />
      )}
    </button>
  );
}
