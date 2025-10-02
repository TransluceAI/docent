'use client';

import React, { useState, useEffect, useRef } from 'react';
import Link from 'next/link';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { ChevronDown, ChevronRight, ExternalLink, Loader2 } from 'lucide-react';
import {
  AgentRunsBlock,
  type RunItem,
  type Block,
  sortRunsByGrade,
  computeMeanScore,
} from '@/components/AgentRunsBlock';
import { useParams, useSearchParams, useRouter } from 'next/navigation';
import { BASE_URL } from '@/app/constants';
import type {
  ExperimentStreamData,
  CounterfactualContext,
} from '@/types/experiment';
import {
  useGetExperimentResultQuery,
  useGetActiveExperimentJobsQuery,
} from '@/app/api/investigatorApi';
import InvestigatorAgentRunViewer from '@/app/investigator/[workspace_id]/components/InvestigatorAgentRunViewer';
import type { ToolInfo } from '@/app/investigator/[workspace_id]/components/BaseContextEditor';
import { AgentRun } from '@/app/types/transcriptTypes';

function CodeBlock({ value }: { value?: string }) {
  const text = value ?? '';
  return (
    <div className="not-prose flex flex-col">
      <pre className="text-sm w-full overflow-x-auto dark:bg-zinc-900 p-4 border border-zinc-200 dark:border-zinc-700 rounded-xl dark:text-zinc-50 text-zinc-900">
        <code className="whitespace-pre-wrap break-words">{text}</code>
      </pre>
    </div>
  );
}

interface CounterfactualExperimentViewerProps {
  experimentConfigId: string;
  onCloneAgentRunToContext?: (data: {
    messages: Array<{ role: string; content: string }>;
    tools?: ToolInfo[];
    counterfactualName?: string;
  }) => void;
}

export default function CounterfactualExperimentViewer({
  experimentConfigId,
  onCloneAgentRunToContext,
}: CounterfactualExperimentViewerProps) {
  const params = useParams();
  const workspaceId = params.workspace_id as string;
  const searchParams = useSearchParams();
  const router = useRouter();

  // Local state for experiment data
  const [experimentStream, setExperimentStream] =
    useState<ExperimentStreamData>({});
  const [selectedAgentRunId, setSelectedAgentRunId] = useState<
    string | undefined
  >();
  const [selectedAgentRun, setSelectedAgentRun] = useState<AgentRun | null>(
    null
  );
  const [isLoadingAgentRun, setIsLoadingAgentRun] = useState(false);

  // Helper function to update URL query parameters
  const updateQueryParams = (agentRunId?: string) => {
    const currentParams = new URLSearchParams(searchParams.toString());

    if (agentRunId) {
      currentParams.set('agent_run_id', agentRunId);
    } else {
      currentParams.delete('agent_run_id');
    }

    const newUrl = `${window.location.pathname}?${currentParams.toString()}`;
    router.push(newUrl, { scroll: false });
  };

  // Ref to access selectedAgentRunId in SSE handler
  const selectedAgentRunIdRef = useRef<string | undefined>();
  selectedAgentRunIdRef.current = selectedAgentRunId;
  const jobIdRef = useRef<string | undefined>();

  // Initialize selected agent run from URL on mount
  const [hasInitializedFromUrl, setHasInitializedFromUrl] = useState(false);

  useEffect(() => {
    if (!hasInitializedFromUrl) {
      const agentRunIdFromUrl = searchParams.get('agent_run_id');
      if (agentRunIdFromUrl) {
        setSelectedAgentRunId(agentRunIdFromUrl);
        // The actual loading will be triggered by the effect below
      }
      setHasInitializedFromUrl(true);
    }
  }, [searchParams, hasInitializedFromUrl]);

  // Fetch experiment result from database
  const { data: experimentResult, refetch: refetchResult } =
    useGetExperimentResultQuery(
      { workspaceId, experimentConfigId },
      {
        pollingInterval: experimentStream.activeJobId ? 5000 : 0,
        skip: !experimentConfigId,
      }
    );

  // Check for active jobs in the workspace
  const { data: activeJobs } = useGetActiveExperimentJobsQuery(workspaceId, {
    skip: !experimentConfigId,
  });
  const activeJobData = activeJobs?.[experimentConfigId];

  // Load agent run data when selected from URL
  useEffect(() => {
    if (
      hasInitializedFromUrl &&
      selectedAgentRunId &&
      !selectedAgentRun &&
      !isLoadingAgentRun &&
      experimentResult // Wait for experiment data to be loaded
    ) {
      // Check if this agent run exists in the metadata
      const agentRunExists =
        experimentResult.agent_run_metadata?.[selectedAgentRunId];
      if (!agentRunExists) {
        // Agent run doesn't exist, clear selection and URL
        setSelectedAgentRunId(undefined);
        updateQueryParams();
        return;
      }

      const loadAgentRunFromUrl = async () => {
        setIsLoadingAgentRun(true);

        // Check if experiment is running
        const isRunning = !!activeJobData?.job_id;

        if (isRunning && activeJobData?.job_id) {
          // Subscribe to the agent run for live updates
          try {
            await fetch(
              `${BASE_URL}/rest/investigator/${workspaceId}/experiment/job/${activeJobData.job_id}/subscribe-agent-run`,
              {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ agent_run_id: selectedAgentRunId }),
                credentials: 'include',
              }
            );
            // Data will arrive through the SSE connection
          } catch (error) {
            console.error('Error subscribing to agent run from URL:', error);
            setIsLoadingAgentRun(false);
          }
        } else {
          // Experiment complete - fetch from database
          try {
            const response = await fetch(
              `${BASE_URL}/rest/investigator/${workspaceId}/experiment/${experimentConfigId}/agent-run/${selectedAgentRunId}`,
              {
                credentials: 'include',
              }
            );
            if (response.ok) {
              const agentRun = await response.json();
              setSelectedAgentRun(agentRun);
            } else {
              console.error(
                'Failed to fetch agent run from URL:',
                response.statusText
              );
              setSelectedAgentRun(null);
              setSelectedAgentRunId(undefined);
              updateQueryParams();
            }
          } catch (error) {
            console.error('Error fetching agent run from URL:', error);
            setSelectedAgentRun(null);
            setSelectedAgentRunId(undefined);
            updateQueryParams();
          } finally {
            setIsLoadingAgentRun(false);
          }
        }
      };

      loadAgentRunFromUrl();
    }
  }, [
    hasInitializedFromUrl,
    selectedAgentRunId,
    selectedAgentRun,
    isLoadingAgentRun,
    experimentResult,
    activeJobData?.job_id,
    workspaceId,
    experimentConfigId,
  ]);

  // Update experiment stream from database result
  useEffect(() => {
    if (experimentResult) {
      const counterfactualContextById: Record<string, CounterfactualContext> =
        {};

      // Transform database format to local state format
      if (experimentResult.counterfactual_context_output) {
        for (const [id, value] of Object.entries(
          experimentResult.counterfactual_context_output
        )) {
          counterfactualContextById[id] = {
            id,
            value: value as string,
          };
        }
      }

      // Add names from parsed counterfactual ideas
      if (experimentResult.parsed_counterfactual_ideas?.counterfactuals) {
        for (const [id, cf] of Object.entries(
          experimentResult.parsed_counterfactual_ideas
            .counterfactuals as Record<string, { name?: string }>
        )) {
          if (counterfactualContextById[id]) {
            counterfactualContextById[id].name = cf?.name;
          } else {
            counterfactualContextById[id] = {
              id,
              name: cf?.name,
            };
          }
        }
      }

      setExperimentStream({
        activeJobId: activeJobData?.job_id || undefined,
        counterfactualIdeaOutput:
          experimentResult.counterfactual_idea_output || '',
        counterfactualContextById,
        experimentStatus: experimentResult.experiment_status,
        agentRunMetadataById: experimentResult.agent_run_metadata || {},
        docentCollectionId: experimentResult.docent_collection_id,
      });
    } else {
      // Clear the state when experimentResult is null
      setExperimentStream({});
    }
  }, [experimentResult, activeJobData]);

  // Stream data from SSE if job is active
  useEffect(() => {
    if (!activeJobData?.job_id || !experimentConfigId) return;

    const jobId = activeJobData.job_id;
    const eventSource = new EventSource(
      `${BASE_URL}/rest/investigator/${workspaceId}/experiment/job/${jobId}/listen`,
      { withCredentials: true }
    );

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        // Update local state based on SSE messages
        setExperimentStream((prev) => {
          const updated = { ...prev };

          if (data.counterfactual_idea_output !== undefined) {
            updated.counterfactualIdeaOutput = data.counterfactual_idea_output;
          }

          if (data.counterfactual_context_output) {
            const contextById: Record<string, CounterfactualContext> = {};
            for (const [id, value] of Object.entries(
              data.counterfactual_context_output
            )) {
              contextById[id] = {
                id,
                value: value as string,
                name: prev.counterfactualContextById?.[id]?.name,
              };
            }
            updated.counterfactualContextById = contextById;
          }

          if (data.parsed_counterfactual_ideas?.counterfactuals) {
            const contextById = {
              ...(updated.counterfactualContextById || {}),
            };
            for (const [id, cf] of Object.entries(
              data.parsed_counterfactual_ideas.counterfactuals as Record<
                string,
                { name?: string }
              >
            )) {
              if (contextById[id]) {
                contextById[id].name = cf?.name;
              } else {
                contextById[id] = {
                  id,
                  name: cf?.name,
                };
              }
            }
            updated.counterfactualContextById = contextById;
          }

          if (data.experiment_status) {
            updated.experimentStatus = data.experiment_status;
          }

          if (data.agent_run_metadata) {
            updated.agentRunMetadataById = {
              ...(updated.agentRunMetadataById || {}),
              ...data.agent_run_metadata,
            };
          }

          if (data.docent_collection_id) {
            updated.docentCollectionId = data.docent_collection_id;
          }

          // Handle subscribed agent runs - full data for viewing
          if (
            data.subscribed_agent_runs &&
            typeof data.subscribed_agent_runs === 'object'
          ) {
            const runs = data.subscribed_agent_runs as Record<string, AgentRun>;
            // Update the selected agent run if it's in the subscribed runs
            for (const [runId, agentRun] of Object.entries(runs)) {
              if (runId === selectedAgentRunIdRef.current) {
                setSelectedAgentRun(agentRun);
                setIsLoadingAgentRun(false);
              }
            }
          }

          return updated;
        });

        // Refetch result when stream ends
        if (
          data.experiment_status?.status === 'completed' ||
          data.experiment_status?.status === 'error' ||
          data.experiment_status?.status === 'cancelled'
        ) {
          refetchResult();
        }
      } catch (error) {
        console.error('Error parsing SSE message:', error);
      }
    };

    eventSource.onerror = (error) => {
      console.error('SSE error:', error);
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }, [activeJobData?.job_id, experimentConfigId, workspaceId, refetchResult]);

  // Parse experiment data
  const ideaOutput = experimentStream?.counterfactualIdeaOutput;
  const contextOutput = experimentStream?.counterfactualContextById;
  const agentRuns = experimentStream?.agentRunMetadataById;
  const jobId = experimentStream?.activeJobId;
  jobIdRef.current = jobId;
  const experimentStatus = experimentStream?.experimentStatus;
  const isExperimentErrored = experimentStatus?.status === 'error';
  const isExperimentCancelled = experimentStatus?.status === 'cancelled';
  const experimentErrorMessage = experimentStatus?.error_message;
  const docentCollectionId = experimentStream?.docentCollectionId;

  // Cleanup subscriptions when component unmounts or experiment changes
  useEffect(() => {
    return () => {
      // Unsubscribe from any active agent run subscription
      const currentAgentRunId = selectedAgentRunIdRef.current;
      const currentJobId = jobIdRef.current;
      if (currentAgentRunId && currentJobId) {
        fetch(
          `${BASE_URL}/rest/investigator/${workspaceId}/experiment/job/${currentJobId}/unsubscribe-agent-run`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ agent_run_id: currentAgentRunId }),
            credentials: 'include',
          }
        ).catch((error) => {
          console.error('Error unsubscribing on cleanup:', error);
        });
      }
    };
  }, [experimentConfigId]); // Cleanup when switching experiments

  // Clear loading state when agent run data arrives
  useEffect(() => {
    if (selectedAgentRun && isLoadingAgentRun) {
      setIsLoadingAgentRun(false);
    }
  }, [selectedAgentRun]);

  const [isIdeaOpen, setIsIdeaOpen] = useState(false);
  const [isContextOpen, setIsContextOpen] = useState(false);
  const [ideaUserTouched, setIdeaUserTouched] = useState(false);
  const [contextUserTouched, setContextUserTouched] = useState(false);
  const prevJobIdRef = useRef<string | undefined>(undefined);

  // Reset state when experiment changes
  useEffect(() => {
    // Clear all state when switching to a new experiment
    // Note: Don't clear experimentStream here - it's managed by the experimentResult effect
    // to avoid race conditions where we clear it before new data arrives
    setSelectedAgentRunId(undefined);
    setSelectedAgentRun(null);
    setIsLoadingAgentRun(false);
    setHasInitializedFromUrl(false);
    // Also reset the UI state
    setIsIdeaOpen(false);
    setIsContextOpen(false);
    setIdeaUserTouched(false);
    setContextUserTouched(false);
    prevJobIdRef.current = undefined;
  }, [experimentConfigId]);

  // Auto-open on stream start; auto-close on finish unless user interacted
  useEffect(() => {
    const prevJobId = prevJobIdRef.current;
    const started = Boolean(jobId && jobId !== prevJobId);
    const finished = Boolean(!jobId && prevJobId);

    if (started) {
      // Reset user interaction when a new job starts
      setIdeaUserTouched(false);
      setContextUserTouched(false);
      setIsIdeaOpen(true);
      setIsContextOpen(true);
    } else if (finished) {
      if (!ideaUserTouched) setIsIdeaOpen(false);
      if (!contextUserTouched) setIsContextOpen(false);
    }

    prevJobIdRef.current = jobId;
  }, [jobId, ideaUserTouched, contextUserTouched]);

  const ids = contextOutput ? Object.keys(contextOutput) : [];
  const hasContext = ids.length > 0;
  const MANY_CONTEXT_THRESHOLD = 6;

  const [activeContextId, setActiveContextId] = useState<string | undefined>(
    hasContext ? ids[0] : undefined
  );

  useEffect(() => {
    // Reset active tab when the set of ids changes
    if (!activeContextId || !ids.includes(activeContextId)) {
      setActiveContextId(hasContext ? ids[0] : undefined);
    }
  }, [ids.join('|')]);

  // Types are imported from AgentRunsBlock component

  // Agent run metadata grouped by counterfactual id (including base)
  const grouped: Block[] = React.useMemo(() => {
    const byCf: Record<
      string,
      { cfId: string; name: string; items: RunItem[] }
    > = {};
    if (!agentRuns) return [];
    const nameMap: Record<string, string> = {};
    // build name map from contextOutput (counterfactual tabs)
    for (const [cfId, v] of Object.entries(contextOutput ?? {})) {
      nameMap[cfId] = v?.name ?? cfId;
    }
    for (const [runId, m] of Object.entries(agentRuns)) {
      const cfId = m.counterfactual_id ?? 'unknown';
      const isBase = !(cfId in (contextOutput ?? {}));
      const name = isBase
        ? 'base'
        : nameMap[cfId] || m.counterfactual_name || cfId;
      if (!byCf[cfId]) byCf[cfId] = { cfId, name, items: [] };
      const gradeVal = typeof m.grade === 'number' ? m.grade : null;
      byCf[cfId].items.push({
        id: runId,
        replica_idx: m.replica_idx,
        grade: gradeVal,
        state: m.state ?? 'in_progress',
        error_type: m.error_type,
        error_message: m.error_message,
      });
    }
    // compute mean score for sorting blocks (exclude null grades)
    const blocks: Block[] = Object.values(byCf).map((b) => {
      const mean = computeMeanScore(b.items);
      return { cfId: b.cfId, name: b.name, items: b.items, mean };
    });
    blocks.sort((a, b) => {
      const aNan = Number.isNaN(a.mean);
      const bNan = Number.isNaN(b.mean);
      if (aNan && bNan) return 0;
      if (aNan) return 1;
      if (bNan) return -1;
      return b.mean - a.mean;
    });
    // sort items within block by descending grade, N/A at bottom
    for (const b of blocks) {
      b.items = sortRunsByGrade(b.items);
    }
    return blocks;
  }, [agentRuns, contextOutput]);

  const [openBlocks, setOpenBlocks] = useState<Record<string, boolean>>({});
  const toggleBlock = (id: string) =>
    setOpenBlocks((s) => ({ ...s, [id]: !s[id] }));

  // Function to handle clicking on a replica row
  const handleReplicaClick = async (agentRunId: string) => {
    const isExperimentRunning = !!jobId;

    // Handle deselection
    if (selectedAgentRunId === agentRunId) {
      // Unsubscribe if experiment is running
      if (isExperimentRunning && jobId) {
        try {
          await fetch(
            `${BASE_URL}/rest/investigator/${workspaceId}/experiment/job/${jobId}/unsubscribe-agent-run`,
            {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ agent_run_id: agentRunId }),
              credentials: 'include',
            }
          );
        } catch (error) {
          console.error('Error unsubscribing from agent run:', error);
        }
      }
      setSelectedAgentRunId(undefined);
      setSelectedAgentRun(null);
      updateQueryParams(); // Clear agent_run_id from URL
      return;
    }

    // Unsubscribe from previous selection if experiment is running
    if (selectedAgentRunId && isExperimentRunning && jobId) {
      try {
        await fetch(
          `${BASE_URL}/rest/investigator/${workspaceId}/experiment/job/${jobId}/unsubscribe-agent-run`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ agent_run_id: selectedAgentRunId }),
            credentials: 'include',
          }
        );
      } catch (error) {
        console.error('Error unsubscribing from previous agent run:', error);
      }
    }

    // Set the selected agent run ID and update URL
    setSelectedAgentRunId(agentRunId);
    updateQueryParams(agentRunId);

    if (isExperimentRunning && jobId) {
      // Subscribe to the agent run - data will come through SSE
      setIsLoadingAgentRun(true);
      try {
        await fetch(
          `${BASE_URL}/rest/investigator/${workspaceId}/experiment/job/${jobId}/subscribe-agent-run`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ agent_run_id: agentRunId }),
            credentials: 'include',
          }
        );
        // Data will arrive through the SSE connection; loading state will be
        // cleared when selectedAgentRun is populated or on error.
      } catch (error) {
        console.error('Error subscribing to agent run:', error);
        setIsLoadingAgentRun(false);
      }
    } else {
      // Experiment complete - fetch from database
      setIsLoadingAgentRun(true);
      try {
        const response = await fetch(
          `${BASE_URL}/rest/investigator/${workspaceId}/experiment/${experimentConfigId}/agent-run/${agentRunId}`,
          {
            credentials: 'include',
          }
        );
        if (response.ok) {
          const agentRun = await response.json();
          setSelectedAgentRun(agentRun);
        } else {
          console.error('Failed to fetch agent run:', response.statusText);
          setSelectedAgentRun(null);
        }
      } catch (error) {
        console.error('Error fetching agent run:', error);
        setSelectedAgentRun(null);
      } finally {
        setIsLoadingAgentRun(false);
      }
    }
  };

  // Function to close the agent run sidebar
  const handleCloseAgentRun = async () => {
    // Unsubscribe if experiment is running
    if (selectedAgentRunId && jobId) {
      try {
        await fetch(
          `${BASE_URL}/rest/investigator/${workspaceId}/experiment/job/${jobId}/unsubscribe-agent-run`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ agent_run_id: selectedAgentRunId }),
            credentials: 'include',
          }
        );
      } catch (error) {
        console.error('Error unsubscribing from agent run:', error);
      }
    }
    setSelectedAgentRunId(undefined);
    setSelectedAgentRun(null);
    updateQueryParams(); // Clear agent_run_id from URL
  };
  return (
    <div className="flex h-screen">
      <div className="flex-1 space-y-4 p-3 custom-scrollbar overflow-y-auto">
        {/* Docent Collection Link */}
        {docentCollectionId && (
          <div className="flex items-center justify-between p-3 bg-secondary rounded-md">
            <div className="text-sm text-muted-foreground">
              View full agent runs in Docent
            </div>
            <Link href={`/dashboard/${docentCollectionId}`} target="_blank">
              <Button variant="outline" size="sm">
                <ExternalLink className="h-4 w-4 mr-2" />
                Open in Docent
              </Button>
            </Link>
          </div>
        )}

        {isExperimentErrored && experimentErrorMessage && (
          <div className="p-3 bg-red-bg border border-red-border rounded-md">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-red-text">
                Experiment Failed
              </span>
            </div>
            <p className="text-sm text-red-text mt-1">
              {experimentErrorMessage}
            </p>
          </div>
        )}

        {isExperimentCancelled && (
          <div className="p-3 bg-orange-bg border border-orange-border rounded-md">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-orange-text">
                Experiment Cancelled
              </span>
            </div>
          </div>
        )}

        <div className="space-y-2">
          <button
            type="button"
            className="flex items-center gap-2 text-sm font-medium text-primary"
            onClick={() => {
              setIsIdeaOpen((v) => !v);
              setIdeaUserTouched(true);
            }}
          >
            {isIdeaOpen ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
            Counterfactual ideas
          </button>
          {isIdeaOpen && <CodeBlock value={ideaOutput} />}
        </div>

        <div className="space-y-2">
          <button
            type="button"
            className="flex items-center gap-2 text-sm font-medium text-primary"
            onClick={() => {
              setIsContextOpen((v) => !v);
              setContextUserTouched(true);
            }}
          >
            {isContextOpen ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
            Alternative contexts
          </button>
          {isContextOpen &&
            (hasContext ? (
              ids.length > MANY_CONTEXT_THRESHOLD ? (
                <div className="space-y-2">
                  <div className="max-w-full">
                    <Select
                      value={activeContextId}
                      onValueChange={(v) => setActiveContextId(v)}
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder="Select counterfactual" />
                      </SelectTrigger>
                      <SelectContent>
                        {ids.map((id) => {
                          const name = contextOutput?.[id]?.name;
                          return (
                            <SelectItem key={id} value={id}>
                              {name ?? id}
                            </SelectItem>
                          );
                        })}
                      </SelectContent>
                    </Select>
                  </div>
                  {activeContextId && (
                    <CodeBlock
                      value={contextOutput?.[activeContextId]?.value}
                    />
                  )}
                </div>
              ) : (
                <Tabs
                  value={activeContextId}
                  onValueChange={(v) => setActiveContextId(v)}
                >
                  <div className="max-w-full overflow-x-auto custom-scrollbar">
                    <TabsList className="min-w-max">
                      {ids.map((id) => {
                        const name = contextOutput?.[id]?.name;
                        return (
                          <TabsTrigger key={id} value={id}>
                            {name ?? id}
                          </TabsTrigger>
                        );
                      })}
                    </TabsList>
                  </div>
                  {ids.map((id) => (
                    <TabsContent key={id} value={id}>
                      <CodeBlock value={contextOutput?.[id]?.value} />
                    </TabsContent>
                  ))}
                </Tabs>
              )
            ) : (
              <div className="text-sm text-muted-foreground">
                No counterfactual contexts yet.
              </div>
            ))}
        </div>

        {/* Agent Run Metadata */}
        <div className="space-y-2">
          <div className="text-sm font-medium text-primary">Agent runs</div>
          {grouped.length > 0 ? (
            <div className="space-y-2">
              {grouped.map((block: Block) => (
                <AgentRunsBlock
                  key={block.cfId}
                  block={block}
                  selectedAgentRunId={selectedAgentRunId}
                  onReplicaClick={handleReplicaClick}
                  defaultOpen={openBlocks[block.cfId] ?? false}
                  onToggle={toggleBlock}
                />
              ))}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">
              No agent runs yet.
            </div>
          )}
        </div>
      </div>

      {/* Agent Run Viewer Sidebar */}
      {selectedAgentRunId && (
        <div className="w-1/2 max-w-3xl h-full border-l border-border flex flex-col bg-background">
          <div className="flex-1 overflow-hidden">
            {isLoadingAgentRun ? (
              <div className="flex items-center justify-center h-full">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : selectedAgentRunId ? (
              <InvestigatorAgentRunViewer
                agentRun={selectedAgentRun}
                onCloneToContext={(data) => {
                  if (!onCloneAgentRunToContext || !selectedAgentRun) return;

                  // TODO(neil): this is a bit hacky; I think it can be simplified later.

                  // Extract tools from the policy config based on the agent run
                  let tools: ToolInfo[] | undefined;
                  if (experimentResult && selectedAgentRun.metadata) {
                    // Type the metadata structure properly
                    const metadata = selectedAgentRun.metadata as {
                      counterfactual_id?: string;
                      [key: string]: unknown;
                    };
                    const counterfactualId = metadata?.counterfactual_id;

                    // Check if this is a base run (counterfactual_id matches base_context.id)
                    let rawTools: unknown[] | undefined;

                    if (
                      counterfactualId ===
                      experimentResult.config?.base_context?.id
                    ) {
                      // Get tools from base_policy_config
                      rawTools = experimentResult.base_policy_config?.tools;
                    } else if (
                      counterfactualId &&
                      experimentResult.counterfactual_policy_configs
                    ) {
                      // Get tools from the specific counterfactual policy config
                      const policyConfig =
                        experimentResult.counterfactual_policy_configs[
                          counterfactualId
                        ];
                      rawTools = policyConfig?.tools;
                    }

                    // Ensure tools have the correct type field for BaseContextEditor
                    if (rawTools && Array.isArray(rawTools)) {
                      tools = rawTools as ToolInfo[];
                    }
                  }

                  // Pass the data with tools to the parent
                  onCloneAgentRunToContext({
                    ...data,
                    tools,
                  });
                }}
                onClose={handleCloseAgentRun}
              />
            ) : (
              <div className="flex items-center justify-center h-full text-muted-foreground">
                Failed to load agent run
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
