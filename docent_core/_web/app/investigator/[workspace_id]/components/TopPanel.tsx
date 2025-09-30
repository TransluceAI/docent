'use client';

import React from 'react';
import {
  Plus,
  Loader2,
  Search,
  Copy,
  Trash2,
  X,
  Check,
  ChevronsUpDown,
} from 'lucide-react';
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
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { cn } from '@/lib/utils';
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
  experimentType?: 'counterfactual' | 'simple_rollout';
  baseContext?: string;
  judgeConfig?: string;
  backendConfig?: string;
  backendConfigs?: string[];
  counterfactualIdea?: string;
  numCounterfactuals?: number;
  numReplicas?: number;
  onExperimentTypeChange?: (value: 'counterfactual' | 'simple_rollout') => void;
  onBaseContextChange?: (value: string) => void;
  onJudgeConfigChange?: (value: string | undefined) => void;
  onBackendConfigChange?: (value: string) => void;
  onBackendConfigsChange?: (values: string[]) => void;
  onCounterfactualIdeaChange?: (value: string) => void;
  onNumCounterfactualsChange?: (value: number) => void;
  onNumReplicasChange?: (value: number) => void;
  onNewBaseContext?: () => void;
  onViewBaseContext?: () => void;
  onNewJudgeConfig?: () => void;
  onViewJudgeConfig?: () => void;
  onNewBackendConfig?: () => void;
  onViewBackendConfig?: (backendId?: string) => void;
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
  experimentType = 'counterfactual',
  baseContext,
  judgeConfig,
  backendConfig,
  backendConfigs,
  counterfactualIdea,
  numCounterfactuals = 1,
  numReplicas = 16,
  onExperimentTypeChange,
  onBaseContextChange,
  onJudgeConfigChange,
  onBackendConfigChange,
  onBackendConfigsChange,
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
  const CLEAR_JUDGE_VALUE = '__no_judge__';
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

  // Find the names of selected backends for multi-backend display
  const selectedBackendNames = backends
    ?.filter((b) => backendConfigs?.includes(b.id))
    .map((b) => b.name)
    .join(', ');

  // Check if all required fields are selected for Launch button
  const canLaunch =
    isNewExperiment &&
    baseContext &&
    numReplicas > 0 &&
    (experimentType === 'simple_rollout'
      ? backendConfigs && backendConfigs.length > 0
      : experimentType === 'counterfactual' &&
        backendConfig &&
        judgeConfig &&
        counterfactualIdea &&
        numCounterfactuals > 0);
  // Display mode - show static values for existing experiments
  if (!isEditMode) {
    return (
      <div className="border-b bg-secondary p-3 space-y-3">
        <div className="flex flex-wrap">
          {/* Experiment Type - Show as static for existing experiments */}
          {!isNewExperiment && (
            <div className="w-full sm:w-auto pr-3 pb-3">
              <label className="text-xs text-muted-foreground mb-1 block">
                Experiment Type
              </label>
              <div className="w-[200px] px-3 py-2 bg-background rounded-md border text-sm">
                {experimentType === 'simple_rollout'
                  ? 'Simple Rollout'
                  : 'Counterfactual'}
              </div>
            </div>
          )}

          <div className="w-full sm:w-auto pr-3 pb-3">
            <label className="text-xs text-muted-foreground mb-1 block">
              Base Context
            </label>
            <div className="flex gap-2">
              <div
                className="w-[280px] px-3 py-2 bg-background rounded-md border text-sm truncate"
                title={
                  selectedBaseContextName || baseContext || 'Not specified'
                }
              >
                {selectedBaseContextName || baseContext || 'Not specified'}
              </div>
              {baseContext && onViewBaseContext && (
                <Button
                  variant="outline"
                  onClick={onViewBaseContext}
                  className="h-9 w-9 p-0"
                  title="View Base Context"
                >
                  <Search className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>

          {/* Backend Configuration - Different display for simple rollout vs counterfactual */}
          {experimentType === 'simple_rollout' ? (
            <div className="w-full sm:w-auto pr-3 pb-3">
              <label className="text-xs text-muted-foreground mb-1 block">
                Backend Configurations
              </label>
              <div className="flex gap-2">
                <Popover>
                  <PopoverTrigger asChild>
                    <Button
                      variant="outline"
                      role="combobox"
                      className="w-[280px] justify-between"
                    >
                      {backendConfigs && backendConfigs.length > 0 ? (
                        <span className="truncate">
                          {backendConfigs.length === 1
                            ? backends?.find((b) => b.id === backendConfigs[0])
                                ?.name
                            : `${backendConfigs.length} backends selected`}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">
                          Not specified
                        </span>
                      )}
                      <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-[280px] p-0" align="start">
                    <div className="max-h-[300px] overflow-y-auto p-2 space-y-1">
                      {backends?.filter((b) => backendConfigs?.includes(b.id))
                        .length === 0 ? (
                        <div className="text-xs text-muted-foreground p-2">
                          No backends selected
                        </div>
                      ) : (
                        backends
                          ?.filter((b) => backendConfigs?.includes(b.id))
                          .map((backend) => (
                            <div
                              key={backend.id}
                              className="flex items-center space-x-2 p-2 hover:bg-secondary rounded group"
                            >
                              <div className="flex items-center space-x-2 flex-1">
                                <div className="flex h-4 w-4 items-center justify-center rounded border bg-primary border-primary">
                                  <Check className="h-3 w-3 text-primary-foreground" />
                                </div>
                                <span
                                  className="text-sm truncate flex-1"
                                  title={`${backend.name} (${backend.provider} - ${backend.model})`}
                                >
                                  {backend.name}
                                </span>
                              </div>
                              {onViewBackendConfig && (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-6 w-6 p-0 opacity-0 group-hover:opacity-100"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onViewBackendConfig(backend.id);
                                  }}
                                  title="View Backend Configuration"
                                >
                                  <Search className="h-3 w-3" />
                                </Button>
                              )}
                            </div>
                          ))
                      )}
                    </div>
                  </PopoverContent>
                </Popover>
              </div>
            </div>
          ) : (
            <div className="w-full sm:w-auto pr-3 pb-3">
              <label className="text-xs text-muted-foreground mb-1 block">
                Backend Configuration
              </label>
              <div className="flex gap-2">
                <div
                  className="w-[280px] px-3 py-2 bg-background rounded-md border text-sm truncate"
                  title={
                    selectedBackendName || backendConfig || 'Not specified'
                  }
                >
                  {selectedBackendName || backendConfig || 'Not specified'}
                </div>
                {backendConfig && onViewBackendConfig && (
                  <Button
                    variant="outline"
                    onClick={() => onViewBackendConfig()}
                    className="h-9 w-9 p-0"
                    title="View Backend Configuration"
                  >
                    <Search className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>
          )}

          <div className="w-full sm:w-auto pr-3 pb-3">
            <label className="text-xs text-muted-foreground mb-1 block">
              Judge Configuration{' '}
              {experimentType === 'simple_rollout' && '(Optional)'}
            </label>
            <div className="flex gap-2">
              <div
                className="w-[280px] px-3 py-2 bg-background rounded-md border text-sm truncate"
                title={
                  selectedJudgeConfigName || judgeConfig || 'Not specified'
                }
              >
                {selectedJudgeConfigName || judgeConfig || 'Not specified'}
              </div>
              {judgeConfig && onViewJudgeConfig && (
                <Button
                  variant="outline"
                  onClick={onViewJudgeConfig}
                  className="h-9 w-9 p-0"
                  title="View Judge Configuration"
                >
                  <Search className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>

          {/* Counterfactual Idea - Only show for counterfactual experiments */}
          {experimentType === 'counterfactual' && (
            <div className="w-full sm:w-auto pr-3 pb-3">
              <label className="text-xs text-muted-foreground mb-1 block">
                Counterfactual Idea
              </label>
              <div className="flex gap-2">
                <div
                  className="w-[280px] px-3 py-2 bg-background rounded-md border text-sm truncate"
                  title={
                    selectedExperimentIdeaName ||
                    counterfactualIdea ||
                    'Not specified'
                  }
                >
                  {selectedExperimentIdeaName ||
                    counterfactualIdea ||
                    'Not specified'}
                </div>
                {counterfactualIdea && onViewCounterfactualIdea && (
                  <Button
                    variant="outline"
                    onClick={onViewCounterfactualIdea}
                    className="h-9 w-9 p-0"
                    title="View Counterfactual Idea"
                  >
                    <Search className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="flex flex-wrap">
          {/* Number of Counterfactuals - Only show for counterfactual experiments */}
          {experimentType === 'counterfactual' && (
            <div className="w-48 pr-3 pb-3">
              <label className="text-xs text-muted-foreground mb-1 block">
                Number of Counterfactuals
              </label>
              <div className="px-3 py-2 bg-background rounded-md border text-sm">
                {numCounterfactuals}
              </div>
            </div>
          )}

          <div className="w-48 pr-3 pb-3">
            <label className="text-xs text-muted-foreground mb-1 block">
              Number of Replicas
            </label>
            <div className="px-3 py-2 bg-background rounded-md border text-sm">
              {numReplicas}
            </div>
          </div>

          {/* Fork, Cancel, and Delete Buttons - Only show for existing experiments */}
          {!isNewExperiment && (
            <div className="flex items-end gap-2 pr-3 pb-3">
              {onForkExperiment && (
                <Button
                  onClick={onForkExperiment}
                  variant="outline"
                  className="h-9"
                >
                  <Copy className="h-4 w-4 mr-2" />
                  Clone
                </Button>
              )}
              {onCancelExperiment && (
                <Button
                  onClick={onCancelExperiment}
                  variant="outline"
                  className="h-9 text-red-text hover:bg-red-bg border-red-border"
                >
                  <X className="h-4 w-4 mr-2" />
                  Cancel
                </Button>
              )}
              {onDeleteExperiment && (
                <Button
                  onClick={onDeleteExperiment}
                  variant="outline"
                  className="h-9 text-red-text hover:bg-red-bg border-red-border"
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
      <div className="flex flex-wrap">
        {/* Experiment Type Selector - Only show for new experiments */}
        {isNewExperiment && onExperimentTypeChange && (
          <div className="w-full sm:w-auto pr-3 pb-3">
            <label className="text-xs text-muted-foreground mb-1 block">
              Experiment Type
            </label>
            <Select
              value={experimentType}
              onValueChange={onExperimentTypeChange}
            >
              <SelectTrigger className="w-[200px]">
                <SelectValue>
                  {experimentType === 'counterfactual' && 'Counterfactual'}
                  {experimentType === 'simple_rollout' && 'Simple Rollout'}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="counterfactual">
                  <div className="flex flex-col">
                    <span className="font-medium">Counterfactual</span>
                    <span className="text-xs text-muted-foreground">
                      Test variations on a context
                    </span>
                  </div>
                </SelectItem>
                <SelectItem value="simple_rollout">
                  <div className="flex flex-col">
                    <span className="font-medium">Simple Rollout</span>
                    <span className="text-xs text-muted-foreground">
                      Run a context with subject model(s)
                    </span>
                  </div>
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
        )}

        <div className="w-full sm:w-auto pr-3 pb-3">
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
              <SelectTrigger
                className="w-[280px]"
                title={selectedBaseContextName || undefined}
              >
                {isLoadingBaseContexts ? (
                  <div className="flex items-center gap-2">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    <span>Loading...</span>
                  </div>
                ) : (
                  <SelectValue
                    className="truncate"
                    placeholder="Select base context"
                  />
                )}
              </SelectTrigger>
              <SelectContent>
                {baseContexts?.length === 0 ? (
                  <div className="text-xs text-muted-foreground p-2">
                    No base contexts yet. Click + to create one.
                  </div>
                ) : (
                  baseContexts?.map((bi) => (
                    <SelectItem key={bi.id} value={bi.id} title={bi.name}>
                      <span className="block truncate">{bi.name}</span>
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

        {/* Backend Configuration - Different for simple rollout vs counterfactual */}
        {experimentType === 'simple_rollout' ? (
          <div className="w-full sm:w-auto pr-3 pb-3">
            <label className="text-xs text-muted-foreground mb-1 block">
              Backend Configurations (select at least one)
            </label>
            <div className="flex gap-2">
              <Popover>
                <PopoverTrigger asChild>
                  <Button
                    variant="outline"
                    role="combobox"
                    className="w-[280px] justify-between"
                    disabled={isLoadingBackends}
                  >
                    {isLoadingBackends ? (
                      <div className="flex items-center gap-2">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        <span>Loading...</span>
                      </div>
                    ) : backendConfigs && backendConfigs.length > 0 ? (
                      <span className="truncate">
                        {backendConfigs.length === 1
                          ? backends?.find((b) => b.id === backendConfigs[0])
                              ?.name
                          : `${backendConfigs.length} backends selected`}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">
                        Select backends
                      </span>
                    )}
                    <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-[280px] p-0" align="start">
                  <div className="max-h-[300px] overflow-y-auto p-2 space-y-1">
                    {backends?.length === 0 ? (
                      <div className="text-xs text-muted-foreground p-2">
                        No backend configurations yet. Click + to create one.
                      </div>
                    ) : (
                      backends?.map((backend) => (
                        <div
                          key={backend.id}
                          className="flex items-center space-x-2 p-2 hover:bg-secondary rounded group"
                        >
                          <div
                            className="flex items-center space-x-2 flex-1 cursor-pointer"
                            onClick={() => {
                              const isSelected = backendConfigs?.includes(
                                backend.id
                              );
                              const newBackends = isSelected
                                ? (backendConfigs || []).filter(
                                    (id) => id !== backend.id
                                  )
                                : [...(backendConfigs || []), backend.id];
                              onBackendConfigsChange?.(newBackends);
                            }}
                          >
                            <div
                              className={cn(
                                'flex h-4 w-4 items-center justify-center rounded border',
                                backendConfigs?.includes(backend.id)
                                  ? 'bg-primary border-primary'
                                  : 'border-border'
                              )}
                            >
                              {backendConfigs?.includes(backend.id) && (
                                <Check className="h-3 w-3 text-primary-foreground" />
                              )}
                            </div>
                            <span
                              className="text-sm truncate flex-1"
                              title={`${backend.name} (${backend.provider} - ${backend.model})`}
                            >
                              {backend.name}
                            </span>
                          </div>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 w-6 p-0 opacity-0 group-hover:opacity-100"
                            onClick={(e) => {
                              e.stopPropagation();
                              if (onViewBackendConfig) {
                                onViewBackendConfig(backend.id);
                              }
                            }}
                            title="View Backend Configuration"
                          >
                            <Search className="h-3 w-3" />
                          </Button>
                        </div>
                      ))
                    )}
                  </div>
                </PopoverContent>
              </Popover>
              <Button
                variant="outline"
                onClick={onNewBackendConfig}
                className="h-9 w-9 p-0"
                title="New Backend Configuration"
              >
                <Plus className="h-4 w-4" />
              </Button>
            </div>
          </div>
        ) : (
          <div className="w-full sm:w-auto pr-3 pb-3">
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
                <SelectTrigger
                  className="w-[280px]"
                  title={selectedBackendName || undefined}
                >
                  {isLoadingBackends ? (
                    <div className="flex items-center gap-2">
                      <Loader2 className="h-3 w-3 animate-spin" />
                      <span>Loading...</span>
                    </div>
                  ) : (
                    <SelectValue
                      className="truncate"
                      placeholder="Select backend"
                    />
                  )}
                </SelectTrigger>
                <SelectContent>
                  {backends?.length === 0 ? (
                    <div className="text-xs text-muted-foreground p-2">
                      No backend configurations yet. Click + to create one.
                    </div>
                  ) : (
                    backends?.map((backend) => (
                      <SelectItem
                        key={backend.id}
                        value={backend.id}
                        title={`${backend.name} (${backend.provider} - ${backend.model})`}
                      >
                        <span className="block truncate">{backend.name}</span>
                      </SelectItem>
                    ))
                  )}
                </SelectContent>
              </Select>
              {backendConfig &&
                backends?.some((b) => b.id === backendConfig) && (
                  <Button
                    variant="outline"
                    onClick={() => onViewBackendConfig?.()}
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
        )}

        {/* Judge Configuration - Only show for counterfactual experiments or optional for simple rollout */}
        <div className="w-full sm:w-auto pr-3 pb-3">
          <label className="text-xs text-muted-foreground mb-1 block">
            Judge Configuration{' '}
            {experimentType === 'simple_rollout' && '(Optional)'}
          </label>
          <div className="flex gap-2">
            <Select
              value={(() => {
                if (judgeConfigs?.some((jc) => jc.id === judgeConfig)) {
                  return judgeConfig as string;
                }
                if (
                  experimentType === 'simple_rollout' &&
                  (!judgeConfig ||
                    !judgeConfigs?.some((jc) => jc.id === judgeConfig))
                ) {
                  return CLEAR_JUDGE_VALUE;
                }
                return '';
              })()}
              onValueChange={(value) => {
                if (value === CLEAR_JUDGE_VALUE) {
                  onJudgeConfigChange?.(undefined);
                } else {
                  onJudgeConfigChange?.(value);
                }
              }}
              disabled={isLoadingJudgeConfigs}
            >
              <SelectTrigger
                className="w-[280px]"
                title={selectedJudgeConfigName || undefined}
              >
                {isLoadingJudgeConfigs ? (
                  <div className="flex items-center gap-2">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    <span>Loading...</span>
                  </div>
                ) : (
                  <SelectValue
                    className="truncate"
                    placeholder="Select judge"
                  />
                )}
              </SelectTrigger>
              <SelectContent>
                {experimentType === 'simple_rollout' && (
                  <SelectItem value={CLEAR_JUDGE_VALUE}>
                    <span className="block truncate">No judge</span>
                  </SelectItem>
                )}
                {judgeConfigs?.length === 0 ? (
                  <div className="text-xs text-muted-foreground p-2">
                    No judge configurations yet. Click + to create one.
                  </div>
                ) : (
                  judgeConfigs?.map((jc) => (
                    <SelectItem
                      key={jc.id}
                      value={jc.id}
                      title={jc.name || 'Unnamed Judge'}
                    >
                      <span className="block truncate">
                        {jc.name || 'Unnamed Judge'}
                      </span>
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

        {/* Counterfactual Idea - Only show for counterfactual experiments */}
        {experimentType === 'counterfactual' && (
          <div className="w-full sm:w-auto pr-3 pb-3">
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
                <SelectTrigger
                  className="w-[280px]"
                  title={selectedExperimentIdeaName || undefined}
                >
                  {isLoadingExperimentIdeas ? (
                    <div className="flex items-center gap-2">
                      <Loader2 className="h-3 w-3 animate-spin" />
                      <span>Loading...</span>
                    </div>
                  ) : (
                    <SelectValue
                      className="truncate"
                      placeholder="Select idea"
                    />
                  )}
                </SelectTrigger>
                <SelectContent>
                  {experimentIdeas?.length === 0 ? (
                    <div className="text-xs text-muted-foreground p-2">
                      No counterfactual ideas yet. Click + to create one.
                    </div>
                  ) : (
                    experimentIdeas?.map((ei) => (
                      <SelectItem key={ei.id} value={ei.id} title={ei.name}>
                        <span className="block truncate">{ei.name}</span>
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
        )}
      </div>

      <div className="flex flex-wrap">
        {/* Number of Counterfactuals - Only show for counterfactual experiments */}
        {experimentType === 'counterfactual' && (
          <div className="w-48 pr-3 pb-3">
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
        )}

        <div className="w-48 pr-3 pb-3">
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
          <div className="flex items-end pr-3 pb-3">
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
