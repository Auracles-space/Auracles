import { StarFilledIcon } from "@radix-ui/react-icons";

type RatingStarsProps = {
  rating: number;
  max?: number;
  className?: string;
  starClassName?: string;
};

/**
 * Displays a 5-star rating with partial fill support.
 */
export function RatingStars({
  rating,
  max = 5,
  className = "flex items-center gap-0.5",
  starClassName = "h-4 w-4",
}: RatingStarsProps) {
  return (
    <div
      className={className}
      aria-label={`Rating: ${rating} out of ${max} stars`}
      title={`${rating} out of ${max} stars`}
    >
      {Array.from({ length: max }).map((_, i) => {
        const fillPercentage = Math.max(0, Math.min(1, rating - i)) * 100;

        return (
          <div key={i} className={`relative ${starClassName}`}>
            {/* Background (Empty) Star */}
            <StarFilledIcon
              className={`absolute left-0 top-0 text-border-strong ${starClassName}`}
            />

            {/* Foreground (Filled) Star, clipped to fillPercentage */}
            {fillPercentage > 0 && (
              <div
                className="absolute left-0 top-0 h-full overflow-hidden"
                style={{ width: `${fillPercentage}%` }}
              >
                <StarFilledIcon
                  className={`absolute left-0 top-0 text-accent ${starClassName}`}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
