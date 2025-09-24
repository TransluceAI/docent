'use client';

import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useState, useEffect, useMemo } from 'react';
import { skipToken } from '@reduxjs/toolkit/query';

import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';

import { type Rubric } from '@/app/store/rubricSlice';

import {
  useGetRubricQuery,
  useGetLatestRubricVersionQuery,
  useGetJudgeModelsQuery,
  rubricApi,
} from '@/app/api/rubricApi';
import { useAppDispatch } from '@/app/store/hooks';
import { cn } from '@/lib/utils';
import { EditorView } from '@uiw/react-codemirror';
import { json as jsonLanguage } from '@codemirror/lang-json';
import { useTheme } from 'next-themes';
import CodeMirror from '@uiw/react-codemirror';
import ModelPicker from '@/components/ModelPicker';
import { Separator } from '@/components/ui/separator';

// Hardcoded fix for types that should be formatted differently, e.g. enum strings for maybe date strings
const fixTypePreview = (property: Record<string, any>) => {
  if (property.type === 'string' && property.enum) {
    return 'enum';
  }
  return property.type;
};

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
        <div className="text-sm whitespace-pre-wrap break-words">{current}</div>
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
      <div className="text-sm whitespace-pre-wrap break-words">{nodes}</div>
    </div>
  );
}

//

interface RubricEditorProps {
  collectionId: string;
  rubricId: string;
  rubricVersion: number | null;
  setRubricVersion?: (version: number) => void;
  showDiff?: boolean;
  setShowDiff?: (show: boolean) => void;
  forceOpenSchema: boolean;
  onSave: (rubric: Rubric, clearLabels: boolean) => void;
  onCloseWithoutSave?: () => void;
  editable: boolean;
  onHasUnsavedChangesUpdated?: (hasChanges: boolean) => void;
  shouldConfirmOnSave?: boolean;
}

export default function RubricEditor({
  collectionId,
  rubricId,
  rubricVersion,
  setRubricVersion,
  showDiff,
  setShowDiff,
  forceOpenSchema,
  onSave,
  onCloseWithoutSave,
  editable,
  onHasUnsavedChangesUpdated,
  shouldConfirmOnSave,
}: RubricEditorProps) {
  const isDisabled = !editable;

  const dispatch = useAppDispatch();

  // Get the remote rubric
  const { data: remoteRubric } = useGetRubricQuery({
    collectionId,
    rubricId,
    version: rubricVersion,
  });

  // Local rubric is for editing
  const [localRubric, setLocalRubric] = useState<Rubric | null>(null);

  const [schemaText, setSchemaText] = useState<string>('');
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [schemaOpen, setSchemaOpen] = useState<boolean>(false);

  const { resolvedTheme } = useTheme();

  const extensions = useMemo(
    () => [jsonLanguage(), EditorView.lineWrapping],
    []
  );

  const preview = useMemo(() => {
    try {
      const parsed = JSON.parse(schemaText || '{}');
      const properties = parsed?.properties || {};
      if (!properties || typeof properties !== 'object') return '';
      const parts: string[] = [];
      for (const key of Object.keys(properties)) {
        const typeStr = fixTypePreview(properties[key]);
        parts.push(`${key}: ${typeStr}`);
      }
      return parts.join('; ');
    } catch {
      return '';
    }
  }, [schemaText]);

  useEffect(() => {
    if (remoteRubric) {
      if (editable) {
        setLocalRubric(remoteRubric);
      }
      setSchemaText(JSON.stringify(remoteRubric.output_schema ?? {}, null, 2));
      setSchemaError(null);
    }
  }, [remoteRubric, editable, setSchemaText, setSchemaError]);

  // Get the latest version number
  const minVersion = 1;
  const { data: maxVersion } = useGetLatestRubricVersionQuery({
    collectionId,
    rubricId,
  });

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
    rubric && rubric.version >= 2 && showDiff
      ? {
          collectionId,
          rubricId,
          version: Math.max(1, rubric.version - 1),
        }
      : skipToken
  );

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

  // Don't clear by default
  const handleSave = (clearLabels: boolean = false) => {
    if (rubric) {
      if (maxVersion === undefined) throw new Error('Latest version not found');

      // Validate JSON syntax before saving
      let parsedSchema;
      try {
        parsedSchema = JSON.parse(schemaText);
      } catch (e) {
        setSchemaError(
          `Invalid JSON: ${e instanceof Error ? e.message : 'Unknown error'}`
        );
        return;
      }

      // Clear any existing error
      setSchemaError(null);

      const updatedRubric = {
        ...{
          ...rubric,
          output_schema: parsedSchema,
        },
        // Possibly skips over some versions, if rubric.version < latestVersion
        // TODO(mengk): consider whether this is ok
        version: maxVersion + 1,
      };
      onSave(updatedRubric, clearLabels);
    }
  };

  // Schema preview

  const schemaPreview = useMemo(() => {
    return preview.split('; ').map((pair, i) => {
      const [k, rest] = pair.split(': ');
      return (
        <span key={i} className="whitespace-nowrap">
          <span className="text-blue-text">{k}</span>
          {`: ${rest}`}
          {i < preview.split('; ').length - 1 ? '; ' : ''}
        </span>
      );
    });
  }, [preview]);

  // Save with confirmation flow
  const [confirmOpen, setConfirmOpen] = useState(false);

  const handleSaveClick = async () => {
    if (!shouldConfirmOnSave || !schemaHasChanges) {
      // Dont clear if schema has not changed
      handleSave(false);
      return;
    }

    setConfirmOpen(true);
  };

  const normalizedRemoteSchema = useMemo(() => {
    return JSON.stringify(remoteRubric?.output_schema ?? {}, null, 2);
  }, [remoteRubric?.output_schema]);

  const schemaHasChanges = useMemo(() => {
    return schemaText !== normalizedRemoteSchema;
  }, [schemaText, normalizedRemoteSchema]);

  const hasChanges = useMemo(() => {
    if (!editable || !rubric || !remoteRubric) return false;
    return (
      rubric.rubric_text !== remoteRubric.rubric_text ||
      JSON.stringify(rubric.judge_model) !==
        JSON.stringify(remoteRubric.judge_model) ||
      schemaHasChanges
    );
  }, [rubric, remoteRubric, editable, schemaHasChanges]);
  useEffect(() => {
    if (onHasUnsavedChangesUpdated) {
      onHasUnsavedChangesUpdated(hasChanges);
    }
  }, [hasChanges, onHasUnsavedChangesUpdated]);

  return (
    <div className="space-y-2">
      <div className="flex justify-between">
        <div className="items-center flex flex-col">
          <div className="text-sm font-semibold">
            {editable ? 'Rubric Editor' : 'Rubric Evaluation'}
          </div>
          <div className="text-xs text-muted-foreground">
            {editable ? 'Specify a rubric.' : 'Explore rubric results.'}
          </div>
        </div>

        <div className="flex flex-wrap grow justify-end items-center gap-x-3">
          {rubric && (
            <ModelPicker
              selectedModel={rubric.judge_model}
              availableModels={availableJudgeModels}
              onChange={(jm) => {
                if (!editable) return;
                updateRubric({ judge_model: jm });
              }}
              className="max-w-28"
              shortenName
            />
          )}
          <Separator orientation="vertical" className="h-5" />

          {showDiff !== undefined && setShowDiff !== undefined && (
            <div className="flex items-center gap-1.5">
              <Checkbox
                id="load-prev-rubric"
                checked={showDiff}
                className="h-3 flex items-center justify-center w-3"
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
          <Separator orientation="vertical" className="h-5" />
          <div>
            <div className="flex items-center gap-0.5 bg-secondary rounded border px-1 py-0.5">
              <Button
                size="sm"
                variant="ghost"
                className="h-4 w-4 p-0 hover:bg-background/50"
                onClick={handleVersionDecrement}
                disabled={!rubric || rubric.version <= minVersion}
              >
                <ChevronLeft className="h-2.5 w-2.5" />
              </Button>
              <div className="text-xs font-mono px-1.5 min-w-[2.5rem] text-center">
                {rubric && maxVersion !== undefined
                  ? `v${rubric.version}/${maxVersion}`
                  : rubric
                    ? rubric.version
                    : '-'}
              </div>
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
            </div>
          </div>
        </div>
      </div>
      <div className="space-y-2 relative">
        {/* Rubric Text */}
        <div className="space-y-1">
          <div className="relative overflow-hidden rounded-md border bg-background focus-within:ring-1 focus-within:ring-ring">
            {showDiff && prevRubricRemote && rubric ? (
              <DescriptionInlineDiff
                previous={prevRubricRemote.rubric_text || ''}
                current={rubric.rubric_text || ''}
              />
            ) : (
              <Textarea
                className={cn(
                  'h-[30vh] max-h-[50vh] resize-y border-0 p-2 shadow-none focus-visible:ring-0 text-sm custom-scrollbar'
                )}
                placeholder="Enter a high-level description of what this rubric evaluates..."
                value={rubric?.rubric_text || ''}
                onChange={handleDescriptionChange}
                disabled={isDisabled}
                style={
                  isDisabled ? { opacity: 1, color: 'inherit' } : undefined
                }
              />
            )}

            {/* Save Button */}
            {hasChanges && (
              <div className="flex absolute bottom-2 right-2 justify-end gap-2">
                {onCloseWithoutSave && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      // Reset local changes to the latest remote rubric
                      if (remoteRubric) {
                        setLocalRubric(remoteRubric);
                        setSchemaText(
                          JSON.stringify(
                            remoteRubric.output_schema ?? {},
                            null,
                            2
                          )
                        );
                        setSchemaError(null);
                      }
                      // Clear any inline edit state
                      onCloseWithoutSave();
                    }}
                  >
                    Cancel
                  </Button>
                )}
                {shouldConfirmOnSave && schemaHasChanges ? (
                  <Popover open={confirmOpen} onOpenChange={setConfirmOpen}>
                    <PopoverTrigger asChild>
                      <Button
                        size="sm"
                        disabled={isDisabled}
                        onClick={handleSaveClick}
                        className="gap-1.5"
                      >
                        Save
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-80 p-3 space-y-2" align="end">
                      <div className="text-sm font-medium">
                        You have existing labels
                      </div>
                      <div className="text-xs text-muted-foreground">
                        Versioning the rubric with a new schema will clear all
                        existing labels.
                      </div>
                      <div className="flex justify-end gap-2 pt-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setConfirmOpen(false)}
                        >
                          Cancel
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => {
                            setConfirmOpen(false);
                            // Clear if schema has changed
                            handleSave(true);
                          }}
                        >
                          Save
                        </Button>
                      </div>
                    </PopoverContent>
                  </Popover>
                ) : (
                  <Button
                    size="sm"
                    disabled={isDisabled}
                    onClick={handleSaveClick}
                    className="gap-1.5"
                  >
                    Save
                  </Button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
      {/* Output Schema Dropdown */}
      <div className="space-y-1">
        <div
          className={cn(
            'rounded-md border bg-background',
            !editable || forceOpenSchema || schemaHasChanges
              ? ''
              : 'hover:bg-accent transition-colors duration-200'
          )}
        >
          {/** Effective open state respects collapse: when collapsed, force closed */}
          {/** Use a computed boolean so arrow, aria-expanded and panel share the same logic */}
          {(() => {
            return (
              <>
                <button
                  type="button"
                  className="w-full flex items-center justify-between px-2 py-1.5 rounded-md disabled:opacity-80"
                  onClick={() => setSchemaOpen(!schemaOpen)}
                  disabled={forceOpenSchema || schemaHasChanges}
                  aria-expanded={
                    schemaOpen || forceOpenSchema || schemaHasChanges
                      ? true
                      : false
                  }
                  aria-controls="schema-content"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <div className="text-xs font-medium border-r pr-2 text-muted-foreground whitespace-nowrap">
                      Output Schema
                    </div>
                    {preview && (
                      <span className="text-xs text-muted-foreground truncate">
                        {/* Color keys differently */}
                        {schemaPreview}
                      </span>
                    )}
                  </div>
                  <ChevronLeft
                    className={
                      'h-3 w-3 transition-transform ' +
                      (schemaOpen || forceOpenSchema || schemaHasChanges
                        ? '-rotate-90'
                        : '')
                    }
                  />
                </button>
                {/* Animated schema content: always mounted for smooth close animation */}
                <div
                  id="schema-content"
                  className={cn(
                    'px-2 pb-2 space-y-2 overflow-hidden transition-all duration-200',
                    schemaOpen || forceOpenSchema || schemaHasChanges
                      ? 'max-h-[40vh] opacity-100'
                      : '!max-h-0 pb-0 opacity-0 pointer-events-none'
                  )}
                >
                  <div className="border rounded-sm max-h-[30vh] overflow-y-auto custom-scrollbar">
                    <CodeMirror
                      value={schemaText}
                      height="auto"
                      // maxHeight="30vh"
                      theme={resolvedTheme === 'dark' ? 'dark' : 'light'}
                      extensions={extensions}
                      onChange={(value) => {
                        setSchemaText(value);
                        if (schemaError) setSchemaError(null);
                      }}
                      basicSetup={{
                        lineNumbers: false,
                        highlightActiveLine: true,
                        foldGutter: false,
                      }}
                      readOnly={!editable}
                    />
                  </div>
                  {schemaError && (
                    <div className="text-xs text-red-text">{schemaError}</div>
                  )}
                </div>
              </>
            );
          })()}
        </div>
      </div>
    </div>
  );
}
