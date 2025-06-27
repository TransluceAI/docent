import { useAppSelector } from '../store/hooks';
import { RootState } from '../store/store';
import { cn } from '@/lib/utils';
const formatMetadataValue = (value: any): string => {
  if (typeof value === 'object' && value !== null) {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
};

type Props = {
  agentRunId: string;
  showCorrectnessBadge?: boolean;
};

export function AgentRunMetadata({
  agentRunId,
  showCorrectnessBadge = false,
}: Props) {
  const metadata = useAppSelector(
    (state: RootState) => state.frame.agentRunMetadata?.[agentRunId]
  );

  if (!metadata) {
    return null;
  }

  const entries = Object.entries(metadata);
  // @ts-expect-error index into metadata
  const isCorrect = metadata.scores[metadata?.default_score_key];
  return (
    <div className="pt-1 border-t border-gray-100 flex items-center gap-1.5 group text-[10px] text-gray-500 flex-1 truncate">
      {showCorrectnessBadge && isCorrect !== undefined && (
        <span
          className={cn(
            'text-green-500',
            isCorrect ? 'text-green-500' : 'text-red-500'
          )}
        >
          {isCorrect ? 'Correct' : 'Incorrect'}
        </span>
      )}
      {entries.map(([key, value], index) => (
        <span key={key}>
          <span className="font-medium">{key}: </span>
          {formatMetadataValue(value)}
          {index < entries.length - 1 ? ' • ' : ''}
        </span>
      ))}
    </div>
  );
}
