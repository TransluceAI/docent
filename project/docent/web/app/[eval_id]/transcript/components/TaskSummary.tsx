'use client';
import { useEffect } from 'react';
import { Datapoint, SolutionSummary } from '@/app/types/docent';
import { useFrameGrid } from '../../../contexts/FrameGridContext';
import ReactMarkdown from 'react-markdown';
import { Loader2 } from 'lucide-react';

interface TaskSummaryProps {
  datapoint: Datapoint | null;
  solutionSummary: SolutionSummary | null;
}

const TaskSummary: React.FC<TaskSummaryProps> = ({
  datapoint,
  solutionSummary,
}) => {
  const {
    requestSolutionSummary,
    clearSolutionSummary,
    loadingSolutionSummaryFor,
  } = useFrameGrid();

  // Request summary
  useEffect(() => {
    // If the datapoint is still loading, clear the summaries; there should be no summaries for those
    if (datapoint?.obj.metadata.is_loading_messages) {
      clearSolutionSummary();
    }
    // If we're loading summaries for a different datapoint, clear the summaries
    if (
      loadingSolutionSummaryFor &&
      loadingSolutionSummaryFor !== datapoint?.id
    ) {
      clearSolutionSummary();
    }
    // Otherwise, just request the summaries for the current datapoint
    if (datapoint?.id) {
      requestSolutionSummary(datapoint.id);
    }
  }, [datapoint?.id, datapoint?.obj.metadata.is_loading_messages]);

  // Loading indicator component for reuse
  const LoadingIndicator = () => (
    <div className="animate-pulse space-y-1">
      <div className="h-4 bg-slate-100 rounded w-3/4"></div>
      <div className="h-4 bg-slate-100 rounded w-2/3"></div>
      <div className="h-4 bg-slate-100 rounded w-4/5"></div>
    </div>
  );

  // If we have no datapoint at all, don't show anything
  if (!datapoint) {
    return null;
  }

  return (
    <div className="space-y-4 text-black">
      {/* <div className="space-y-2">
        <h4 className="text-sm font-semibold mb-2">Task Description</h4>
        <div className="text-sm mb-3 text-black">
          PicoCTF is a cybersecurity competition format where an AI agent is
          given access to a Docker filesystem and tasked with finding a hidden
          string (called a &quot;flag&quot;) somewhere within the system. The
          flag could be hidden in file contents, environment variables, or other
          locations that require exploration and investigation of the
          filesystem. This tests the agent&apos;s ability to navigate
          directories, read files, and use command-line tools to discover hidden
          information - similar to real-world security challenges where analysts
          need to find vulnerabilities or evidence of compromise.
        </div>
      </div> */}
      <div className="space-y-2">
        <h4 className="text-sm font-semibold mb-2 flex items-center">
          Intended Solution from the Benchmark (Summarized by an LLM)
          {loadingSolutionSummaryFor === datapoint?.id && (
            <Loader2 className="ml-2 h-4 w-4 animate-spin text-gray-500" />
          )}
        </h4>
        {solutionSummary ? (
          <div className="text-sm text-black">
            <div className="mb-2">{solutionSummary.summary}</div>
            {solutionSummary.parts.length > 0 && (
              <div className="space-y-2">
                {solutionSummary.parts.map((part, index) => (
                  <div
                    key={index}
                    className="prose prose-sm max-w-none text-black
                  prose-p:my-0.5 prose-p:leading-normal prose-p:text-black
                  prose-headings:mt-2 prose-headings:mb-1 prose-headings:text-black
                  prose-ul:my-0.5 prose-ul:pl-4
                  prose-ol:my-0.5 prose-ol:pl-4
                  prose-li:my-0 prose-li:leading-normal prose-li:text-black
                  prose-code:px-1 prose-code:py-0.5 prose-code:bg-slate-50 prose-code:rounded prose-code:text-black
                  prose-pre:my-1 prose-pre:p-2 prose-pre:bg-slate-50 prose-pre:rounded
                  prose-a:text-blue-600 prose-a:no-underline hover:prose-a:underline
                  prose-hr:my-2
                  prose-blockquote:my-1 prose-blockquote:pl-2 prose-blockquote:border-l-2 prose-blockquote:border-slate-200 prose-blockquote:italic prose-blockquote:text-black"
                  >
                    <ReactMarkdown>{part}</ReactMarkdown>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <LoadingIndicator />
        )}
        {!solutionSummary && !loadingSolutionSummaryFor && (
          <div className="text-sm text-gray-500">
            No solution summary available
          </div>
        )}
      </div>
    </div>
  );
};

export default TaskSummary;
