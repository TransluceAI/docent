'use client';
import { Loader2 } from 'lucide-react';
import { useEffect } from 'react';
import ReactMarkdown from 'react-markdown';

import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import {
  getSolutionSummary,
} from '@/app/store/transcriptSlice';

const TaskSummary: React.FC = () => {
  const dispatch = useAppDispatch();
  const agentRun = useAppSelector((state) => state.transcript.curAgentRun);
  const solutionSummary = useAppSelector(
    (state) => state.transcript.solutionSummary
  );
  const loadingSolutionSummaryForTranscriptId = useAppSelector(
    (state) => state.transcript.loadingSolutionSummaryForTranscriptId
  );

  // Request summary
  useEffect(() => {
    if (!agentRun) {
      return;
    }

    // Request summary if we don't already have it loaded, and we're not loading it yet
    if (
      loadingSolutionSummaryForTranscriptId !== agentRun.id &&
      solutionSummary?.agent_run_id != agentRun.id
    ) {
      dispatch(getSolutionSummary(agentRun.id));
    }
  }, [
    agentRun,
    loadingSolutionSummaryForTranscriptId,
    dispatch,
    solutionSummary?.agent_run_id,
  ]);

  // Loading indicator component for reuse
  const LoadingIndicator = () => (
    <div className="animate-pulse space-y-1">
      <div className="h-4 bg-slate-100 rounded w-3/4"></div>
      <div className="h-4 bg-slate-100 rounded w-2/3"></div>
      <div className="h-4 bg-slate-100 rounded w-4/5"></div>
    </div>
  );

  // If we have no datapoint at all, don't show anything
  if (!agentRun) {
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
          {loadingSolutionSummaryForTranscriptId === agentRun?.id && (
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
        {!solutionSummary && !loadingSolutionSummaryForTranscriptId && (
          <div className="text-sm text-gray-500">
            No solution summary available
          </div>
        )}
      </div>
    </div>
  );
};

export default TaskSummary;
