import { BaseAgentRunMetadata } from '../types/collectionTypes';
const formatMetadataValue = (value: any): string => {
  if (typeof value === 'object' && value !== null) {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
};

type Props = {
  metadata: BaseAgentRunMetadata;
};

export function AgentRunMetadata({ metadata }: Props) {
  if (!metadata) {
    return null;
  }

  const entries = Object.entries(metadata);
  return (
    <div className="pt-1 border-t border-border flex items-center gap-1.5 group text-[10px] text-muted-foreground flex-1 truncate">
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
