import Image from "next/image";
import Link from "next/link";

type BrandLogoProps = {
  href?: string;
  className?: string;
  variant?: "auto" | "light" | "dark";
};

export function BrandLogo({ href = "/", className = "h-8 w-32", variant = "auto" }: BrandLogoProps) {
  const showBlack = variant === "light" || variant === "auto";
  const showWhite = variant === "dark" || variant === "auto";

  return (
    <Link href={href} className={`relative block shrink-0 ${className}`}>
      {/* Black text logo */}
      {showBlack && (
        <Image
          src="/images/logo-text-black.png"
          alt="Auracles"
          fill
          className={`object-contain object-left ${variant === "auto" ? "dark:hidden" : ""}`}
          priority
        />
      )}
      {/* White text logo */}
      {showWhite && (
        <Image
          src="/images/logo-text-white.png"
          alt="Auracles"
          fill
          className={`object-contain object-left ${variant === "auto" ? "hidden dark:block" : ""}`}
          priority
        />
      )}
    </Link>
  );
}
