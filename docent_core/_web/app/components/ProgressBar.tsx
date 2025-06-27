import { Loader2 } from 'lucide-react';

interface ProgressBarProps {
  current: number;
  total: number;
  paused?: boolean;
}

export const ProgressBar = ({ current, total, paused = false }: ProgressBarProps) => {
  return (
    <div className="mt-2 mb-2 space-y-1">
      <div className="flex justify-between text-xs text-gray-600">
        <span className="flex items-center">
          Processing datapoints
          {!paused &&
          <Loader2 className="h-3 w-3 ml-1.5 animate-spin text-gray-500" />
          }
        </span>
        <span>
          {current} / {total}
        </span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-1.5">
        <div
          className="bg-blue-600 h-1.5 rounded-full transition-all duration-300 ease-in-out"
          style={{
            width: `${
              current > 0 ? Math.min((current / total) * 100, 100) : 0
            }%`,
          }}
        ></div>
      </div>
    </div>
  );
};
