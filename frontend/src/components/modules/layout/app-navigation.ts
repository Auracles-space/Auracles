/**
 * Authenticated application navigation definitions.
 *
 * Centralises link visibility so middleware, layouts, and tests rely on one
 * role-filter contract for UX-only navigation disclosure.
 */

export type AppNavigationLink = {
  href: string;
  label: string;
  roles: string[] | null;
};

/**
 * Shared authenticated navigation links and their role visibility.
 */
export const appLinks: AppNavigationLink[] = [
  // Ordered from most to least used. Links are role-filtered, so each role
  // sees this order minus what it cannot use: the marketplace entry first,
  // then each role's daily work, periodic management, occasional tools, and
  // Admin and Settings last.
  { href: "/explore", label: "Explore", roles: null },
  { href: "/dashboard/frameworks", label: "Frameworks", roles: ["contributor"] },
  { href: "/library", label: "Library", roles: ["operator"] },
  { href: "/projects", label: "Projects", roles: ["operator", "contributor"] },
  { href: "/attestations", label: "Attestations", roles: ["contributor", "operator"] },
  { href: "/dashboard/financials", label: "Financials", roles: ["contributor"] },
  { href: "/dashboard/organizations", label: "Organizations", roles: null },
  { href: "/dashboard/collections", label: "Collections", roles: ["contributor"] },
  { href: "/settings/saved-searches", label: "Saved Searches", roles: ["operator"] },
  { href: "/attestors", label: "Find Attestors", roles: null },
  {
    href: "/dashboard/developer",
    label: "Developer",
    roles: ["contributor", "developer"],
  },
  { href: "/admin/analytics", label: "Admin", roles: ["admin"] },
  { href: "/settings/identity", label: "Settings", roles: null },
];

/**
 * Filter authenticated navigation links for the active role set.
 *
 * @param links - Full navigation link definitions.
 * @param roles - Active roles from the verified session hint.
 */
export function visibleNavLinks(
  links: AppNavigationLink[],
  roles: string[],
): AppNavigationLink[] {
  return links.filter((link) => {
    if (link.roles === null) {
      return true;
    }

    return link.roles.some((role) => roles.includes(role));
  });
}
