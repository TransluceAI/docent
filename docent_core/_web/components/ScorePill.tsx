import React from 'react';

/**
 * Returns the appropriate color classes based on the score value
 */
export const scoreToneClass = (score: number | null) => {
  if (score === null || Number.isNaN(score)) {
    return 'bg-secondary text-muted-foreground border-border';
  }
  if (score >= 9) return 'bg-green-bg text-green-text border-green-border';
  if (score >= 5) return 'bg-orange-bg text-orange-text border-orange-border';
  return 'bg-red-bg text-red-text border-red-border';
};

interface ScorePillProps {
  score: number | null;
  title?: string;
  className?: string;
}

/**
 * A pill component that displays a score with appropriate color coding
 */
export const ScorePill: React.FC<ScorePillProps> = ({
  score,
  title,
  className = '',
}) => {
  const baseClasses = 'px-2 py-0.5 rounded-full border text-xs font-medium';
  const colorClasses = scoreToneClass(score);
  const cls = `${baseClasses} ${colorClasses} ${className}`.trim();

  const label =
    score === null || Number.isNaN(score) ? 'N/A' : score.toFixed(2);

  return (
    <span className={cls} title={title}>
      {label}
    </span>
  );
};
