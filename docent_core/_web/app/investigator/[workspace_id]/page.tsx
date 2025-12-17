'use client';

import { useParams, useSearchParams, useRouter } from 'next/navigation';
import React, { useState, useEffect } from 'react';
import { ArrowLeft, FlaskConicalIcon, Loader2 } from 'lucide-react';
import Link from 'next/link';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Separator } from '@/components/ui/separator';
import { ModeToggle } from '@/components/ui/theme-toggle';
import { UserProfile } from '@/app/components/auth/UserProfile';
import {
  useGetWorkspaceQuery,
  useGetBaseContextsQuery,
  useGetJudgeConfigsQuery,
  useGetExperimentIdeasQuery,
  useGetBackendsQuery,
  useCreateOpenAICompatibleBackendMutation,
  useCreateAnthropicCompatibleBackendMutation,
  useDeleteBackendMutation,
  useCreateBaseContextMutation,
  useDeleteBaseContextMutation,
  useCreateJudgeConfigMutation,
  useDeleteJudgeConfigMutation,
  useCreateExperimentIdeaMutation,
  useDeleteExperimentIdeaMutation,
  useGetExperimentConfigsQuery,
  useCreateExperimentConfigMutation,
  useDeleteExperimentConfigMutation,
  useStartExperimentMutation,
  useCancelExperimentMutation,
  useGetActiveExperimentJobsQuery,
  type Backend,
} from '@/app/api/investigatorApi';
import { toast } from 'sonner';

// Import layout components
import LeftSidebar from './components/LeftSidebar';
import TopPanel from './components/TopPanel';
import MainPanel from './components/MainPanel';
import BaseContextEditor, {
  type ToolInfo,
} from './components/BaseContextEditor';
import JudgeEditor from './components/JudgeEditor';
import CounterfactualIdeaEditor from './components/CounterfactualIdeaEditor';
import BackendEditor from './components/BackendEditor';
import CounterfactualExperimentViewer from './components/CounterfactualExperimentViewer';
import SimpleRolloutExperimentViewer from './components/SimpleRolloutExperimentViewer';
import ExperimentStreamManager from './components/ExperimentStreamManager';
import ExperimentAutoReconnect from './components/ExperimentAutoReconnect';
import ExperimentResultLoader from './components/ExperimentResultLoader';
import { getNextForkName } from '@/lib/investigatorUtils';
import AccessDeniedPage from '../components/AccessDeniedPage';
import { handleInvestigatorError, is403Error } from '../utils/errorHandling';

export default function WorkspacePage() {
  const params = useParams();
  const workspaceId = params.workspace_id as string;
  const searchParams = useSearchParams();
  const router = useRouter();

  // Get experiment ID from URL
  const experimentId = searchParams.get('experiment');
  const isCreatingNew = searchParams.get('new') === 'true';
  const [editingComponent, setEditingComponent] = useState<
    | 'base-interaction'
    | 'view-base-interaction'
    | 'judge'
    | 'view-judge'
    | 'backend'
    | 'view-backend'
    | 'idea'
    | 'view-idea'
    | null
  >(null);
  const [selectedBaseContextId, setSelectedBaseContextId] = useState<
    string | undefined
  >();
  const [selectedJudgeConfigId, setSelectedJudgeConfigId] = useState<
    string | undefined
  >();
  const [selectedCounterfactualIdeaId, setSelectedCounterfactualIdeaId] =
    useState<string | undefined>();
  const [selectedBackendId, setSelectedBackendId] = useState<
    string | undefined
  >();
  const [selectedBackendIds, setSelectedBackendIds] = useState<string[]>([]);
  const [baseContextToView, setBaseContextToView] = useState<{
    name: string;
    prompt: Array<{
      role: 'user' | 'assistant' | 'system' | 'tool';
      content: string;
      tool_calls?: any[];
      tool_call_id?: string;
    }>;
    tools?: any[];
  } | null>(null);
  const [baseContextToFork, setBaseContextToFork] = useState<{
    name: string;
    prompt: Array<{
      role: 'user' | 'assistant' | 'system' | 'tool';
      content: string;
      tool_calls?: any[];
      tool_call_id?: string;
    }>;
    tools?: any[];
  } | null>(null);
  const [judgeConfigToView, setJudgeConfigToView] = useState<{
    name: string;
    rubric: string;
  } | null>(null);
  const [judgeConfigToFork, setJudgeConfigToFork] = useState<{
    name: string;
    rubric: string;
  } | null>(null);
  const [backendToView, setBackendToView] = useState<{
    backend_type: 'openai_compatible' | 'anthropic_compatible';
    name: string;
    provider: string;
    model: string;
    max_tokens?: number;
    thinking_type?: 'enabled' | 'disabled';
    thinking_budget_tokens?: number;
    api_key?: string;
    base_url?: string;
  } | null>(null);
  const [backendToFork, setBackendToFork] = useState<{
    backend_type: 'openai_compatible' | 'anthropic_compatible';
    name: string;
    provider: string;
    model: string;
    max_tokens?: number;
    thinking_type?: 'enabled' | 'disabled';
    thinking_budget_tokens?: number;
    api_key?: string;
    base_url?: string;
  } | null>(null);
  const [ideaToView, setIdeaToView] = useState<{
    name: string;
    idea: string;
  } | null>(null);
  const [ideaToFork, setIdeaToFork] = useState<{
    name: string;
    idea: string;
  } | null>(null);

  // State for tracking selected values for new experiments
  const [experimentType, setExperimentType] = useState<
    'counterfactual' | 'simple_rollout'
  >('counterfactual');
  const [numCounterfactuals, setNumCounterfactuals] = useState(1);
  const [numReplicas, setNumReplicas] = useState(16);

  // State for delete confirmation dialog
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);

  // Fetch workspace details
  const {
    data: workspace,
    isLoading: isLoadingWorkspace,
    error: workspaceError,
  } = useGetWorkspaceQuery(workspaceId);

  // Fetch data - skip if we have a workspace error to avoid multiple 403 errors
  const { data: baseContexts, error: baseContextsError } =
    useGetBaseContextsQuery(workspaceId, {
      skip: !!workspaceError,
    });
  const { data: judgeConfigs, error: judgeConfigsError } =
    useGetJudgeConfigsQuery(workspaceId, {
      skip: !!workspaceError,
    });
  const { data: experimentIdeas, error: experimentIdeasError } =
    useGetExperimentIdeasQuery(workspaceId, {
      skip: !!workspaceError,
    });

  // Use unified backends endpoint (returns both types with type discriminator)
  const { data: backends, error: backendsError } = useGetBackendsQuery(
    workspaceId,
    {
      skip: !!workspaceError,
    }
  );

  const { data: experimentConfigs, error: experimentConfigsError } =
    useGetExperimentConfigsQuery(workspaceId, {
      skip: !!workspaceError,
    });

  // Create mutations
  const [createBaseContext, { isLoading: isCreatingBaseContext }] =
    useCreateBaseContextMutation();
  const [createJudgeConfig, { isLoading: isCreatingJudgeConfig }] =
    useCreateJudgeConfigMutation();
  const [createExperimentIdea, { isLoading: isCreatingExperimentIdea }] =
    useCreateExperimentIdeaMutation();
  const [createOpenAIBackend] = useCreateOpenAICompatibleBackendMutation();
  const [createAnthropicBackend] =
    useCreateAnthropicCompatibleBackendMutation();
  const [deleteBackend] = useDeleteBackendMutation();
  const [createExperimentConfig, { isLoading: isCreatingExperimentConfig }] =
    useCreateExperimentConfigMutation();
  const [deleteExperimentConfig, { isLoading: isDeletingExperimentConfig }] =
    useDeleteExperimentConfigMutation();
  const [startExperiment] = useStartExperimentMutation();
  const [cancelExperiment, { isLoading: isCancellingExperiment }] =
    useCancelExperimentMutation();

  // Sort experiments in reverse chronological order (most recent first)
  const sortedExperimentConfigs = React.useMemo(() => {
    if (!experimentConfigs) return [];
    return [...experimentConfigs].sort((a, b) => {
      const dateA = new Date(a.created_at).getTime();
      const dateB = new Date(b.created_at).getTime();
      return dateB - dateA; // Descending order (most recent first)
    });
  }, [experimentConfigs]);

  // Get selected experiment from configs based on URL param
  const selectedExperiment =
    experimentConfigs?.find((exp) => exp.id === experimentId) || null;

  // Check active jobs for all experiments in the workspace
  const { data: activeJobs } = useGetActiveExperimentJobsQuery(workspaceId, {
    skip: !selectedExperiment,
  });
  const activeJobData = selectedExperiment
    ? activeJobs?.[selectedExperiment.id]
    : undefined;
  const isExperimentRunning = activeJobData?.job_id != null;

  // Delete mutations
  const [deleteBaseContext, { isLoading: isDeletingBaseContext }] =
    useDeleteBaseContextMutation();
  const [deleteJudgeConfig, { isLoading: isDeletingJudgeConfig }] =
    useDeleteJudgeConfigMutation();
  const [deleteExperimentIdea, { isLoading: isDeletingExperimentIdea }] =
    useDeleteExperimentIdeaMutation();

  // Sync selected IDs when experiment changes
  useEffect(() => {
    if (selectedExperiment) {
      setSelectedBaseContextId(selectedExperiment.base_context.id);
      setSelectedJudgeConfigId(
        selectedExperiment.judge_config?.id || undefined
      );

      if (selectedExperiment.type === 'counterfactual') {
        setSelectedBackendId(selectedExperiment.backend.id);
        setSelectedCounterfactualIdeaId(selectedExperiment.idea.id);
        setNumCounterfactuals(selectedExperiment.num_counterfactuals);
      } else {
        setSelectedCounterfactualIdeaId(undefined);
        setSelectedBackendIds(
          selectedExperiment.backends?.map((b: Backend) => b.id) || []
        );
      }

      setNumReplicas(selectedExperiment.num_replicas);
    } else if (!isCreatingNew) {
      // Clear selections when no experiment is selected (unless creating new)
      setSelectedBaseContextId(undefined);
      setSelectedJudgeConfigId(undefined);
      setSelectedBackendId(undefined);
      setSelectedBackendIds([]);
      setSelectedCounterfactualIdeaId(undefined);
    }
  }, [selectedExperiment, isCreatingNew]);

  if (isLoadingWorkspace) {
    return (
      <div className="flex items-center justify-center h-screen">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // Check for 403 error
  if (workspaceError && is403Error(workspaceError)) {
    return (
      <AccessDeniedPage
        title="Workspace Access Denied"
        message="You are not authorized to access this investigator workspace."
        backButtonText="Back to Workspaces"
        backButtonHref="/investigator"
      />
    );
  }

  if (!workspace) {
    return (
      <div className="flex flex-col items-center justify-center h-screen">
        <FlaskConicalIcon className="h-12 w-12 text-muted-foreground mb-4" />
        <h2 className="text-lg font-semibold">Workspace Not Found</h2>
        <p className="text-sm text-muted-foreground mb-4">
          The workspace you&apos;re looking for doesn&apos;t exist.
        </p>
        <Link href="/investigator">
          <Button variant="outline">
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to Workspaces
          </Button>
        </Link>
      </div>
    );
  }

  const handleExperimentSelect = (id: string) => {
    const experiment = sortedExperimentConfigs?.find((exp) => exp.id === id);
    if (experiment) {
      // Update URL to select experiment
      router.push(`/investigator/${workspaceId}?experiment=${id}`);
      setEditingComponent(null);

      // Set the experiment type
      setExperimentType(experiment.type);

      // Reset the selected IDs to the experiment's values
      setSelectedBaseContextId(experiment.base_context?.id);

      // Handle type-specific fields
      if (experiment.type === 'counterfactual') {
        setSelectedBackendId(experiment.backend?.id);
        setSelectedJudgeConfigId(experiment.judge_config?.id);
        setSelectedCounterfactualIdeaId(experiment.idea?.id);
        setNumCounterfactuals(experiment.num_counterfactuals);
      } else if (experiment.type === 'simple_rollout') {
        setSelectedBackendIds(
          experiment.backends?.map((b: Backend) => b.id) || []
        );
        setSelectedJudgeConfigId(experiment.judge_config?.id || undefined);
        setSelectedCounterfactualIdeaId(undefined);
        setNumCounterfactuals(1);
      }
      setNumReplicas(experiment.num_replicas);
    }
  };

  const handleNewExperiment = () => {
    // Update URL to create new experiment
    router.push(`/investigator/${workspaceId}?new=true`);
    setEditingComponent(null);

    // Clear all selected IDs for a fresh start
    setSelectedBaseContextId(undefined);
    setSelectedJudgeConfigId(undefined);
    setSelectedBackendId(undefined);
    setSelectedCounterfactualIdeaId(undefined);
    setNumCounterfactuals(1);
    setNumReplicas(16);
  };

  const handleForkExperiment = () => {
    if (!selectedExperiment) return;

    // Set up for creating new experiment with current experiment's values
    router.push(`/investigator/${workspaceId}?new=true`);
    setEditingComponent(null);

    // Set the experiment type
    setExperimentType(selectedExperiment.type);

    // Keep the selected IDs from the current experiment
    setSelectedBaseContextId(selectedExperiment.base_context?.id);
    setNumReplicas(selectedExperiment.num_replicas);

    // Handle type-specific fields
    if (selectedExperiment.type === 'counterfactual') {
      setSelectedBackendId(selectedExperiment.backend?.id);
      setSelectedJudgeConfigId(selectedExperiment.judge_config?.id);
      setSelectedCounterfactualIdeaId(selectedExperiment.idea?.id);
      setNumCounterfactuals(selectedExperiment.num_counterfactuals);
    } else if (selectedExperiment.type === 'simple_rollout') {
      setSelectedBackendIds(
        selectedExperiment.backends?.map((b: Backend) => b.id) || []
      );
      // Judge is optional for simple rollout
      setSelectedJudgeConfigId(
        selectedExperiment.judge_config?.id || undefined
      );
      // Clear counterfactual-specific fields
      setSelectedCounterfactualIdeaId(undefined);
      setNumCounterfactuals(1);
    }
  };

  const handleCancelExperiment = async () => {
    if (!selectedExperiment) return;

    try {
      await cancelExperiment({
        workspaceId,
        experimentConfigId: selectedExperiment.id,
      }).unwrap();

      toast.success('Experiment cancelled successfully');

      // The experiment viewer component will handle reloading the data
    } catch (error) {
      console.error('Failed to cancel experiment:', error);
      handleInvestigatorError(error, 'Failed to cancel experiment');
    }
  };

  const handleDeleteExperiment = async () => {
    if (!selectedExperiment) return;

    try {
      await deleteExperimentConfig(selectedExperiment.id).unwrap();

      // Clear URL selection
      router.push(`/investigator/${workspaceId}`);
      setEditingComponent(null);
      setShowDeleteDialog(false);

      // Show success toast
      toast.success('Experiment deleted successfully');
    } catch (error) {
      console.error('Failed to delete experiment:', error);
      handleInvestigatorError(error, 'Failed to delete experiment');
      setShowDeleteDialog(false);
    }
  };

  const handleLaunchExperiment = async () => {
    try {
      let experimentConfigId: string | null = null;

      if (isCreatingNew) {
        let created: any;

        // Validate based on experiment type
        if (experimentType === 'counterfactual') {
          if (
            !selectedBaseContextId ||
            !selectedJudgeConfigId ||
            !selectedBackendId ||
            !selectedCounterfactualIdeaId
          ) {
            toast.error('Please select all required fields before launching');
            return;
          }

          // Get backend type from the type discriminator
          const selectedBackend = backends?.find(
            (b) => b.id === selectedBackendId
          );
          const backendType = selectedBackend?.type || 'openai_compatible';

          created = await createExperimentConfig({
            workspaceId,
            type: 'counterfactual',
            base_context_id: selectedBaseContextId,
            judge_config_id: selectedJudgeConfigId,
            backend_type: backendType,
            openai_compatible_backend_id:
              backendType === 'openai_compatible'
                ? selectedBackendId
                : undefined,
            anthropic_compatible_backend_id:
              backendType === 'anthropic_compatible'
                ? selectedBackendId
                : undefined,
            idea_id: selectedCounterfactualIdeaId,
            num_counterfactuals: numCounterfactuals,
            num_replicas: numReplicas,
            max_turns: 1,
          }).unwrap();
        } else if (experimentType === 'simple_rollout') {
          if (
            !selectedBaseContextId ||
            !selectedBackendIds ||
            selectedBackendIds.length === 0
          ) {
            toast.error(
              'Please select base context and at least one backend before launching'
            );
            return;
          }

          // Separate backend IDs by type using the type discriminator
          const openaiBackendIds = selectedBackendIds.filter(
            (id) =>
              backends?.find((b) => b.id === id)?.type === 'openai_compatible'
          );
          const anthropicBackendIds = selectedBackendIds.filter(
            (id) =>
              backends?.find((b) => b.id === id)?.type ===
              'anthropic_compatible'
          );

          created = await createExperimentConfig({
            workspaceId,
            type: 'simple_rollout',
            base_context_id: selectedBaseContextId,
            judge_config_id: selectedJudgeConfigId || undefined,
            openai_compatible_backend_ids: openaiBackendIds,
            anthropic_compatible_backend_ids: anthropicBackendIds,
            num_replicas: numReplicas,
            max_turns: 1,
          }).unwrap();
        }

        experimentConfigId = created.id;

        // After a short delay, select the new experiment from refreshed list
        setTimeout(() => {
          handleExperimentSelect(created.id);
        }, 500);
      } else if (selectedExperiment) {
        experimentConfigId = selectedExperiment.id;
      }

      if (!experimentConfigId) {
        throw new Error('No experiment config selected or created');
      }

      const { job_id } = await startExperiment({
        workspaceId,
        experimentConfigId,
      }).unwrap();

      // The CounterfactualExperimentViewer component will handle SSE connection
      // when it detects an active job
    } catch (error) {
      console.error('Failed to launch experiment:', error);
      handleInvestigatorError(error, 'Failed to launch experiment');
    }
  };

  const handleNewBaseContext = () => {
    // If a base context is selected and exists, fork it
    if (selectedBaseContextId && baseContexts) {
      const selectedBI = baseContexts.find(
        (bi) => bi.id === selectedBaseContextId
      );
      if (selectedBI) {
        setBaseContextToFork({
          name: getNextForkName(selectedBI.name),
          prompt: selectedBI.prompt.map((m) => ({
            role: m.role as 'user' | 'assistant' | 'system' | 'tool',
            content: m.content,
            ...(m.tool_calls && { tool_calls: m.tool_calls }),
            ...(m.tool_call_id && { tool_call_id: m.tool_call_id }),
          })),
          tools: selectedBI.tools,
        });
        setEditingComponent('base-interaction');
      }
    } else {
      // Otherwise create a new one
      setBaseContextToFork(null);
      setEditingComponent('base-interaction');
    }
    // Don't change isCreatingNew - keep it true if we're creating a new experiment
  };

  const handleViewBaseContext = () => {
    // Get the ID from either selectedBaseContextId or from the selected experiment
    const baseContextIdToView =
      selectedBaseContextId || selectedExperiment?.base_context?.id;

    if (baseContextIdToView && baseContexts) {
      const selectedBI = baseContexts.find(
        (bi) => bi.id === baseContextIdToView
      );
      if (selectedBI) {
        setBaseContextToView({
          name: selectedBI.name,
          prompt: selectedBI.prompt.map((m) => ({
            role: m.role as 'user' | 'assistant' | 'system' | 'tool',
            content: m.content,
            ...(m.tool_calls && { tool_calls: m.tool_calls }),
            ...(m.tool_call_id && { tool_call_id: m.tool_call_id }),
          })),
          tools: selectedBI.tools,
        });
        setEditingComponent('view-base-interaction');
      }
    }
  };

  const handleForkBaseContext = (data: {
    name: string;
    prompt: Array<{
      role: 'user' | 'assistant' | 'system' | 'tool';
      content: string;
      tool_calls?: any[];
      tool_call_id?: string;
    }>;
    tools?: any[];
  }) => {
    setBaseContextToFork(data);
    setEditingComponent('base-interaction');
  };

  const handleDeleteBaseContext = async () => {
    if (!selectedBaseContextId) return;

    try {
      await deleteBaseContext(selectedBaseContextId).unwrap();

      // Clear selection and close viewer
      setSelectedBaseContextId(undefined);
      setBaseContextToView(null);
      setEditingComponent(null);

      // Show success toast
      toast.success('Base context deleted successfully');
    } catch (error) {
      // Show error toast
      toast.error(
        `Failed to delete base context: ${(error as any)?.data?.detail || 'Unknown error'}`
      );
    }
  };

  const handleNewJudgeConfig = () => {
    if (selectedJudgeConfigId && judgeConfigs) {
      const selectedJC = judgeConfigs.find(
        (jc) => jc.id === selectedJudgeConfigId
      );
      if (selectedJC) {
        setJudgeConfigToFork({
          name: getNextForkName(selectedJC.name ?? 'Unnamed Judge'),
          rubric: selectedJC.rubric,
        });
        setEditingComponent('judge');
      }
    } else {
      setJudgeConfigToFork(null);
      setEditingComponent('judge');
    }
  };

  const handleViewJudgeConfig = () => {
    // Get the ID from either selectedJudgeConfigId or from the selected experiment
    const judgeConfigIdToView =
      selectedJudgeConfigId || selectedExperiment?.judge_config?.id;

    if (judgeConfigIdToView && judgeConfigs) {
      const selectedJC = judgeConfigs.find(
        (jc) => jc.id === judgeConfigIdToView
      );
      if (selectedJC) {
        setJudgeConfigToView({
          name: selectedJC.name ?? 'Unnamed Judge',
          rubric: selectedJC.rubric,
        });
        setEditingComponent('view-judge');
      }
    }
  };

  const handleForkJudgeConfig = (data: { name: string; rubric: string }) => {
    setJudgeConfigToFork(data);
    setEditingComponent('judge');
  };

  const handleDeleteJudgeConfig = async () => {
    if (!selectedJudgeConfigId) return;

    try {
      await deleteJudgeConfig(selectedJudgeConfigId).unwrap();
      setSelectedJudgeConfigId(undefined);
      setJudgeConfigToView(null);
      setEditingComponent(null);
      toast.success('Judge configuration deleted successfully');
    } catch (error) {
      toast.error(
        `Failed to delete judge configuration: ${(error as any)?.data?.detail || 'Unknown error'}`
      );
    }
  };

  const handleNewBackendConfig = () => {
    if (selectedBackendId && backends) {
      const selectedBackend = backends.find((b) => b.id === selectedBackendId);
      if (selectedBackend) {
        // Use the type discriminator from the API response
        if (selectedBackend.type === 'anthropic_compatible') {
          setBackendToFork({
            backend_type: 'anthropic_compatible',
            name: getNextForkName(selectedBackend.name),
            provider: selectedBackend.provider,
            model: selectedBackend.model,
            max_tokens: selectedBackend.max_tokens,
            thinking_type: selectedBackend.thinking_type ?? undefined,
            thinking_budget_tokens:
              selectedBackend.thinking_budget_tokens ?? undefined,
            api_key: selectedBackend.api_key ?? undefined,
            base_url: selectedBackend.base_url ?? undefined,
          });
        } else {
          setBackendToFork({
            backend_type: 'openai_compatible',
            name: getNextForkName(selectedBackend.name),
            provider: selectedBackend.provider,
            model: selectedBackend.model,
            api_key: selectedBackend.api_key ?? undefined,
            base_url: selectedBackend.base_url ?? undefined,
          });
        }
        setEditingComponent('backend');
      }
    } else {
      setBackendToFork(null);
      setEditingComponent('backend');
    }
  };

  const handleViewBackendConfig = (backendId?: string) => {
    // Get the ID from parameter, selectedBackendId, or from the selected experiment
    const backendIdToView =
      backendId ||
      selectedBackendId ||
      (selectedExperiment?.type === 'counterfactual'
        ? selectedExperiment?.backend?.id
        : undefined);

    if (backendIdToView && backends) {
      const selectedBackend = backends.find((b) => b.id === backendIdToView);
      if (selectedBackend) {
        // Use the type discriminator from the API response
        if (selectedBackend.type === 'anthropic_compatible') {
          setBackendToView({
            backend_type: 'anthropic_compatible',
            name: selectedBackend.name,
            provider: selectedBackend.provider,
            model: selectedBackend.model,
            max_tokens: selectedBackend.max_tokens,
            thinking_type: selectedBackend.thinking_type
              ? selectedBackend.thinking_type
              : undefined,
            thinking_budget_tokens: selectedBackend.thinking_budget_tokens
              ? selectedBackend.thinking_budget_tokens
              : undefined,
            api_key: selectedBackend.api_key || undefined,
            base_url: selectedBackend.base_url || undefined,
          });
        } else {
          setBackendToView({
            backend_type: 'openai_compatible',
            name: selectedBackend.name,
            provider: selectedBackend.provider,
            model: selectedBackend.model,
            api_key: selectedBackend.api_key ?? undefined,
            base_url: selectedBackend.base_url ?? undefined,
          });
        }
        setEditingComponent('view-backend');
      }
    }
  };

  const handleForkBackendConfig = (data: {
    backend_type: 'openai_compatible' | 'anthropic_compatible';
    name: string;
    provider: string;
    model: string;
    max_tokens?: number;
    thinking_type?: 'enabled' | 'disabled';
    thinking_budget_tokens?: number;
    api_key?: string;
    base_url?: string;
  }) => {
    setBackendToFork(data);
    setEditingComponent('backend');
  };

  const handleDeleteBackendConfig = async () => {
    if (!selectedBackendId) return;

    try {
      // Find the backend to get its type from the type discriminator
      const selectedBackend = backends?.find((b) => b.id === selectedBackendId);
      if (!selectedBackend) {
        throw new Error(`Backend not found: ${selectedBackendId}`);
      }

      // Use the type discriminator to delete the correct backend
      await deleteBackend({
        backendId: selectedBackendId,
        backendType: selectedBackend.type,
      }).unwrap();

      setSelectedBackendId(undefined);
      setBackendToView(null);
      setEditingComponent(null);
      toast.success('Backend configuration deleted successfully');
    } catch (error) {
      toast.error(
        `Failed to delete backend configuration: ${(error as any)?.data?.detail || 'Unknown error'}`
      );
    }
  };

  const handleNewCounterfactualIdea = () => {
    if (selectedCounterfactualIdeaId && experimentIdeas) {
      const selectedIdea = experimentIdeas.find(
        (ei) => ei.id === selectedCounterfactualIdeaId
      );
      if (selectedIdea) {
        setIdeaToFork({
          name: getNextForkName(selectedIdea.name),
          idea: selectedIdea.idea,
        });
        setEditingComponent('idea');
      }
    } else {
      setIdeaToFork(null);
      setEditingComponent('idea');
    }
  };

  const handleViewCounterfactualIdea = () => {
    // Get the ID from either selectedCounterfactualIdeaId or from the selected experiment
    const ideaIdToView =
      selectedCounterfactualIdeaId ||
      (selectedExperiment?.type === 'counterfactual'
        ? selectedExperiment.idea?.id
        : undefined);

    if (ideaIdToView && experimentIdeas) {
      const selectedIdea = experimentIdeas.find((ei) => ei.id === ideaIdToView);
      if (selectedIdea) {
        setIdeaToView({
          name: selectedIdea.name,
          idea: selectedIdea.idea,
        });
        setEditingComponent('view-idea');
      }
    }
  };

  const handleForkCounterfactualIdea = (data: {
    name: string;
    idea: string;
  }) => {
    setIdeaToFork(data);
    setEditingComponent('idea');
  };

  const handleDeleteCounterfactualIdea = async () => {
    if (!selectedCounterfactualIdeaId) return;

    try {
      await deleteExperimentIdea(selectedCounterfactualIdeaId).unwrap();
      setSelectedCounterfactualIdeaId(undefined);
      setIdeaToView(null);
      setEditingComponent(null);
      toast.success('Counterfactual idea deleted successfully');
    } catch (error) {
      toast.error(
        `Failed to delete counterfactual idea: ${(error as any)?.data?.detail || 'Unknown error'}`
      );
    }
  };

  const handleSaveBaseContext = async (data: any) => {
    try {
      const result = await createBaseContext({
        workspaceId,
        name: data.name,
        prompt: data.prompt,
        tools: data.tools,
      }).unwrap();

      // Only update selection if creating a new experiment
      if (isCreatingNew) {
        setSelectedBaseContextId(result.id);
      } else {
        // Show success toast for fork from read-only view
        toast.success(`Base context "${data.name}" created successfully`);
      }

      // Clear fork state
      setBaseContextToFork(null);

      // Close the editor
      setEditingComponent(null);
    } catch (error) {
      handleInvestigatorError(error, 'Failed to create base context');
    }
  };

  const handleSaveCounterfactualIdea = async (data: any) => {
    try {
      const result = await createExperimentIdea({
        workspaceId,
        name: data.name,
        idea: data.idea,
      }).unwrap();

      // Only update selection if creating a new experiment
      if (isCreatingNew) {
        setSelectedCounterfactualIdeaId(result.id);
      } else {
        // Show success toast for fork from read-only view
        toast.success(
          `Counterfactual idea "${data.name}" created successfully`
        );
      }

      // Clear fork state
      setIdeaToFork(null);

      // Close the editor
      setEditingComponent(null);
    } catch (error) {
      // Show error toast
      toast.error(
        `Failed to create counterfactual idea: ${(error as any)?.data?.detail || 'Unknown error'}`
      );
    }
  };

  const handleCancelEdit = () => {
    setEditingComponent(null);
    setBaseContextToView(null);
    setBaseContextToFork(null);
    setJudgeConfigToView(null);
    setJudgeConfigToFork(null);
    setBackendToView(null);
    setBackendToFork(null);
    setIdeaToView(null);
    setIdeaToFork(null);
    // The top panel stays visible if we're still creating a new experiment
  };

  const handleCloneAgentRunToContext = (data: {
    messages: Array<{ role: string; content: string }>;
    tools?: ToolInfo[];
    counterfactualName?: string;
  }) => {
    // Find the selected experiment's base context
    if (!selectedExperiment || !baseContexts) return;

    const baseContext = baseContexts.find(
      (ctx) => ctx.id === selectedExperiment.base_context.id
    );
    if (!baseContext) {
      toast.error('Could not find base context configuration');
      return;
    }

    // Create the new context name
    const experimentIdShort = selectedExperiment.id.split('-')[0]; // First 8 chars of UUID
    const newContextName = `${baseContext.name}-${experimentIdShort}-${data.counterfactualName || 'unknown'}`;

    // Take the first N messages where N is the base context prompt length
    const promptLength = baseContext.prompt.length;
    const clonedMessages = data.messages.slice(0, promptLength) as Array<{
      role: 'user' | 'assistant' | 'system';
      content: string;
    }>;

    // Set the base context to fork with the cloned data
    setBaseContextToFork({
      name: newContextName,
      prompt: clonedMessages,
      tools: data.tools, // Include the tools from the deterministic policy config
    });
    setEditingComponent('base-interaction');
  };

  const handleBaseContextChange = (value: string) => {
    setSelectedBaseContextId(value);
  };

  const handleJudgeConfigChange = (value: string | undefined) => {
    setSelectedJudgeConfigId(value);
  };

  const handleCounterfactualIdeaChange = (value: string) => {
    setSelectedCounterfactualIdeaId(value);
  };

  const handleBackendChange = (value: string) => {
    setSelectedBackendId(value);
  };

  const handleSaveBackend = async (data: any) => {
    try {
      let result;
      if (data.backend_type === 'anthropic_compatible') {
        result = await createAnthropicBackend({
          workspaceId,
          name: data.name,
          provider: data.provider,
          model: data.model,
          max_tokens: data.max_tokens,
          thinking_type: data.thinking_type,
          thinking_budget_tokens: data.thinking_budget_tokens,
          api_key: data.api_key,
          base_url: data.base_url,
        }).unwrap();
      } else {
        result = await createOpenAIBackend({
          workspaceId,
          name: data.name,
          provider: data.provider,
          model: data.model,
          api_key: data.api_key,
          base_url: data.base_url,
        }).unwrap();
      }

      // Only update selection if creating a new experiment
      if (isCreatingNew) {
        setSelectedBackendId(result.id);
      } else {
        // Show success toast for fork from read-only view
        toast.success(
          `Backend configuration "${data.name}" created successfully`
        );
      }

      // Clear fork state
      setBackendToFork(null);

      // Close the editor
      setEditingComponent(null);
    } catch (error) {
      // Show error toast
      toast.error(
        `Failed to create backend configuration: ${(error as any)?.data?.detail || 'Unknown error'}`
      );
    }
  };

  const handleSaveJudgeConfig = async (data: any) => {
    try {
      const result = await createJudgeConfig({
        workspaceId,
        name: data.name,
        rubric: data.rubric,
      }).unwrap();

      // Only update selection if creating a new experiment
      if (isCreatingNew) {
        setSelectedJudgeConfigId(result.id);
      } else {
        // Show success toast for fork from read-only view
        toast.success(
          `Judge configuration "${data.name}" created successfully`
        );
      }

      // Clear fork state
      setJudgeConfigToFork(null);

      // Close the editor
      setEditingComponent(null);
    } catch (error) {
      // Show error toast
      toast.error(
        `Failed to create judge configuration: ${(error as any)?.data?.detail || 'Unknown error'}`
      );
    }
  };

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <div className="border-b bg-background">
        <div className="container-fluid px-4 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <Link href="/investigator">
                <Button variant="ghost" size="sm">
                  <ArrowLeft className="h-4 w-4 mr-2" />
                  Workspaces
                </Button>
              </Link>
              <Separator orientation="vertical" className="h-6" />
              <div>
                <h1 className="text-lg font-semibold">
                  {workspace.name || 'Unnamed Workspace'}
                </h1>
                {workspace.description && (
                  <p className="text-xs text-muted-foreground">
                    {workspace.description}
                  </p>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <ModeToggle />
              <UserProfile />
            </div>
          </div>
        </div>
      </div>

      {/* Mount a manager that keeps SSE connections alive per active job */}
      <ExperimentStreamManager workspaceId={workspaceId} />

      {/* Auto-reconnect to active jobs on page load */}
      {sortedExperimentConfigs?.map((config) => (
        <ExperimentAutoReconnect
          key={config.id}
          workspaceId={workspaceId}
          experimentConfigId={config.id}
        />
      ))}

      {/* Load completed experiments from database */}
      {sortedExperimentConfigs?.map((config) => (
        <ExperimentResultLoader
          key={`loader-${config.id}`}
          workspaceId={workspaceId}
          experimentConfigId={config.id}
        />
      ))}

      {/* Main Content Area */}
      <div className="flex-1 flex overflow-hidden">
        {/* Sidebar */}
        <LeftSidebar
          experiments={sortedExperimentConfigs}
          selectedExperimentId={selectedExperiment?.id}
          isCreatingNew={isCreatingNew}
          onExperimentSelect={handleExperimentSelect}
          onNewExperiment={handleNewExperiment}
        />

        {/* Right Panel Container */}
        <div className="flex-1 flex flex-col">
          {/* Top Panel - show when experiment selected, creating new, or editing a component */}
          {(selectedExperiment || isCreatingNew || editingComponent) && (
            <TopPanel
              workspaceId={workspaceId}
              isEditMode={isCreatingNew}
              isNewExperiment={isCreatingNew}
              experimentType={
                isCreatingNew
                  ? experimentType
                  : selectedExperiment?.type || 'counterfactual'
              }
              baseContext={
                selectedBaseContextId || selectedExperiment?.base_context?.id
              }
              judgeConfig={
                selectedJudgeConfigId || selectedExperiment?.judge_config?.id
              }
              backendConfig={
                selectedBackendId ||
                (selectedExperiment?.type === 'counterfactual'
                  ? selectedExperiment?.backend?.id
                  : undefined)
              }
              backendConfigs={
                (isCreatingNew && experimentType === 'simple_rollout') ||
                selectedExperiment?.type === 'simple_rollout'
                  ? selectedBackendIds ||
                    (selectedExperiment?.type === 'simple_rollout'
                      ? selectedExperiment.backends?.map((b: Backend) => b.id)
                      : undefined)
                  : undefined
              }
              counterfactualIdea={
                selectedCounterfactualIdeaId ||
                (selectedExperiment?.type === 'counterfactual'
                  ? selectedExperiment.idea?.id
                  : undefined)
              }
              numCounterfactuals={
                isCreatingNew
                  ? numCounterfactuals
                  : selectedExperiment?.type === 'counterfactual'
                    ? selectedExperiment.num_counterfactuals
                    : undefined
              }
              numReplicas={
                isCreatingNew ? numReplicas : selectedExperiment?.num_replicas
              }
              onExperimentTypeChange={
                isCreatingNew ? setExperimentType : undefined
              }
              onBaseContextChange={handleBaseContextChange}
              onJudgeConfigChange={handleJudgeConfigChange}
              onCounterfactualIdeaChange={handleCounterfactualIdeaChange}
              onBackendConfigChange={handleBackendChange}
              onBackendConfigsChange={setSelectedBackendIds}
              onNumCounterfactualsChange={setNumCounterfactuals}
              onNumReplicasChange={setNumReplicas}
              onNewBaseContext={handleNewBaseContext}
              onViewBaseContext={handleViewBaseContext}
              onNewJudgeConfig={handleNewJudgeConfig}
              onViewJudgeConfig={handleViewJudgeConfig}
              onNewBackendConfig={handleNewBackendConfig}
              onViewBackendConfig={handleViewBackendConfig}
              onNewCounterfactualIdea={handleNewCounterfactualIdea}
              onViewCounterfactualIdea={handleViewCounterfactualIdea}
              onLaunchExperiment={handleLaunchExperiment}
              onForkExperiment={handleForkExperiment}
              onCancelExperiment={
                isExperimentRunning ? handleCancelExperiment : undefined
              }
              onDeleteExperiment={() => setShowDeleteDialog(true)}
            />
          )}

          {/* Main Panel */}
          <MainPanel>
            {/* Show component editors */}
            {editingComponent === 'base-interaction' && (
              <BaseContextEditor
                initialValue={baseContextToFork || undefined}
                onSave={handleSaveBaseContext}
                onCancel={handleCancelEdit}
              />
            )}
            {editingComponent === 'view-base-interaction' &&
              baseContextToView && (
                <BaseContextEditor
                  initialValue={baseContextToView}
                  readOnly={true}
                  onFork={handleForkBaseContext}
                  onDelete={handleDeleteBaseContext}
                  onClose={handleCancelEdit}
                />
              )}
            {editingComponent === 'judge' && (
              <JudgeEditor
                initialValue={judgeConfigToFork || undefined}
                onSave={handleSaveJudgeConfig}
                onCancel={handleCancelEdit}
              />
            )}
            {editingComponent === 'view-judge' && judgeConfigToView && (
              <JudgeEditor
                initialValue={judgeConfigToView}
                readOnly={true}
                onFork={handleForkJudgeConfig}
                onDelete={handleDeleteJudgeConfig}
                onClose={handleCancelEdit}
              />
            )}
            {editingComponent === 'backend' && (
              <BackendEditor
                initialValue={backendToFork as any}
                onSave={handleSaveBackend}
                onCancel={handleCancelEdit}
              />
            )}
            {editingComponent === 'view-backend' && backendToView && (
              <BackendEditor
                initialValue={backendToView as any}
                readOnly={true}
                onFork={handleForkBackendConfig}
                onDelete={handleDeleteBackendConfig}
                onClose={handleCancelEdit}
              />
            )}
            {editingComponent === 'idea' && (
              <CounterfactualIdeaEditor
                initialValue={ideaToFork || undefined}
                onSave={handleSaveCounterfactualIdea}
                onCancel={handleCancelEdit}
              />
            )}
            {editingComponent === 'view-idea' && ideaToView && (
              <CounterfactualIdeaEditor
                initialValue={ideaToView}
                readOnly={true}
                onFork={handleForkCounterfactualIdea}
                onDelete={handleDeleteCounterfactualIdea}
                onClose={handleCancelEdit}
              />
            )}

            {/* Show experiment views */}
            {!editingComponent && selectedExperiment && (
              <>
                {selectedExperiment.type === 'simple_rollout' ? (
                  <SimpleRolloutExperimentViewer
                    experimentConfigId={selectedExperiment.id}
                    onCloneAgentRunToContext={handleCloneAgentRunToContext}
                  />
                ) : (
                  <CounterfactualExperimentViewer
                    experimentConfigId={selectedExperiment.id}
                    onCloneAgentRunToContext={handleCloneAgentRunToContext}
                  />
                )}
              </>
            )}
            {!editingComponent && isCreatingNew && (
              <div className="flex items-center justify-center h-96 border-2 border-dashed rounded-lg">
                <p className="text-muted-foreground">
                  Configure your new experiment above
                </p>
              </div>
            )}
            {!editingComponent && !selectedExperiment && !isCreatingNew && (
              <div className="flex items-center justify-center h-96">
                <p className="text-muted-foreground">
                  Select an experiment or create a new one
                </p>
              </div>
            )}
          </MainPanel>
        </div>
      </div>

      {/* Delete Experiment Confirmation Dialog */}
      {selectedExperiment && (
        <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Delete Experiment</DialogTitle>
              <DialogDescription className="space-y-2">
                <p>
                  Are you sure you want to delete Experiment #
                  {selectedExperiment.id.slice(0, 8)}?
                </p>
                <p className="text-sm text-muted-foreground">
                  This action cannot be undone. The experiment will be removed
                  from your workspace.
                </p>
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setShowDeleteDialog(false)}
              >
                Cancel
              </Button>
              <Button
                onClick={handleDeleteExperiment}
                className="bg-red-bg text-red-text hover:bg-red-muted"
                disabled={isDeletingExperimentConfig}
              >
                Delete
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
