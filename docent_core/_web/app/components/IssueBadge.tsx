import { Badge } from '@/components/ui/badge';
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

const COLOR_RED = 'bg-red-100 text-red-800 border-red-300';
const COLOR_YELLOW = 'bg-yellow-100 text-yellow-800 border-yellow-300';

const issueMetadata: Record<
  string,
  { label: string; subtitle: string; color: string }
> = {
  human_miss: {
    label: 'Incomplete label',
    subtitle:
      'The judge identified a behavior that the human label does not address',
    color: COLOR_YELLOW,
  },
  ai_miss: {
    label: 'Miss',
    subtitle:
      'The judge fails to consider a behavior identified in the human label',
    color: COLOR_RED,
  },
  false_negative: {
    label: 'False Negative',
    subtitle:
      'The judge states that the behavior does not match the rubric, but the human label states that it does',
    color: COLOR_RED,
  },
  false_positive: {
    label: 'False Positive',
    subtitle:
      'The judge states that the behavior matches the rubric, but the human label states that it does not',
    color: COLOR_RED,
  },
};

interface IssueBadgeProps {
  type: string;
  count?: number;
}

export function IssueBadge({ type, count }: IssueBadgeProps) {
  const meta = issueMetadata[type];
  if (!meta) return null;

  const badge = (
    <Badge variant="outline" className={cn('text-xs', meta.color)}>
      {count ? `${count} ` : ''}
      {meta.label}
      {count && count > 1 && !meta.label.endsWith('s') ? 's' : ''}
    </Badge>
  );

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-block">{badge}</span>
      </TooltipTrigger>
      <TooltipContent>
        <div className="flex flex-col gap-1">
          <p className="text-xs">{meta.subtitle}</p>
        </div>
      </TooltipContent>
    </Tooltip>
  );
}
