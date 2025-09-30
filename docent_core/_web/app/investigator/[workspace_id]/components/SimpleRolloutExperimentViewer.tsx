'use client';

import React, { useState, useEffect, useRef } from 'react';
import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { ExternalLink, Loader2 } from 'lucide-react';
import {
  AgentRunsBlock,
  type RunItem,
  type Block,
  sortRunsByGrade,
  computeMeanScore,
} from '@/components/AgentRunsBlock';
import { useParams, useSearchParams, useRouter } from 'next/navigation';
import { BASE_URL } from '@/app/constants';
import type { ExperimentStreamData } from '@/types/experiment';
import {
  useGetExperimentResultQuery,
  useGetActiveExperimentJobsQuery,
} from '@/app/api/investigatorApi';
import InvestigatorAgentRunViewer from '@/app/investigator/[workspace_id]/components/InvestigatorAgentRunViewer';
import type { ToolInfo } from '@/app/investigator/[workspace_id]/components/BaseContextEditor';
import { AgentRun } from '@/app/types/transcriptTypes';

interface SimpleRolloutExperimentViewerProps {
  experimentConfigId: string;
  onCloneAgentRunToContext?: (data: {
    messages: Array<{ role: string; content: string }>;
    tools?: ToolInfo[];
  }) => void;
}

export default function SimpleRolloutExperimentViewer({
  experimentConfigId,
  onCloneAgentRunToContext,
}: SimpleRolloutExperimentViewerProps) {
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

  // Reset state when experiment changes
  useEffect(() => {
    // Clear all state when switching to a new experiment
    // Note: Don't clear experimentStream here - it's managed by the experimentResult effect
    // to avoid race conditions where we clear it before new data arrives
    setSelectedAgentRunId(undefined);
    setSelectedAgentRun(null);
    setIsLoadingAgentRun(false);
    setHasInitializedFromUrl(false);
  }, [experimentConfigId]);

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
      setExperimentStream({
        activeJobId: activeJobData?.job_id || undefined,
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

  // Types are imported from AgentRunsBlock component

  // Agent run metadata grouped by backend
  const grouped: Block[] = React.useMemo(() => {
    if (!agentRuns) return [];

    const runsByBackend: Record<string, RunItem[]> = {};

    for (const [runId, m] of Object.entries(agentRuns)) {
      const backendName = m.backend_name || 'Unknown Backend';

      if (!runsByBackend[backendName]) {
        runsByBackend[backendName] = [];
      }

      const gradeVal =
        typeof m.grade?.grade === 'number' ? m.grade.grade : null;
      runsByBackend[backendName].push({
        id: runId,
        replica_idx: m.replica_idx,
        grade: gradeVal,
        state: m.state ?? 'in_progress',
        error_type: m.error_type,
        error_message: m.error_message,
      });
    }

    const blocks: Block[] = [];

    const sortedBackendNames = Object.keys(runsByBackend).sort();

    for (const backendName of sortedBackendNames) {
      const items = runsByBackend[backendName];

      const mean = computeMeanScore(items);

      blocks.push({
        cfId: backendName,
        name: backendName,
        items: sortRunsByGrade(items),
        mean,
      });
    }

    return blocks;
  }, [agentRuns]);

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

                  // Extract tools from the policy config for simple rollout
                  let tools: ToolInfo[] | undefined;
                  if (
                    experimentResult &&
                    experimentResult.base_policy_config?.tools
                  ) {
                    const rawTools = experimentResult.base_policy_config.tools;
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
