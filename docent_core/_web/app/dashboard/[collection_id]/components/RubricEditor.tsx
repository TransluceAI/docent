'use client';

import {
  Save,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Braces,
} from 'lucide-react';
import { useState, useEffect, useMemo } from 'react';
import { skipToken } from '@reduxjs/toolkit/query';

import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';

import { JudgeModel, type Rubric } from '@/app/store/rubricSlice';

import {
  useGetRubricQuery,
  useGetLatestRubricVersionQuery,
  useGetJudgeModelsQuery,
  rubricApi,
} from '@/app/api/rubricApi';
import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { KeyRound } from 'lucide-react';
import OutputSchemaDialog from './OutputSchemaDialog';

function DescriptionInlineDiff({
  previous,
  current,
}: {
  previous: string;
  current: string;
}) {
  if (previous === current) {
    return (
      <div className="rounded-sm border-0 bg-background p-2">
        <div className="text-[11px] uppercase text-muted-foreground mb-1">
          No changes from previous version
        </div>
        <div className="text-xs whitespace-pre-wrap break-words font-mono">
          {current}
        </div>
      </div>
    );
  }

  const tokenize = (text: string) => text.match(/\S+\s*/g) || [];
  const wordOf = (token: string) => token.trim();

  const prevTokens = tokenize(previous);
  const currTokens = tokenize(current);
  const prevWords = prevTokens.map(wordOf);
  const currWords = currTokens.map(wordOf);

  const m = prevWords.length;
  const n = currWords.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () =>
    Array(n + 1).fill(0)
  );
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i][j] =
        prevWords[i] === currWords[j]
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const nodes: JSX.Element[] = [];
  let i = 0;
  let j = 0;
  while (i < m || j < n) {
    if (i < m && j < n && prevWords[i] === currWords[j]) {
      nodes.push(<span key={`eq-${i}-${j}`}>{currTokens[j]}</span>);
      i++;
      j++;
    } else if (j < n && (i === m || dp[i][j + 1] >= (dp[i + 1]?.[j] ?? -1))) {
      nodes.push(
        <span
          key={`add-${i}-${j}`}
          className="bg-green-bg/40 text-green-text rounded px-0.5"
        >
          {currTokens[j]}
        </span>
      );
      j++;
    } else if (i < m) {
      nodes.push(
        <span
          key={`del-${i}-${j}`}
          className="bg-red-bg/40 text-red-text line-through rounded px-0.5"
        >
          {prevTokens[i]}
        </span>
      );
      i++;
    } else {
      break;
    }
  }

  return (
    <div className="h-[40vh] rounded-sm border-0 bg-background p-2 overflow-y-auto custom-scrollbar">
      {/* <div className="text-[11px] uppercase text-muted-foreground mb-1">
        Description changes
      </div> */}
      <div className="text-xs whitespace-pre-wrap break-words font-mono">
        {nodes}
      </div>
    </div>
  );
}

function nameJudgeModel(jm: JudgeModel | null) {
  if (!jm) {
    return 'Default';
  }
  if (jm.reasoning_effort) {
    return `${jm.provider}/${jm.model_name} (${jm.reasoning_effort} reasoning effort)`;
  }
  return `${jm.provider}/${jm.model_name}`;
}

interface RubricEditorProps {
  rubricId: string;
  rubricVersion: number | null;
  setRubricVersion?: (version: number) => void;
  showDiff?: boolean;
  setShowDiff?: (show: boolean) => void;
  onSave: (rubric: Rubric) => void;
  onCloseWithoutSave?: () => void;
  editable: boolean;
  onHasUnsavedChangesUpdated?: (hasChanges: boolean) => void;
}

export default function RubricEditor({
  rubricId,
  rubricVersion,
  setRubricVersion,
  showDiff,
  setShowDiff,
  onSave,
  onCloseWithoutSave,
  editable,
  onHasUnsavedChangesUpdated,
}: RubricEditorProps) {
  const isDisabled = !editable;

  const collectionId = useAppSelector((state) => state.collection.collectionId);
  const dispatch = useAppDispatch();

  // Get the remote rubric
  const { data: remoteRubric } = useGetRubricQuery(
    collectionId
      ? {
          collectionId: collectionId,
          rubricId: rubricId,
          version: rubricVersion,
        }
      : skipToken
  );

  // Local rubric is for editing
  const [localRubric, setLocalRubric] = useState<Rubric | null>(null);
  useEffect(() => {
    if (remoteRubric && editable) {
      setLocalRubric(remoteRubric);
    }
  }, [remoteRubric, editable]);

  // Get the latest version number
  const minVersion = 1;
  const { data: maxVersion } = useGetLatestRubricVersionQuery(
    collectionId
      ? {
          collectionId: collectionId,
          rubricId: rubricId,
        }
      : skipToken
  );

  // When the rubric version changes, invalidate the latest rubric version query
  useEffect(() => {
    dispatch(rubricApi.util.invalidateTags([{ type: 'Rubric', id: rubricId }]));
  }, [rubricVersion, rubricId, dispatch]);

  const { data: availableJudgeModels } = useGetJudgeModelsQuery();

  // The rubric to display is either the local or remote rubric, depending on the editable flag
  const rubric = useMemo(() => {
    return editable ? localRubric : remoteRubric;
  }, [localRubric, remoteRubric, editable]);

  // Previous version state
  const { data: prevRubricRemote } = useGetRubricQuery(
    collectionId && rubric && rubric.version >= 2 && showDiff
      ? {
          collectionId: collectionId as string,
          rubricId: rubricId,
          version: Math.max(1, rubric.version - 1),
        }
      : skipToken
  );

  // Inline editing state
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [isSchemaDialogOpen, setIsSchemaDialogOpen] = useState(false);

  // Helper function to create a new rubric with updates
  const updateRubric = (updates: Partial<Rubric>) => {
    setLocalRubric((prev) => {
      if (!prev) return null;
      return {
        ...prev,
        ...updates,
      };
    });
  };

  // Handler functions for rubric editing
  const handleDescriptionChange = (
    e: React.ChangeEvent<HTMLTextAreaElement>
  ) => {
    if (!editable) return;
    updateRubric({ rubric_text: e.target.value });
  };

  // Version control handlers
  const handleVersionDecrement = () => {
    if (setRubricVersion && rubric && rubric.version > minVersion) {
      setRubricVersion(rubric.version - 1);
    }
  };

  const handleVersionIncrement = () => {
    if (
      setRubricVersion &&
      rubric &&
      maxVersion !== undefined &&
      rubric.version < maxVersion
    ) {
      setRubricVersion(rubric.version + 1);
    }
  };

  const handleSave = () => {
    if (rubric) {
      if (maxVersion === undefined) throw new Error('Latest version not found');

      const updatedRubric = {
        ...rubric,
        // Possibly skips over some versions, if rubric.version < latestVersion
        // TODO(mengk): consider whether this is ok
        version: maxVersion + 1,
      };
      onSave(updatedRubric);
    }
  };

  const hasChanges = useMemo(() => {
    if (!editable) return false;
    return (
      rubric?.rubric_text !== remoteRubric?.rubric_text ||
      JSON.stringify(rubric?.judge_model) !==
        JSON.stringify(remoteRubric?.judge_model) ||
      JSON.stringify(rubric?.output_schema) !==
        JSON.stringify(remoteRubric?.output_schema)
    );
  }, [rubric, remoteRubric, editable]);
  useEffect(() => {
    if (onHasUnsavedChangesUpdated) {
      onHasUnsavedChangesUpdated(hasChanges);
    }
  }, [hasChanges, onHasUnsavedChangesUpdated]);

  return (
    <div className="space-y-2">
      <div className="flex justify-between">
        <div>
          <div className="text-sm font-semibold">
            {editable ? 'Rubric Editor' : 'Rubric Evaluation'}
          </div>
          <div className="text-xs text-muted-foreground">
            {editable
              ? 'Modify the specification of a rubric.'
              : 'Explore the results of running the rubric against data.'}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div className="text-xs text-muted-foreground">Version:</div>
          <div className="flex items-center gap-0.5 bg-secondary rounded border px-1 py-0.5">
            {setRubricVersion && (
              <Button
                size="sm"
                variant="ghost"
                className="h-4 w-4 p-0 hover:bg-background/50"
                onClick={handleVersionDecrement}
                disabled={!rubric || rubric.version <= minVersion}
              >
                <ChevronLeft className="h-2.5 w-2.5" />
              </Button>
            )}
            <div className="text-xs font-mono px-1.5 min-w-[2.5rem] text-center">
              {rubric && maxVersion !== undefined
                ? `${rubric.version}/${maxVersion}`
                : rubric
                  ? rubric.version
                  : '-'}
            </div>
            {setRubricVersion && (
              <Button
                size="sm"
                variant="ghost"
                className="h-4 w-4 p-0 hover:bg-background/50"
                onClick={handleVersionIncrement}
                disabled={
                  !rubric ||
                  maxVersion === undefined ||
                  rubric.version >= maxVersion
                }
              >
                <ChevronRight className="h-2.5 w-2.5" />
              </Button>
            )}
          </div>
          {showDiff !== undefined && setShowDiff !== undefined && (
            <div className="flex items-center gap-1 pl-2 border-l">
              <Checkbox
                id="load-prev-rubric"
                checked={showDiff}
                onCheckedChange={(v) => setShowDiff(!!v)}
                disabled={!rubric || rubric.version < 2}
              />
              <Label
                htmlFor="load-prev-rubric"
                className="text-xs text-muted-foreground whitespace-nowrap"
              >
                Show diff
              </Label>
            </div>
          )}
        </div>
      </div>
      <div className="border rounded-sm bg-secondary p-2 space-y-2 relative">
        {/* High-level Description */}
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs text-primary">
            High-level Description
          </div>
          <div className="relative overflow-hidden rounded-md border bg-background focus-within:ring-1 focus-within:ring-ring">
            {showDiff && prevRubricRemote && rubric ? (
              <DescriptionInlineDiff
                previous={prevRubricRemote.rubric_text || ''}
                current={rubric.rubric_text || ''}
              />
            ) : (
              <Textarea
                className="h-[40vh] max-h-[50vh] resize-y border-0 p-2 shadow-none focus-visible:ring-0 text-xs font-mono"
                placeholder="Enter a high-level description of what this rubric evaluates..."
                value={rubric?.rubric_text || ''}
                onChange={handleDescriptionChange}
                disabled={isDisabled}
                style={
                  isDisabled ? { opacity: 1, color: 'inherit' } : undefined
                }
              />
            )}
          </div>
        </div>

        {rubric && (
          <div className="space-y-1">
            <button
              type="button"
              className="w-full flex items-center gap-1 text-xs text-muted-foreground hover:text-primary transition-colors"
              onClick={() => setShowAdvanced((v) => !v)}
            >
              {showAdvanced ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              <span className="font-medium">Additional settings</span>
            </button>
            {showAdvanced && (
              <div className="ml-4 border-l p-2 rounded-sm space-y-2">
                {/* Judge model */}
                <div className="flex flex-col">
                  <div className="flex flex-row items-center">
                    <label className="block text-xs font-medium text-muted-foreground mr-2 shrink-0">
                      Judge Model
                    </label>
                    <div className="min-w-0">
                      <Select
                        value={nameJudgeModel(rubric.judge_model)}
                        onValueChange={(value) => {
                          if (!editable) return;
                          const selected = availableJudgeModels?.find(
                            (jm) => nameJudgeModel(jm) === value
                          );
                          updateRubric({
                            judge_model: selected || null,
                          });
                        }}
                        disabled={isDisabled}
                      >
                        <SelectTrigger className="w-full h-7 text-xs border bg-background px-2 font-normal">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="Default" className="text-xs">
                            Default
                          </SelectItem>
                          {availableJudgeModels?.map((jm) => (
                            <SelectItem
                              key={nameJudgeModel(jm)}
                              value={nameJudgeModel(jm)}
                              className="text-xs"
                            >
                              <span className="flex flex-row items-center gap-1">
                                <span className="flex-1">
                                  {nameJudgeModel(jm)}
                                </span>
                                {jm.uses_byok && (
                                  <KeyRound className="h-3 w-3" />
                                )}
                              </span>
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  {rubric.judge_model?.uses_byok && (
                    <div className="text-xs text-muted-foreground mt-1">
                      This model uses your own API key.
                    </div>
                  )}
                </div>
                <div className="flex flex-row items-center">
                  <label className="block text-xs font-medium text-muted-foreground mr-2 shrink-0">
                    Output Schema
                  </label>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 text-xs gap-1.5"
                    onClick={() => {
                      if (!rubric) return;
                      setIsSchemaDialogOpen(true);
                    }}
                    disabled={isDisabled}
                  >
                    <Braces className="h-4 w-4" />
                    Edit
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Save Button */}
        {hasChanges && (
          <div className="flex justify-end gap-2">
            {onCloseWithoutSave && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  // Reset local changes to the latest remote rubric
                  if (remoteRubric) {
                    setLocalRubric(remoteRubric);
                  }
                  // Clear any inline edit state
                  onCloseWithoutSave();
                }}
              >
                Cancel
              </Button>
            )}
            <Button
              size="sm"
              disabled={isDisabled}
              onClick={handleSave}
              className="gap-1.5"
            >
              <Save className="h-4 w-4" />
              Save changes
            </Button>
          </div>
        )}
      </div>
      <OutputSchemaDialog
        open={isSchemaDialogOpen}
        onOpenChange={(open) => setIsSchemaDialogOpen(open)}
        initialSchema={rubric?.output_schema}
        editable={editable}
        onSave={(parsed) => {
          updateRubric({ output_schema: parsed });
          setIsSchemaDialogOpen(false);
        }}
      />
    </div>
  );
}
