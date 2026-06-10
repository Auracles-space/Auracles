"use client";

import * as React from "react";
import { MoonIcon, SunIcon } from "@radix-ui/react-icons";
import { useTheme } from "next-themes";

export function ThemeToggle() {
  const { theme, setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => {
    setMounted(true);
  }, []);

  const isDark = resolvedTheme === "dark";

  return (
    <button
      className="flex h-10 w-10 items-center justify-center rounded-control border border-border-default bg-surface-1 text-foreground-muted outline-none transition hover:bg-surface-2 hover:text-foreground focus-visible:ring-2 focus-visible:ring-accent"
      onClick={() => {
        const currentTheme = theme || "system";
        if (currentTheme === "system") setTheme("dark");
        else if (currentTheme === "dark") setTheme("light");
        else setTheme("system");
      }}
      title={`Toggle theme (current: ${theme || "system"})`}
      aria-label="Toggle theme"
    >
      {!mounted ? (
        <span className="h-5 w-5" />
      ) : theme === "dark" ? (
        <MoonIcon className="h-5 w-5" />
      ) : theme === "light" ? (
        <SunIcon className="h-5 w-5" />
      ) : (
        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-monitor">
          <rect width="20" height="14" x="2" y="3" rx="2" />
          <line x1="8" x2="16" y1="21" y2="21" />
          <line x1="12" x2="12" y1="17" y2="21" />
        </svg>
      )}
    </button>
  );
}
