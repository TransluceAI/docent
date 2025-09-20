import { Loader2 } from 'lucide-react';

interface ProgressBarProps {
  current: number;
  total: number | null;
  paused?: boolean;
}

export const ProgressBar = ({
  current,
  total,
  paused = false,
}: ProgressBarProps) => {
  return (
    <div className="mt-2 mb-2 space-y-1">
      <div className="flex justify-between text-xs text-muted-foreground">
        <span className="flex items-center">
          Processing...
          {!paused && (
            <Loader2
              size={12}
              className="ml-1.5 animate-spin text-muted-foreground"
            />
          )}
        </span>
        <span>
          {current} / {total === 0 || !total ? '?' : total}
        </span>
      </div>
      <div className="w-full bg-accent rounded-full h-1.5">
        <div
          className="bg-blue-600 h-1.5 rounded-full transition-all duration-300 ease-in-out"
          style={{
            width: `${
              total !== null && total > 0 && current > 0
                ? Math.min((current / total) * 100, 100)
                : 0
            }%`,
          }}
        ></div>
      </div>
    </div>
  );
};
