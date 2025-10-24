import React, { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import {
  useCreateLabelMutation,
  useUpdateLabelMutation,
  useDeleteLabelMutation,
  Label,
  useCreateLabelSetMutation,
} from '@/app/api/labelApi';
import { JudgeResultWithCitations } from '@/app/store/rubricSlice';
import { SchemaDefinition } from '@/app/types/schema';
import { toast } from '@/hooks/use-toast';
import posthog from 'posthog-js';
import { Tag, Pencil, X } from 'lucide-react';
import { TextWithCitations } from '@/components/CitationRenderer';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { useParams, usePathname, useRouter } from 'next/navigation';
import { Citation } from '@/app/types/experimentViewerTypes';
import {
  useCitationNavigation,
  CitationNavigationContext,
} from '@/app/dashboard/[collection_id]/rubric/[rubric_id]/NavigateToCitationContext';
import { useLabelSets } from '@/providers/use-label-sets';

interface LabelSetMenuItemsProps {
  usedLabelSetIds: string[];
  onLabelSetSelect: (labelSetId: string) => void;
  schema: SchemaDefinition;
}

const LabelSetMenuItems = ({
  usedLabelSetIds,
  onLabelSetSelect,
  schema,
}: LabelSetMenuItemsProps) => {
  const [isCreatingNew, setIsCreatingNew] = useState(false);
  const [newLabelSetName, setNewLabelSetName] = useState('');

  const { collection_id: collectionId } = useParams<{
    collection_id: string;
  }>();
  const [createLabelSet] = useCreateLabelSetMutation();

  const { labelSets, setLabelSets } = useLabelSets();

  const handleCreateLabelSet = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = newLabelSetName.trim();
    if (!trimmed || !collectionId) return;

    await createLabelSet({
      collectionId,
      name: trimmed,
      label_schema: schema,
    })
      .unwrap()
      .then((result) => {
        onLabelSetSelect(result.label_set_id);
        setNewLabelSetName('');
        setIsCreatingNew(false);

        const newLabelSet = {
          id: result.label_set_id,
          name: trimmed,
          label_schema: schema,
        };
        console.log('newLabelSet', newLabelSet);
        setLabelSets([...labelSets, newLabelSet]);
      })
      .catch((error) => {
        console.error('Failed to create label set:', error);
        toast({
          title: 'Error',
          description: 'Failed to create label set',
          variant: 'destructive',
        });
      });
  };

  return (
    <>
      <div className="max-h-32 overflow-y-auto">
        {labelSets.map((labelSet, idx) => {
          const isUsed = usedLabelSetIds.includes(labelSet.id);
          return (
            <button
              key={labelSet.id}
              onClick={() => !isUsed && onLabelSetSelect(labelSet.id)}
              disabled={isUsed}
              className={cn(
                'w-full text-left px-2 py-1.5 text-xs',
                isUsed
                  ? 'opacity-50 cursor-not-allowed text-muted-foreground'
                  : 'hover:bg-muted cursor-pointer',
                idx === 0 && 'rounded-t-sm'
              )}
            >
              {labelSet.name}
            </button>
          );
        })}
      </div>
      {isCreatingNew ? (
        <form onSubmit={handleCreateLabelSet}>
          <input
            type="text"
            value={newLabelSetName}
            onChange={(e) => setNewLabelSetName(e.target.value)}
            placeholder="Enter label set name..."
            className="w-full text-xs border rounded px-2 py-1"
            autoFocus
            onBlur={() => {
              if (!newLabelSetName.trim()) {
                setIsCreatingNew(false);
              }
            }}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                setNewLabelSetName('');
                setIsCreatingNew(false);
              }
            }}
          />
        </form>
      ) : (
        <button
          onClick={() => setIsCreatingNew(true)}
          className="w-full text-left px-2 py-1.5 text-xs hover:bg-muted rounded-b-sm text-muted-foreground border-t"
        >
          + Create new label set...
        </button>
      )}
    </>
  );
};

const TagButton = React.forwardRef<HTMLButtonElement>(({ ...props }, ref) => {
  return (
    <button
      ref={ref}
      className="inline-flex items-center gap-1 border rounded-xl border-dashed hover:bg-muted/70 text-muted-foreground px-1.5 py-0.5 text-xs"
      {...props}
    >
      <Pencil className="size-3" />
      Label
    </button>
  );
});
TagButton.displayName = 'TagButton';

interface LabelBadgeProps {
  labeledValue?: any;
  labelSetId: string;
  onEdit?: () => void; // used by text/number to open editor
  onClear?: () => void; // clear the label
}

const LabelBadge = React.forwardRef<
  HTMLDivElement,
  LabelBadgeProps & React.HTMLAttributes<HTMLDivElement>
>(({ labeledValue, labelSetId, onEdit, onClear, ...props }, ref) => {
  const { labelSets } = useLabelSets();
  const labelSetName =
    labelSets.find((ls) => ls.id === labelSetId)?.name || labelSetId;

  return (
    <div
      ref={ref}
      className="flex w-fit px-1.5 py-0.5 cursor-pointer border relative bg-green-bg border-green-border rounded-xl group/label"
      {...props}
    >
      <div className="flex items-start gap-1">
        <span className="text-primary text-xs">{labeledValue}</span>
        <Tag className="size-3 mt-0.5 flex-shrink-0 text-green-text" />
        <span className="text-xs font-mono">{labelSetName}</span>
        <X
          className="size-3 mt-0.5 flex-shrink-0 text-green-text cursor-pointer"
          onPointerDown={(e) => {
            e.preventDefault();
            e.stopPropagation();
          }}
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onClear?.();
          }}
        />
      </div>
    </div>
  );
});
LabelBadge.displayName = 'LabelBadge';

interface EnumInputProps {
  propertyKey: string;
  options: string[];
  resultValue: string;
  labelValues?: Record<string, string>;
  usedLabelSetIds: string[];
  onSubmit: (labelSetId: string, value: string) => void;
  onClearLabel: (labelSetId: string) => void;
  schema: SchemaDefinition;
}

const EnumInput = ({
  propertyKey,
  options,
  resultValue,
  labelValues,
  usedLabelSetIds,
  onSubmit,
  onClearLabel,
  schema,
}: EnumInputProps) => {
  const [newSetId, setNewSetId] = useState<string | null>(null);

  const LabelButton = (labelSetId?: string, key?: string) => {
    if (labelSetId && labelValues?.[labelSetId] === undefined) return null;

    const effectiveSetId = labelSetId || newSetId;

    return (
      <DropdownMenu
        key={key}
        onOpenChange={(open) => {
          if (!open) {
            setNewSetId(null);
          }
        }}
      >
        <DropdownMenuTrigger asChild>
          {labelSetId ? (
            <LabelBadge
              labeledValue={labelValues?.[labelSetId]}
              labelSetId={labelSetId}
              onClear={() => onClearLabel(labelSetId)}
            />
          ) : (
            <TagButton />
          )}
        </DropdownMenuTrigger>
        <DropdownMenuContent className="w-56" align="start">
          {effectiveSetId ? (
            <DropdownMenuRadioGroup
              value={labelValues?.[effectiveSetId]}
              onValueChange={(value) => {
                onSubmit(effectiveSetId, value);
                setNewSetId(null);
              }}
            >
              {options.map((value) => (
                <DropdownMenuRadioItem
                  className="text-xs"
                  key={value}
                  value={value}
                >
                  {value}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          ) : (
            <LabelSetMenuItems
              usedLabelSetIds={usedLabelSetIds}
              onLabelSetSelect={setNewSetId}
              schema={schema}
            />
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    );
  };

  return (
    <div className="gap-1 text-xs flex items-center flex-wrap">
      <label className="font-semibold">{propertyKey}: </label>
      <span className="mr-1">{resultValue}</span>
      {usedLabelSetIds.map((labelSetId) => LabelButton(labelSetId, labelSetId))}
      {LabelButton(undefined, 'new')}
    </div>
  );
};

interface BooleanInputProps {
  propertyKey: string;
  resultValue: boolean;
  labelValues?: Record<string, boolean>;
  usedLabelSetIds: string[];
  onSubmit: (labelSetId: string, value: boolean) => void;
  onClearLabel?: (labelSetId: string) => void;
  schema: SchemaDefinition;
}

const BooleanInput = ({
  propertyKey,
  resultValue,
  labelValues,
  usedLabelSetIds,
  onSubmit,
  onClearLabel,
  schema,
}: BooleanInputProps) => {
  const [newSetId, setNewSetId] = useState<string | null>(null);

  const LabelButton = (labelSetId?: string, key?: string) => {
    if (labelSetId && labelValues?.[labelSetId] === undefined) return null;

    const effectiveSetId = labelSetId || newSetId;

    return (
      <DropdownMenu
        key={key}
        onOpenChange={(open) => {
          if (!open) {
            setNewSetId(null);
          }
        }}
      >
        <DropdownMenuTrigger asChild>
          {labelSetId ? (
            <LabelBadge
              labeledValue={String(labelValues?.[labelSetId])}
              labelSetId={labelSetId}
              onClear={() => onClearLabel?.(labelSetId)}
            />
          ) : (
            <TagButton />
          )}
        </DropdownMenuTrigger>
        <DropdownMenuContent className="w-56">
          {effectiveSetId ? (
            <DropdownMenuRadioGroup
              value={String(labelValues?.[effectiveSetId] ?? resultValue)}
              onValueChange={(val) => {
                onSubmit(effectiveSetId, val === 'true');
                setNewSetId(null);
              }}
            >
              {['true', 'false'].map((value) => (
                <DropdownMenuRadioItem
                  className="text-xs"
                  key={value}
                  value={value}
                >
                  {value}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          ) : (
            <LabelSetMenuItems
              usedLabelSetIds={usedLabelSetIds}
              onLabelSetSelect={setNewSetId}
              schema={schema}
            />
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    );
  };

  return (
    <div className="gap-1 text-xs flex items-center">
      <label className="font-semibold">{propertyKey}: </label>
      <div className="flex items-center gap-1">
        <span>{String(resultValue)}</span>
        {usedLabelSetIds.map((labelSetId) =>
          LabelButton(labelSetId, labelSetId)
        )}
        {LabelButton(undefined, 'new')}
      </div>
    </div>
  );
};

interface NumberInputProps {
  propertyKey: string;
  resultValue: number;
  labelValues?: Record<string, number>;
  maximum: number;
  minimum: number;
  usedLabelSetIds: string[];
  onSubmit: (labelSetId: string, value: number) => void;
  onClearLabel?: (labelSetId: string) => void;
  schema: SchemaDefinition;
}

const NumberInput = ({
  propertyKey,
  resultValue,
  labelValues,
  maximum,
  minimum,
  usedLabelSetIds,
  onSubmit,
  onClearLabel,
  schema,
}: NumberInputProps) => {
  const [openPopover, setOpenPopover] = useState<string | null>(null);
  const [newSetId, setNewSetId] = useState<string | null>(null);

  // If we have a label, cast the values to strings to use as local state
  const labelAsStrings = labelValues
    ? Object.fromEntries(
        Object.entries(labelValues).map(([key, value]) => [key, String(value)])
      )
    : {};

  const [localValue, _setLocalValue] =
    useState<Record<string, string>>(labelAsStrings);

  const setLocalValue = (labelSetId: string, value: string) => {
    _setLocalValue((prev) => ({ ...prev, [labelSetId]: value }));
  };

  // Sync local state when labelValues updates from server
  useEffect(() => {
    const updated = labelValues
      ? Object.fromEntries(
          Object.entries(labelValues).map(([key, value]) => [
            key,
            String(value),
          ])
        )
      : {};
    _setLocalValue(updated);
  }, [labelValues]);

  // Helper to check whether the entered value is a valid number
  const submit = (labelSetId: string) => {
    const parsed = parseInt(localValue[labelSetId], 10);
    if (!isNaN(parsed)) {
      const clamped = Math.min(maximum, Math.max(minimum, parsed));
      onSubmit(labelSetId, clamped);
    }
  };

  const LabelButton = (labelSetId?: string, key?: string) => {
    if (labelSetId && labelValues?.[labelSetId] === undefined) return null;

    const effectiveSetId = labelSetId || newSetId;
    const popoverKey = key ?? labelSetId ?? '__new__';

    return (
      <Popover
        key={popoverKey}
        open={openPopover === popoverKey}
        onOpenChange={(open) => {
          setOpenPopover(open ? popoverKey : null);
          if (!open) {
            setNewSetId(null);
          }
        }}
      >
        <PopoverTrigger asChild>
          {labelSetId ? (
            <LabelBadge
              labeledValue={String(labelValues?.[labelSetId])}
              labelSetId={labelSetId}
              onClear={() => onClearLabel?.(labelSetId)}
              onEdit={() => setOpenPopover(labelSetId)}
            />
          ) : (
            <TagButton />
          )}
        </PopoverTrigger>
        <PopoverContent className="w-64 p-1" align="start">
          {effectiveSetId ? (
            <form
              className="flex flex-col gap-2 p-1"
              onSubmit={(e) => {
                e.preventDefault();
                submit(effectiveSetId);
                setOpenPopover(null);
                setNewSetId(null);
              }}
            >
              <input
                type="number"
                value={localValue[effectiveSetId] ?? ''}
                onChange={(e) => setLocalValue(effectiveSetId, e.target.value)}
                className="border rounded px-2 py-1 text-xs"
                max={maximum}
                min={minimum}
              />
              <Button size="sm" type="submit">
                Save
              </Button>
            </form>
          ) : (
            <LabelSetMenuItems
              usedLabelSetIds={usedLabelSetIds}
              onLabelSetSelect={setNewSetId}
              schema={schema}
            />
          )}
        </PopoverContent>
      </Popover>
    );
  };

  return (
    <div className="space-y-2">
      <div className="text-xs">
        <span className="font-semibold shrink-0">{propertyKey}: </span>{' '}
        <span>{String(resultValue)}</span>
      </div>
      <div className="flex items-center gap-1">
        {usedLabelSetIds.map((labelSetId) =>
          LabelButton(labelSetId, labelSetId)
        )}
        {LabelButton(undefined, 'new')}
      </div>
    </div>
  );
};

interface TextWithCitationsInputProps {
  judgeResult: JudgeResultWithCitations;
  labelValues?: Record<string, string>;
  propertyKey: string;
  placeholder: string;
  usedLabelSetIds: string[];
  onSubmit: (labelSetId: string, value: string) => void;
  onClearLabel?: (labelSetId: string) => void;
  schema: SchemaDefinition;
}

const TextWithCitationsInput = ({
  judgeResult,
  labelValues,
  propertyKey,
  placeholder,
  usedLabelSetIds,
  onSubmit,
  onClearLabel,
  schema,
}: TextWithCitationsInputProps) => {
  const { collection_id: collectionId } = useParams<{
    collection_id: string;
  }>();
  const pathname = usePathname();
  const router = useRouter();

  const citationNav = useCitationNavigation();

  //***************
  // Labels state *
  //***************

  const [value, _setValue] = useState<Record<string, string>>(
    labelValues ?? {}
  );
  const setValue = (labelSetId: string, value: string) => {
    _setValue((prev) => ({ ...prev, [labelSetId]: value }));
  };

  // Sync local state when labelValues updates from server
  useEffect(() => {
    _setValue(labelValues ?? {});
  }, [labelValues]);

  //*********************
  // Result value state *
  //*********************

  const citations = judgeResult.output[propertyKey]?.citations || [];
  const resultValue = judgeResult.output[propertyKey]?.text || '';

  const navigateToCitation = React.useCallback(
    ({ citation }: { citation: Citation }) => {
      const url = `/dashboard/${collectionId}/rubric/${judgeResult.rubric_id}/agent_run/${judgeResult.agent_run_id}/result/${judgeResult.id}`;
      const isOnTargetPage = pathname === url;

      if (!isOnTargetPage) {
        citationNav?.prepareForNavigation?.();
        router.push(url, { scroll: false } as any);
      }

      citationNav?.navigateToCitation?.({
        citation,
        source: 'judge_result',
      });
    },
    [
      citationNav,
      collectionId,
      judgeResult.id,
      judgeResult.rubric_id,
      judgeResult.agent_run_id,
      pathname,
      router,
    ]
  );

  const navigateToAgentRun = () => {
    router.push(
      `/dashboard/${collectionId}/rubric/${judgeResult.rubric_id}/agent_run/${judgeResult.agent_run_id}`
    );
  };

  const citationNavValue = React.useMemo(
    () => ({
      registerHandler: citationNav?.registerHandler ?? (() => {}),
      navigateToCitation,
      prepareForNavigation: citationNav?.prepareForNavigation ?? (() => {}),
    }),
    [citationNav, navigateToCitation]
  );

  //****************
  // Popover state *
  //****************

  // Auto-grow textarea similar to chat InputArea
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);
  const adjustHeight = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight + 2}px`;
  };

  const [openPopover, setOpenPopover] = useState<string | null>(null);
  const [newSetId, setNewSetId] = useState<string | null>(null);

  useEffect(() => {
    if (openPopover) {
      // Use requestAnimationFrame to ensure DOM has updated
      requestAnimationFrame(() => {
        adjustHeight();
      });
    }
  }, [openPopover]);

  const AddLabelButton = (labelSetId?: string, key?: string) => {
    if (labelSetId && labelValues?.[labelSetId] === undefined) return null;

    // Determine which labelSetId to use for the form
    const effectiveSetId = labelSetId || newSetId;

    // Use a unique key for the "add new label" button
    const popoverKey = key ?? labelSetId ?? '__new__';

    return (
      <Popover
        key={popoverKey}
        open={openPopover === popoverKey}
        onOpenChange={(open) => {
          setOpenPopover(open ? popoverKey : null);
          if (!open) {
            setNewSetId(null);
          }
        }}
      >
        <PopoverTrigger asChild>
          {labelSetId ? (
            <LabelBadge
              labeledValue={labelValues?.[labelSetId]}
              labelSetId={labelSetId}
              onClear={() => onClearLabel?.(labelSetId)}
              onEdit={() => setOpenPopover(labelSetId)}
            />
          ) : (
            <TagButton />
          )}
        </PopoverTrigger>
        <PopoverContent
          className={cn(' p-1', effectiveSetId ? 'w-96' : 'w-56')}
          align="start"
        >
          {effectiveSetId ? (
            <form
              className="flex flex-col p-1 gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                onSubmit(effectiveSetId, value[effectiveSetId] || '');
                setOpenPopover(null);
                setNewSetId(null);
              }}
            >
              <Textarea
                ref={textareaRef}
                value={value[effectiveSetId] || ''}
                placeholder={placeholder}
                onChange={(e) => {
                  setValue(effectiveSetId, e.target.value);
                  adjustHeight();
                }}
                className="min-h-[24px] max-h-[20vh] text-xs resize-vertical"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    onSubmit(effectiveSetId, value[effectiveSetId] || '');
                    setOpenPopover(null);
                    setNewSetId(null);
                  }
                }}
              />

              <Button size="sm" type="submit">
                Save
              </Button>
            </form>
          ) : (
            <LabelSetMenuItems
              usedLabelSetIds={usedLabelSetIds}
              onLabelSetSelect={setNewSetId}
              schema={schema}
            />
          )}
        </PopoverContent>
      </Popover>
    );
  };

  return (
    <div className="space-y-2">
      <div
        className="text-xs cursor-pointer group"
        onClick={navigateToAgentRun}
      >
        <span className="font-semibold shrink-0 group-hover:text-muted-foreground transition-colors">
          {propertyKey}:{' '}
        </span>{' '}
        <CitationNavigationContext.Provider value={citationNavValue}>
          <TextWithCitations text={resultValue} citations={citations} />
        </CitationNavigationContext.Provider>
      </div>
      <div className="flex items-center gap-1 flex-wrap">
        {usedLabelSetIds.map((labelSetId) =>
          AddLabelButton(labelSetId, labelSetId)
        )}
        {AddLabelButton(undefined, 'new')}
      </div>
    </div>
  );
};

/**
 * Normalizes label state by extracting text from citation objects.
 * If a property is defined as a string in the schema but the value is an object
 * with a 'text' property (e.g., {text: string, citations: Citation[]}),
 * this function extracts just the text value.
 */
const normalizeLabelsWithCitations = (
  labelState: Record<string, any>,
  schema?: SchemaDefinition
): Record<string, any> => {
  if (!schema) return labelState;

  return Object.fromEntries(
    Object.entries(labelState).map(([key, value]) => {
      const property = schema.properties?.[key];

      // If the property is a string, and the value is an object with a text property, pull that out
      if (
        property &&
        property.type === 'string' &&
        value &&
        typeof value === 'object' &&
        'text' in (value as Record<string, any>)
      ) {
        return [key, (value as { text: string }).text];
      }

      return [key, value];
    })
  );
};

//*****************
// Main component *
//*****************

interface JudgeResultCardProps {
  schema: SchemaDefinition;
  judgeResult: JudgeResultWithCitations;
  labels: Label[];
  agentRunId: string;
}

const JudgeResultCard = ({
  judgeResult,
  schema,
  labels,
  agentRunId,
}: JudgeResultCardProps) => {
  const { collection_id: collectionId } = useParams<{
    collection_id: string;
  }>();
  const [createLabel] = useCreateLabelMutation();

  const normalizedJudgeRunLabels = Object.fromEntries(
    labels.map((label) => [
      label.label_set_id,
      normalizeLabelsWithCitations(label.label_value, schema),
    ])
  );

  const [formState, setFormState] = useState(normalizedJudgeRunLabels);

  // Sync local form state when the server label changes (e.g., after async fetch)
  useEffect(() => {
    setFormState(normalizedJudgeRunLabels);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentRunId, labels]);

  const [updateLabel] = useUpdateLabelMutation();
  const [deleteLabel] = useDeleteLabelMutation();

  // Helper to get usedLabelSetIds that already have labels for a specific field
  const getUsedSetIdsForField = (fieldKey: string): string[] => {
    return labels
      .filter((label) => fieldKey in label.label_value)
      .map((label) => label.label_set_id);
  };

  // Helper to create a map from usedLabelSetIds to values for a given key
  const createLabelValues = (key: string) => {
    return Object.fromEntries(
      Object.entries(formState).map(([labelSetId, props]) => [
        labelSetId,
        props[key],
      ])
    );
  };

  const clearLabelField = async (labelSetId: string, key: string) => {
    // Find the label for this labelSetId
    const labelForSet = labels.find((l) => l.label_set_id === labelSetId);
    if (!labelForSet || !labelForSet.id || !collectionId) return;

    // Compute the new state
    const { [key]: _removed, ...currentFields } = formState[labelSetId] || {};

    // Update local form state
    setFormState((prev) => {
      const { [key]: _, ...rest } = prev[labelSetId] || {};
      return { ...prev, [labelSetId]: rest };
    });

    try {
      // If no fields left, delete the entire label
      if (Object.keys(currentFields).length === 0) {
        await deleteLabel({
          collectionId,
          labelId: labelForSet.id,
        }).unwrap();
      } else {
        // Otherwise update the label
        await updateLabel({
          collectionId,
          labelId: labelForSet.id,
          label_value: currentFields,
        }).unwrap();
      }
    } catch (error: any) {
      console.error('Failed to clear label field:', error.data || error);
      toast({
        title: 'Error',
        description: 'Failed to clear label field',
        variant: 'destructive',
      });
    }
  };

  const save = async (labelSetId: string, key: string, value: any) => {
    if (!collectionId) return;

    // Update local state
    setFormState((prev) => ({
      ...prev,
      [labelSetId]: {
        ...prev[labelSetId],
        [key]: value,
      },
    }));

    // Check whether the label exists to either update or create
    const existingLabel = labels.find((l) => l.label_set_id === labelSetId);

    try {
      const labelData = {
        ...formState[labelSetId],
        [key]: value,
      };

      if (!existingLabel) {
        // Create new label
        await createLabel({
          collectionId,
          label: {
            label_set_id: labelSetId,
            label_value: labelData,
            agent_run_id: agentRunId,
          },
        }).unwrap();
      } else if (existingLabel && existingLabel.id) {
        // Update existing label
        await updateLabel({
          collectionId,
          labelId: existingLabel.id,
          label_value: labelData,
        }).unwrap();
      } else {
        throw new Error('No existing label found');
      }

      posthog.capture('label_form_submitted', {
        num_fields_filled: Object.keys(labelData).length,
        agent_run_id: agentRunId,
        label_set_id: labelSetId,
      });
    } catch (error: any) {
      console.error('Label operation failed:', error.data || error);
      toast({
        title: 'Error',
        description: `Failed to ${existingLabel ? 'update' : 'create'} label`,
        variant: 'destructive',
      });
    }
  };

  return (
    <div className="space-y-1">
      {Object.entries(schema.properties).map(([key, property]) => {
        if (property.type === 'string' && 'citations' in property) {
          return (
            <TextWithCitationsInput
              key={key}
              judgeResult={judgeResult}
              labelValues={createLabelValues(key)}
              propertyKey={key}
              placeholder={'Enter an updated explanation.'}
              usedLabelSetIds={getUsedSetIdsForField(key)}
              onSubmit={(labelSetId, value) => save(labelSetId, key, value)}
              onClearLabel={(labelSetId) => clearLabelField(labelSetId, key)}
              schema={schema}
            />
          );
        }

        if (property.type === 'string' && 'enum' in property) {
          return (
            <EnumInput
              key={key}
              propertyKey={key}
              options={property.enum}
              resultValue={judgeResult.output[key]}
              labelValues={createLabelValues(key)}
              usedLabelSetIds={getUsedSetIdsForField(key)}
              onSubmit={(labelSetId, value) => save(labelSetId, key, value)}
              onClearLabel={(labelSetId) => clearLabelField(labelSetId, key)}
              schema={schema}
            />
          );
        }

        if (property.type === 'boolean') {
          return (
            <BooleanInput
              key={key}
              propertyKey={key}
              resultValue={judgeResult.output[key] as boolean}
              labelValues={createLabelValues(key)}
              usedLabelSetIds={getUsedSetIdsForField(key)}
              onSubmit={(labelSetId, value) => save(labelSetId, key, value)}
              onClearLabel={(labelSetId) => clearLabelField(labelSetId, key)}
              schema={schema}
            />
          );
        }

        if (
          property.type === 'integer' &&
          'maximum' in property &&
          'minimum' in property
        ) {
          return (
            <NumberInput
              key={key}
              propertyKey={key}
              resultValue={judgeResult.output[key] as number}
              labelValues={createLabelValues(key)}
              usedLabelSetIds={getUsedSetIdsForField(key)}
              maximum={property.maximum}
              minimum={property.minimum}
              onSubmit={(labelSetId, value) => save(labelSetId, key, value)}
              onClearLabel={(labelSetId) => clearLabelField(labelSetId, key)}
              schema={schema}
            />
          );
        }

        return null;
      })}
    </div>
  );
};

export default JudgeResultCard;
