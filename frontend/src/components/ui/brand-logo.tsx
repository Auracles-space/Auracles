import Image from "next/image";
import Link from "next/link";

type BrandLogoProps = {
  href?: string;
  className?: string;
};

export function BrandLogo({ href = "/explore", className = "relative h-8 w-32" }: BrandLogoProps) {
  return (
    <Link href={href} className={`block ${className}`}>
      {/* Light mode logo (hidden in dark mode) */}
      <Image
        src="/images/logo-text-black.png"
        alt="Auracles"
        fill
        className="object-contain object-left dark:hidden"
        priority
      />
      {/* Dark mode logo (hidden in light mode) */}
      <Image
        src="/images/logo-text-white.png"
        alt="Auracles"
        fill
        className="hidden object-contain object-left dark:block"
        priority
      />
    </Link>
  );
}
