'use client';

import { AlertTriangle } from 'lucide-react';
import { JudgeResultWithCitations } from '@/app/store/rubricSlice';

type FailureError = {
  type?: string;
  user_message?: string;
  error_type_id?: string;
  failed_output?: string;
  message?: string;
};

interface FailedResultCardProps {
  result: JudgeResultWithCitations;
}

const truncate = (text: string, max = 220) =>
  text.length > max ? `${text.slice(0, max)}…` : text;

const getErrorDetails = (result: JudgeResultWithCitations) => {
  const errors = Array.isArray(result.result_metadata?.errors)
    ? (result.result_metadata.errors as FailureError[])
    : [];

  const primary = errors[0];
  const message =
    primary?.user_message ||
    primary?.message ||
    primary?.type ||
    'Judge run failed without a model response.';
  const code = primary?.error_type_id || primary?.type;
  const failedOutput =
    primary?.failed_output && typeof primary.failed_output === 'string'
      ? truncate(primary.failed_output)
      : undefined;

  return { message, code, failedOutput };
};

const FailedResultCard = ({ result }: FailedResultCardProps) => {
  const { message, code, failedOutput } = getErrorDetails(result);

  return (
    <div className="space-y-1 text-xs">
      <div className="flex items-center gap-1.5">
        <AlertTriangle className="size-3 text-red-500 flex-shrink-0" />
        <span className="font-semibold text-red-500">Evaluation failed</span>
        {code && (
          <span className="text-[10px] uppercase tracking-wide text-red-500">
            ({code})
          </span>
        )}
      </div>
      <p className="text-muted-foreground leading-snug">{message}</p>
      {failedOutput && (
        <p className="text-muted-foreground">
          <span className="font-medium text-foreground">Last output:</span>{' '}
          {failedOutput}
        </p>
      )}
    </div>
  );
};

export default FailedResultCard;
