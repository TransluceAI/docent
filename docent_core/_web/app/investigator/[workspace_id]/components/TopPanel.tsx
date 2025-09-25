'use client';

import React from 'react';
import { Plus, Loader2, Search, Copy, Trash2, X } from 'lucide-react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  useGetBaseContextsQuery,
  useGetJudgeConfigsQuery,
  useGetExperimentIdeasQuery,
  useGetOpenAICompatibleBackendsQuery,
} from '@/app/api/investigatorApi';

interface TopPanelProps {
  workspaceId: string;
  isEditMode?: boolean;
  isNewExperiment?: boolean;
  baseContext?: string;
  judgeConfig?: string;
  backendConfig?: string;
  counterfactualIdea?: string;
  numCounterfactuals?: number;
  numReplicas?: number;
  onBaseContextChange?: (value: string) => void;
  onJudgeConfigChange?: (value: string) => void;
  onBackendConfigChange?: (value: string) => void;
  onCounterfactualIdeaChange?: (value: string) => void;
  onNumCounterfactualsChange?: (value: number) => void;
  onNumReplicasChange?: (value: number) => void;
  onNewBaseContext?: () => void;
  onViewBaseContext?: () => void;
  onNewJudgeConfig?: () => void;
  onViewJudgeConfig?: () => void;
  onNewBackendConfig?: () => void;
  onViewBackendConfig?: () => void;
  onNewCounterfactualIdea?: () => void;
  onViewCounterfactualIdea?: () => void;
  onLaunchExperiment?: () => void;
  onForkExperiment?: () => void;
  onCancelExperiment?: () => void;
  onDeleteExperiment?: () => void;
}

export default function TopPanel({
  workspaceId,
  isEditMode = false,
  isNewExperiment = false,
  baseContext,
  judgeConfig,
  backendConfig,
  counterfactualIdea,
  numCounterfactuals = 1,
  numReplicas = 16,
  onBaseContextChange,
  onJudgeConfigChange,
  onBackendConfigChange,
  onCounterfactualIdeaChange,
  onNumCounterfactualsChange,
  onNumReplicasChange,
  onNewBaseContext,
  onViewBaseContext,
  onNewJudgeConfig,
  onViewJudgeConfig,
  onNewBackendConfig,
  onViewBackendConfig,
  onNewCounterfactualIdea,
  onViewCounterfactualIdea,
  onLaunchExperiment,
  onForkExperiment,
  onCancelExperiment,
  onDeleteExperiment,
}: TopPanelProps) {
  // Fetch base contexts from the API
  const { data: baseContexts, isLoading: isLoadingBaseContexts } =
    useGetBaseContextsQuery(workspaceId);

  // Fetch judge configs from the API
  const { data: judgeConfigs, isLoading: isLoadingJudgeConfigs } =
    useGetJudgeConfigsQuery(workspaceId);

  // Fetch experiment ideas from the API
  const { data: experimentIdeas, isLoading: isLoadingExperimentIdeas } =
    useGetExperimentIdeasQuery(workspaceId);

  // Fetch OpenAI compatible backends from the API
  const { data: backends, isLoading: isLoadingBackends } =
    useGetOpenAICompatibleBackendsQuery(workspaceId);

  // Find the name of the selected base context for display mode
  const selectedBaseContextName = baseContexts?.find(
    (bi) => bi.id === baseContext
  )?.name;

  // Find the name of the selected judge config for display mode
  const selectedJudgeConfigName = judgeConfigs?.find(
    (jc) => jc.id === judgeConfig
  )?.name;

  // Find the name of the selected experiment idea for display mode
  const selectedExperimentIdeaName = experimentIdeas?.find(
    (ei) => ei.id === counterfactualIdea
  )?.name;

  // Find the name of the selected backend for display mode
  const selectedBackendName = backends?.find(
    (b) => b.id === backendConfig
  )?.name;

  // Check if all required fields are selected for Launch button
  const canLaunch =
    isNewExperiment &&
    baseContext &&
    judgeConfig &&
    backendConfig &&
    counterfactualIdea &&
    numCounterfactuals > 0 &&
    numReplicas > 0;
  // Display mode - show static values for existing experiments
  if (!isEditMode) {
    return (
      <div className="border-b bg-secondary p-3 space-y-3">
        <div className="flex gap-3">
          <div className="flex-1">
            <label className="text-xs text-muted-foreground mb-1 block">
              Base Context
            </label>
            <div className="flex gap-2">
              <div className="flex-1 px-3 py-2 bg-background rounded-md border text-sm">
                {selectedBaseContextName || baseContext || 'Not specified'}
              </div>
              {baseContext && onViewBaseContext && (
                <Button
                  variant="outline"
                  onClick={onViewBaseContext}
                  className="h-[38px] w-[38px] p-0"
                  title="View Base Context"
                >
                  <Search className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>

          <div className="flex-1">
            <label className="text-xs text-muted-foreground mb-1 block">
              Judge Configuration
            </label>
            <div className="flex gap-2">
              <div className="flex-1 px-3 py-2 bg-background rounded-md border text-sm">
                {selectedJudgeConfigName || judgeConfig || 'Not specified'}
              </div>
              {judgeConfig && onViewJudgeConfig && (
                <Button
                  variant="outline"
                  onClick={onViewJudgeConfig}
                  className="h-[38px] w-[38px] p-0"
                  title="View Judge Configuration"
                >
                  <Search className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>

          <div className="flex-1">
            <label className="text-xs text-muted-foreground mb-1 block">
              Backend Configuration
            </label>
            <div className="flex gap-2">
              <div className="flex-1 px-3 py-2 bg-background rounded-md border text-sm">
                {selectedBackendName || backendConfig || 'Not specified'}
              </div>
              {backendConfig && onViewBackendConfig && (
                <Button
                  variant="outline"
                  onClick={onViewBackendConfig}
                  className="h-[38px] w-[38px] p-0"
                  title="View Backend Configuration"
                >
                  <Search className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>

          <div className="flex-1">
            <label className="text-xs text-muted-foreground mb-1 block">
              Counterfactual Idea
            </label>
            <div className="flex gap-2">
              <div className="flex-1 px-3 py-2 bg-background rounded-md border text-sm">
                {selectedExperimentIdeaName ||
                  counterfactualIdea ||
                  'Not specified'}
              </div>
              {counterfactualIdea && onViewCounterfactualIdea && (
                <Button
                  variant="outline"
                  onClick={onViewCounterfactualIdea}
                  className="h-[38px] w-[38px] p-0"
                  title="View Counterfactual Idea"
                >
                  <Search className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>
        </div>

        <div className="flex gap-3">
          <div className="w-48">
            <label className="text-xs text-muted-foreground mb-1 block">
              Number of Counterfactuals
            </label>
            <div className="px-3 py-2 bg-background rounded-md border text-sm">
              {numCounterfactuals}
            </div>
          </div>

          <div className="w-48">
            <label className="text-xs text-muted-foreground mb-1 block">
              Number of Replicas
            </label>
            <div className="px-3 py-2 bg-background rounded-md border text-sm">
              {numReplicas}
            </div>
          </div>

          {/* Fork, Cancel, and Delete Buttons - Only show for existing experiments */}
          {!isNewExperiment && (
            <div className="flex items-end gap-2">
              {onForkExperiment && (
                <Button
                  onClick={onForkExperiment}
                  variant="outline"
                  className="h-[38px]"
                >
                  <Copy className="h-4 w-4 mr-2" />
                  Clone
                </Button>
              )}
              {onCancelExperiment && (
                <Button
                  onClick={onCancelExperiment}
                  variant="outline"
                  className="h-[38px] text-red-text hover:bg-red-bg border-red-border"
                >
                  <X className="h-4 w-4 mr-2" />
                  Cancel
                </Button>
              )}
              {onDeleteExperiment && (
                <Button
                  onClick={onDeleteExperiment}
                  variant="outline"
                  className="h-[38px] text-red-text hover:bg-red-bg border-red-border"
                >
                  <Trash2 className="h-4 w-4 mr-2" />
                  Delete
                </Button>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }

  // Edit mode - show selectors for new experiments
  return (
    <div className="border-b bg-background p-3 space-y-3">
      <div className="flex gap-3">
        <div className="flex-1">
          <label className="text-xs text-muted-foreground mb-1 block">
            Base Context
          </label>
          <div className="flex gap-2">
            <Select
              value={
                baseContexts?.some((bi) => bi.id === baseContext)
                  ? baseContext
                  : ''
              }
              onValueChange={onBaseContextChange}
              disabled={isLoadingBaseContexts}
            >
              <SelectTrigger className="flex-1">
                {isLoadingBaseContexts ? (
                  <div className="flex items-center gap-2">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    <span>Loading...</span>
                  </div>
                ) : (
                  <SelectValue placeholder="Select base context" />
                )}
              </SelectTrigger>
              <SelectContent>
                {baseContexts?.length === 0 ? (
                  <div className="text-xs text-muted-foreground p-2">
                    No base contexts yet. Click + to create one.
                  </div>
                ) : (
                  baseContexts?.map((bi) => (
                    <SelectItem key={bi.id} value={bi.id}>
                      {bi.name}
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
            {baseContext &&
              baseContexts?.some((bi) => bi.id === baseContext) && (
                <Button
                  variant="outline"
                  onClick={onViewBaseContext}
                  className="h-9 w-9 p-0"
                  title="View Base Context"
                >
                  <Search className="h-4 w-4" />
                </Button>
              )}
            <Button
              variant="outline"
              onClick={onNewBaseContext}
              className="h-9 w-9 p-0"
              title={
                baseContext && baseContexts?.some((bi) => bi.id === baseContext)
                  ? 'Clone Base Context'
                  : 'New Base Context'
              }
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div className="flex-1">
          <label className="text-xs text-muted-foreground mb-1 block">
            Judge Configuration
          </label>
          <div className="flex gap-2">
            <Select
              value={
                judgeConfigs?.some((jc) => jc.id === judgeConfig)
                  ? judgeConfig
                  : ''
              }
              onValueChange={onJudgeConfigChange}
              disabled={isLoadingJudgeConfigs}
            >
              <SelectTrigger className="flex-1">
                {isLoadingJudgeConfigs ? (
                  <div className="flex items-center gap-2">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    <span>Loading...</span>
                  </div>
                ) : (
                  <SelectValue placeholder="Select judge" />
                )}
              </SelectTrigger>
              <SelectContent>
                {judgeConfigs?.length === 0 ? (
                  <div className="text-xs text-muted-foreground p-2">
                    No judge configurations yet. Click + to create one.
                  </div>
                ) : (
                  judgeConfigs?.map((jc) => (
                    <SelectItem key={jc.id} value={jc.id}>
                      {jc.name || 'Unnamed Judge'}
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
            {judgeConfig &&
              judgeConfigs?.some((jc) => jc.id === judgeConfig) && (
                <Button
                  variant="outline"
                  onClick={onViewJudgeConfig}
                  className="h-9 w-9 p-0"
                  title="View Judge Configuration"
                >
                  <Search className="h-4 w-4" />
                </Button>
              )}
            <Button
              variant="outline"
              onClick={onNewJudgeConfig}
              className="h-9 w-9 p-0"
              title={
                judgeConfig && judgeConfigs?.some((jc) => jc.id === judgeConfig)
                  ? 'Clone Judge Configuration'
                  : 'New Judge Configuration'
              }
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div className="flex-1">
          <label className="text-xs text-muted-foreground mb-1 block">
            Backend Configuration
          </label>
          <div className="flex gap-2">
            <Select
              value={
                backends?.some((b) => b.id === backendConfig)
                  ? backendConfig
                  : ''
              }
              onValueChange={onBackendConfigChange}
              disabled={isLoadingBackends}
            >
              <SelectTrigger className="flex-1">
                {isLoadingBackends ? (
                  <div className="flex items-center gap-2">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    <span>Loading...</span>
                  </div>
                ) : (
                  <SelectValue placeholder="Select backend" />
                )}
              </SelectTrigger>
              <SelectContent>
                {backends?.length === 0 ? (
                  <div className="text-xs text-muted-foreground p-2">
                    No backend configurations yet. Click + to create one.
                  </div>
                ) : (
                  backends?.map((backend) => (
                    <SelectItem key={backend.id} value={backend.id}>
                      {backend.name}
                      <span className="text-xs text-muted-foreground ml-2">
                        ({backend.provider} - {backend.model})
                      </span>
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
            {backendConfig && backends?.some((b) => b.id === backendConfig) && (
              <Button
                variant="outline"
                onClick={onViewBackendConfig}
                className="h-9 w-9 p-0"
                title="View Backend Configuration"
              >
                <Search className="h-4 w-4" />
              </Button>
            )}
            <Button
              variant="outline"
              onClick={onNewBackendConfig}
              className="h-9 w-9 p-0"
              title={
                backendConfig && backends?.some((b) => b.id === backendConfig)
                  ? 'Clone Backend Configuration'
                  : 'New Backend Configuration'
              }
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div className="flex-1">
          <label className="text-xs text-muted-foreground mb-1 block">
            Counterfactual Idea
          </label>
          <div className="flex gap-2">
            <Select
              value={
                experimentIdeas?.some((ei) => ei.id === counterfactualIdea)
                  ? counterfactualIdea
                  : ''
              }
              onValueChange={onCounterfactualIdeaChange}
              disabled={isLoadingExperimentIdeas}
            >
              <SelectTrigger className="flex-1">
                {isLoadingExperimentIdeas ? (
                  <div className="flex items-center gap-2">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    <span>Loading...</span>
                  </div>
                ) : (
                  <SelectValue placeholder="Select idea" />
                )}
              </SelectTrigger>
              <SelectContent>
                {experimentIdeas?.length === 0 ? (
                  <div className="text-xs text-muted-foreground p-2">
                    No counterfactual ideas yet. Click + to create one.
                  </div>
                ) : (
                  experimentIdeas?.map((ei) => (
                    <SelectItem key={ei.id} value={ei.id}>
                      {ei.name}
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
            {counterfactualIdea &&
              experimentIdeas?.some((ei) => ei.id === counterfactualIdea) && (
                <Button
                  variant="outline"
                  onClick={onViewCounterfactualIdea}
                  className="h-9 w-9 p-0"
                  title="View Counterfactual Idea"
                >
                  <Search className="h-4 w-4" />
                </Button>
              )}
            <Button
              variant="outline"
              onClick={onNewCounterfactualIdea}
              className="h-9 w-9 p-0"
              title={
                counterfactualIdea &&
                experimentIdeas?.some((ei) => ei.id === counterfactualIdea)
                  ? 'Clone Counterfactual Idea'
                  : 'New Counterfactual Idea'
              }
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>

      <div className="flex gap-3">
        <div className="w-48">
          <label className="text-xs text-muted-foreground mb-1 block">
            Number of Counterfactuals
          </label>
          <Input
            type="number"
            min="1"
            max="64"
            value={numCounterfactuals || ''}
            onChange={(e) => {
              const value = parseInt(e.target.value);
              // Only update if it's a valid number
              if (!isNaN(value)) {
                // Cap at 64 counterfactuals
                const cappedValue = Math.min(Math.max(value, 1), 64);
                onNumCounterfactualsChange?.(cappedValue);
              } else if (e.target.value === '') {
                // Allow clearing the field temporarily
                onNumCounterfactualsChange?.(0);
              }
            }}
            onBlur={(e) => {
              // Set to 1 if empty or invalid on blur
              const value = parseInt(e.target.value);
              if (isNaN(value) || value < 1) {
                onNumCounterfactualsChange?.(1);
              }
            }}
            className="w-full"
          />
        </div>

        <div className="w-48">
          <label className="text-xs text-muted-foreground mb-1 block">
            Number of Replicas
          </label>
          <Input
            type="number"
            min="1"
            max="256"
            value={numReplicas || ''}
            onChange={(e) => {
              const value = parseInt(e.target.value);
              // Only update if it's a valid number
              if (!isNaN(value)) {
                // Cap at 256 replicas
                const cappedValue = Math.min(Math.max(value, 1), 256);
                onNumReplicasChange?.(cappedValue);
              } else if (e.target.value === '') {
                // Allow clearing the field temporarily
                onNumReplicasChange?.(0);
              }
            }}
            onBlur={(e) => {
              // Set to 1 if empty or invalid on blur
              const value = parseInt(e.target.value);
              if (isNaN(value) || value < 1) {
                onNumReplicasChange?.(1);
              }
            }}
            className="w-full"
          />
        </div>

        {/* Launch Button - Only show for new experiments */}
        {isNewExperiment && (
          <div className="flex items-end">
            <Button
              onClick={onLaunchExperiment}
              disabled={!canLaunch}
              className="h-9"
            >
              Launch Experiment
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
