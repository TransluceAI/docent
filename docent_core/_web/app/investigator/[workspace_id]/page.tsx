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
  useGetOpenAICompatibleBackendsQuery,
  useCreateBaseContextMutation,
  useDeleteBaseContextMutation,
  useCreateJudgeConfigMutation,
  useDeleteJudgeConfigMutation,
  useCreateExperimentIdeaMutation,
  useDeleteExperimentIdeaMutation,
  useCreateOpenAICompatibleBackendMutation,
  useDeleteOpenAICompatibleBackendMutation,
  useGetExperimentConfigsQuery,
  useCreateExperimentConfigMutation,
  useDeleteExperimentConfigMutation,
  useStartExperimentMutation,
  useCancelExperimentMutation,
  useGetActiveExperimentJobsQuery,
} from '@/app/api/investigatorApi';
import { toast } from '@/hooks/use-toast';

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
    name: string;
    provider: string;
    model: string;
    api_key?: string;
    base_url?: string;
  } | null>(null);
  const [backendToFork, setBackendToFork] = useState<{
    name: string;
    provider: string;
    model: string;
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
  const { data: backends, error: backendsError } =
    useGetOpenAICompatibleBackendsQuery(workspaceId, {
      skip: !!workspaceError,
    });
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
  const [createBackend, { isLoading: isCreatingBackend }] =
    useCreateOpenAICompatibleBackendMutation();
  const [createExperimentConfig, { isLoading: isCreatingExperimentConfig }] =
    useCreateExperimentConfigMutation();
  const [deleteExperimentConfig, { isLoading: isDeletingExperimentConfig }] =
    useDeleteExperimentConfigMutation();
  const [startExperiment] = useStartExperimentMutation();
  const [cancelExperiment, { isLoading: isCancellingExperiment }] =
    useCancelExperimentMutation();

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
  const [deleteBackend, { isLoading: isDeletingBackend }] =
    useDeleteOpenAICompatibleBackendMutation();

  // Sync selected IDs when experiment changes
  useEffect(() => {
    if (selectedExperiment) {
      setSelectedBaseContextId(selectedExperiment.base_context_id);
      setSelectedJudgeConfigId(selectedExperiment.judge_config_id);
      setSelectedBackendId(selectedExperiment.openai_compatible_backend_id);
      setSelectedCounterfactualIdeaId(selectedExperiment.idea_id);
      setNumCounterfactuals(selectedExperiment.num_counterfactuals);
      setNumReplicas(selectedExperiment.num_replicas);
    } else if (!isCreatingNew) {
      // Clear selections when no experiment is selected (unless creating new)
      setSelectedBaseContextId(undefined);
      setSelectedJudgeConfigId(undefined);
      setSelectedBackendId(undefined);
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
    const experiment = experimentConfigs?.find((exp) => exp.id === id);
    if (experiment) {
      // Update URL to select experiment
      router.push(`/investigator/${workspaceId}?experiment=${id}`);
      setEditingComponent(null);

      // Reset the selected IDs to the experiment's values
      setSelectedBaseContextId(experiment.base_context_id);
      setSelectedJudgeConfigId(experiment.judge_config_id);
      setSelectedBackendId(experiment.openai_compatible_backend_id);
      setSelectedCounterfactualIdeaId(experiment.idea_id);
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

    // Keep the selected IDs from the current experiment
    setSelectedBaseContextId(selectedExperiment.base_context_id);
    setSelectedJudgeConfigId(selectedExperiment.judge_config_id);
    setSelectedBackendId(selectedExperiment.openai_compatible_backend_id);
    setSelectedCounterfactualIdeaId(selectedExperiment.idea_id);
    setNumCounterfactuals(selectedExperiment.num_counterfactuals);
    setNumReplicas(selectedExperiment.num_replicas);
  };

  const handleCancelExperiment = async () => {
    if (!selectedExperiment) return;

    try {
      await cancelExperiment({
        workspaceId,
        experimentConfigId: selectedExperiment.id,
      }).unwrap();

      toast({
        title: 'Success',
        description: 'Experiment cancelled successfully',
      });

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
      toast({
        title: 'Success',
        description: 'Experiment deleted successfully',
      });
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
        if (
          !selectedBaseContextId ||
          !selectedJudgeConfigId ||
          !selectedBackendId ||
          !selectedCounterfactualIdeaId
        ) {
          toast({
            title: 'Error',
            description: 'Please select all required fields before launching',
            variant: 'destructive',
          });
          return;
        }

        const created = await createExperimentConfig({
          workspaceId,
          base_context_id: selectedBaseContextId,
          judge_config_id: selectedJudgeConfigId,
          openai_compatible_backend_id: selectedBackendId,
          idea_id: selectedCounterfactualIdeaId,
          num_counterfactuals: numCounterfactuals,
          num_replicas: numReplicas,
          max_turns: 1,
        }).unwrap();
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
    if (selectedBaseContextId && baseContexts) {
      const selectedBI = baseContexts.find(
        (bi) => bi.id === selectedBaseContextId
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
      toast({
        title: 'Success',
        description: 'Base context deleted successfully',
      });
    } catch (error) {
      // Show error toast
      toast({
        title: 'Error',
        description: `Failed to delete base context: ${(error as any)?.data?.detail || 'Unknown error'}`,
        variant: 'destructive',
      });
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
    if (selectedJudgeConfigId && judgeConfigs) {
      const selectedJC = judgeConfigs.find(
        (jc) => jc.id === selectedJudgeConfigId
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
      toast({
        title: 'Success',
        description: 'Judge configuration deleted successfully',
      });
    } catch (error) {
      toast({
        title: 'Error',
        description: `Failed to delete judge configuration: ${(error as any)?.data?.detail || 'Unknown error'}`,
        variant: 'destructive',
      });
    }
  };

  const handleNewBackendConfig = () => {
    if (selectedBackendId && backends) {
      const selectedBackend = backends.find((b) => b.id === selectedBackendId);
      if (selectedBackend) {
        setBackendToFork({
          name: getNextForkName(selectedBackend.name),
          provider: selectedBackend.provider,
          model: selectedBackend.model,
          api_key: selectedBackend.api_key ?? undefined,
          base_url: selectedBackend.base_url ?? undefined,
        });
        setEditingComponent('backend');
      }
    } else {
      setBackendToFork(null);
      setEditingComponent('backend');
    }
  };

  const handleViewBackendConfig = () => {
    if (selectedBackendId && backends) {
      const selectedBackend = backends.find((b) => b.id === selectedBackendId);
      if (selectedBackend) {
        setBackendToView({
          name: selectedBackend.name,
          provider: selectedBackend.provider,
          model: selectedBackend.model,
          api_key: selectedBackend.api_key ?? undefined,
          base_url: selectedBackend.base_url ?? undefined,
        });
        setEditingComponent('view-backend');
      }
    }
  };

  const handleForkBackendConfig = (data: {
    name: string;
    provider: string;
    model: string;
    api_key?: string;
    base_url?: string;
  }) => {
    setBackendToFork(data);
    setEditingComponent('backend');
  };

  const handleDeleteBackendConfig = async () => {
    if (!selectedBackendId) return;

    try {
      await deleteBackend(selectedBackendId).unwrap();
      setSelectedBackendId(undefined);
      setBackendToView(null);
      setEditingComponent(null);
      toast({
        title: 'Success',
        description: 'Backend configuration deleted successfully',
      });
    } catch (error) {
      toast({
        title: 'Error',
        description: `Failed to delete backend configuration: ${(error as any)?.data?.detail || 'Unknown error'}`,
        variant: 'destructive',
      });
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
    if (selectedCounterfactualIdeaId && experimentIdeas) {
      const selectedIdea = experimentIdeas.find(
        (ei) => ei.id === selectedCounterfactualIdeaId
      );
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
      toast({
        title: 'Success',
        description: 'Counterfactual idea deleted successfully',
      });
    } catch (error) {
      toast({
        title: 'Error',
        description: `Failed to delete counterfactual idea: ${(error as any)?.data?.detail || 'Unknown error'}`,
        variant: 'destructive',
      });
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
        toast({
          title: 'Success',
          description: `Base context "${data.name}" created successfully`,
        });
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
        toast({
          title: 'Success',
          description: `Counterfactual idea "${data.name}" created successfully`,
        });
      }

      // Clear fork state
      setIdeaToFork(null);

      // Close the editor
      setEditingComponent(null);
    } catch (error) {
      // Show error toast
      toast({
        title: 'Error',
        description: `Failed to create counterfactual idea: ${(error as any)?.data?.detail || 'Unknown error'}`,
        variant: 'destructive',
      });
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
      (ctx) => ctx.id === selectedExperiment.base_context_id
    );
    if (!baseContext) {
      toast({
        title: 'Cannot clone',
        description: 'Could not find base context configuration',
        variant: 'destructive',
      });
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

  const handleJudgeConfigChange = (value: string) => {
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
      const result = await createBackend({
        workspaceId,
        name: data.name,
        provider: data.provider,
        model: data.model,
        api_key: data.api_key,
        base_url: data.base_url,
      }).unwrap();

      // Only update selection if creating a new experiment
      if (isCreatingNew) {
        setSelectedBackendId(result.id);
      } else {
        // Show success toast for fork from read-only view
        toast({
          title: 'Success',
          description: `Backend configuration "${data.name}" created successfully`,
        });
      }

      // Clear fork state
      setBackendToFork(null);

      // Close the editor
      setEditingComponent(null);
    } catch (error) {
      // Show error toast
      toast({
        title: 'Error',
        description: `Failed to create backend configuration: ${(error as any)?.data?.detail || 'Unknown error'}`,
        variant: 'destructive',
      });
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
        toast({
          title: 'Success',
          description: `Judge configuration "${data.name}" created successfully`,
        });
      }

      // Clear fork state
      setJudgeConfigToFork(null);

      // Close the editor
      setEditingComponent(null);
    } catch (error) {
      // Show error toast
      toast({
        title: 'Error',
        description: `Failed to create judge configuration: ${(error as any)?.data?.detail || 'Unknown error'}`,
        variant: 'destructive',
      });
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
      {experimentConfigs?.map((config) => (
        <ExperimentAutoReconnect
          key={config.id}
          workspaceId={workspaceId}
          experimentConfigId={config.id}
        />
      ))}

      {/* Load completed experiments from database */}
      {experimentConfigs?.map((config) => (
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
          experiments={experimentConfigs}
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
              baseContext={
                selectedBaseContextId || selectedExperiment?.base_context_id
              }
              judgeConfig={
                selectedJudgeConfigId || selectedExperiment?.judge_config_id
              }
              backendConfig={
                selectedBackendId ||
                selectedExperiment?.openai_compatible_backend_id
              }
              counterfactualIdea={
                selectedCounterfactualIdeaId || selectedExperiment?.idea_id
              }
              numCounterfactuals={
                isCreatingNew
                  ? numCounterfactuals
                  : selectedExperiment?.num_counterfactuals
              }
              numReplicas={
                isCreatingNew ? numReplicas : selectedExperiment?.num_replicas
              }
              onBaseContextChange={handleBaseContextChange}
              onJudgeConfigChange={handleJudgeConfigChange}
              onCounterfactualIdeaChange={handleCounterfactualIdeaChange}
              onBackendConfigChange={handleBackendChange}
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
                initialValue={backendToFork || undefined}
                onSave={handleSaveBackend}
                onCancel={handleCancelEdit}
              />
            )}
            {editingComponent === 'view-backend' && backendToView && (
              <BackendEditor
                initialValue={backendToView}
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
              <CounterfactualExperimentViewer
                experimentConfigId={selectedExperiment.id}
                onCloneAgentRunToContext={handleCloneAgentRunToContext}
              />
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
