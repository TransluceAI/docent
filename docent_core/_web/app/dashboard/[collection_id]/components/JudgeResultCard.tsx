import React, { useEffect, useState } from 'react';
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
import { Tag, Pencil, X, ExternalLink } from 'lucide-react';
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
import { cn } from '@/lib/utils';
import LabelSetsDialog from './LabelSetsDialog';

interface LabelSetMenuItemsProps {
  onLabelSetCreated: (labelSetId: string) => void;
  schema: SchemaDefinition;
}

const LabelSetMenuItems = ({
  onLabelSetCreated,
  schema,
}: LabelSetMenuItemsProps) => {
  const [newLabelSetName, setNewLabelSetName] = useState('');
  const [showLabelSetsDialog, setShowLabelSetsDialog] = useState(false);

  const { collection_id: collectionId } = useParams<{
    collection_id: string;
  }>();
  const [createLabelSet] = useCreateLabelSetMutation();
  const { setActiveLabelSet } = useLabelSets();

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
        const newLabelSet = {
          id: result.label_set_id,
          name: trimmed,
          label_schema: schema,
        };
        setActiveLabelSet(newLabelSet);
        onLabelSetCreated(result.label_set_id);
        setNewLabelSetName('');
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

  const handleImportLabelSet = (labelSet: any) => {
    setActiveLabelSet(labelSet);
    onLabelSetCreated(labelSet.id);
    setShowLabelSetsDialog(false);
  };

  return (
    <>
      <div className="space-y-1">
        <button
          type="button"
          onClick={() => setShowLabelSetsDialog(true)}
          className="w-full text-xs flex gap-2 items-center hover:bg-muted rounded px-2 py-2"
        >
          Select an existing label set
          <ExternalLink className="size-3" />
        </button>
        <form onSubmit={handleCreateLabelSet}>
          <input
            type="text"
            value={newLabelSetName}
            onChange={(e) => setNewLabelSetName(e.target.value)}
            placeholder="Or create new label set..."
            className="w-full text-xs border rounded px-2 py-1"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                setNewLabelSetName('');
              }
            }}
          />
        </form>
      </div>
      <LabelSetsDialog
        open={showLabelSetsDialog}
        onOpenChange={setShowLabelSetsDialog}
        onImportLabelSet={handleImportLabelSet}
        currentRubricSchema={schema}
      />
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
  const { activeLabelSet } = useLabelSets();
  const labelSetName =
    activeLabelSet?.id === labelSetId ? activeLabelSet.name : labelSetId;

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
  labelValue?: string;
  onSubmit: (labelSetId: string, value: string) => void;
  onClearLabel: (labelSetId: string) => void;
  schema: SchemaDefinition;
  isRequiredWarning?: boolean;
}

const EnumInput = ({
  propertyKey,
  options,
  resultValue,
  labelValue,
  onSubmit,
  onClearLabel,
  schema,
  isRequiredWarning = false,
}: EnumInputProps) => {
  const hasLabel = labelValue !== undefined;
  const { activeLabelSetId } = useLabelSets();
  const [tempLabelSetId, setTempLabelSetId] = useState<string | null>(null);
  const effectiveLabelSetId = activeLabelSetId || tempLabelSetId;

  return (
    <div className="gap-1 text-xs flex items-center flex-wrap">
      <label
        className={`font-semibold ${isRequiredWarning ? 'text-red-500' : ''}`}
      >
        {propertyKey}:
      </label>
      <span className="mr-1">{resultValue}</span>
      <DropdownMenu
        onOpenChange={(open) => {
          if (!open) setTempLabelSetId(null);
        }}
      >
        <DropdownMenuTrigger asChild>
          {hasLabel && activeLabelSetId ? (
            <LabelBadge
              labeledValue={labelValue}
              labelSetId={activeLabelSetId}
              onClear={() => onClearLabel(activeLabelSetId)}
            />
          ) : (
            <TagButton />
          )}
        </DropdownMenuTrigger>
        <DropdownMenuContent className="w-56" align="start">
          {effectiveLabelSetId ? (
            <DropdownMenuRadioGroup
              value={labelValue}
              onValueChange={(value) => {
                onSubmit(effectiveLabelSetId, value);
                setTempLabelSetId(null);
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
              onLabelSetCreated={setTempLabelSetId}
              schema={schema}
            />
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
};

interface BooleanInputProps {
  propertyKey: string;
  resultValue: boolean;
  labelValue?: boolean;
  onSubmit: (labelSetId: string, value: boolean) => void;
  onClearLabel?: (labelSetId: string) => void;
  schema: SchemaDefinition;
  isRequiredWarning?: boolean;
}

const BooleanInput = ({
  propertyKey,
  resultValue,
  labelValue,
  onSubmit,
  onClearLabel,
  schema,
  isRequiredWarning = false,
}: BooleanInputProps) => {
  const hasLabel = labelValue !== undefined;
  const { activeLabelSetId } = useLabelSets();
  const [tempLabelSetId, setTempLabelSetId] = useState<string | null>(null);
  const effectiveLabelSetId = activeLabelSetId || tempLabelSetId;

  return (
    <div className="gap-1 text-xs flex items-center">
      <label
        className={`font-semibold ${isRequiredWarning ? 'text-red-500' : ''}`}
      >
        {propertyKey}:
      </label>
      <div className="flex items-center gap-1">
        <span>{String(resultValue)}</span>
        <DropdownMenu
          onOpenChange={(open) => {
            if (!open) setTempLabelSetId(null);
          }}
        >
          <DropdownMenuTrigger asChild>
            {hasLabel && activeLabelSetId ? (
              <LabelBadge
                labeledValue={String(labelValue)}
                labelSetId={activeLabelSetId}
                onClear={() => onClearLabel?.(activeLabelSetId)}
              />
            ) : (
              <TagButton />
            )}
          </DropdownMenuTrigger>
          <DropdownMenuContent className="w-56">
            {effectiveLabelSetId ? (
              <DropdownMenuRadioGroup
                value={String(labelValue ?? resultValue)}
                onValueChange={(val) => {
                  onSubmit(effectiveLabelSetId, val === 'true');
                  setTempLabelSetId(null);
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
                onLabelSetCreated={setTempLabelSetId}
                schema={schema}
              />
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
};

interface NumberInputProps {
  propertyKey: string;
  resultValue: number;
  labelValue?: number;
  maximum: number;
  minimum: number;
  onSubmit: (labelSetId: string, value: number) => void;
  onClearLabel?: (labelSetId: string) => void;
  schema: SchemaDefinition;
  isRequiredWarning?: boolean;
}

const NumberInput = ({
  propertyKey,
  resultValue,
  labelValue,
  maximum,
  minimum,
  onSubmit,
  onClearLabel,
  schema,
  isRequiredWarning = false,
}: NumberInputProps) => {
  const { activeLabelSetId } = useLabelSets();
  const [openPopover, setOpenPopover] = useState(false);
  const [localValue, setLocalValue] = useState(String(labelValue ?? ''));
  const [tempLabelSetId, setTempLabelSetId] = useState<string | null>(null);
  const effectiveLabelSetId = activeLabelSetId || tempLabelSetId;

  // Sync local state when labelValue updates from server
  useEffect(() => {
    setLocalValue(labelValue !== undefined ? String(labelValue) : '');
  }, [labelValue]);

  // Helper to check whether the entered value is a valid number
  const submit = () => {
    if (!effectiveLabelSetId) return;
    const parsed = parseInt(localValue, 10);
    if (!isNaN(parsed)) {
      const clamped = Math.min(maximum, Math.max(minimum, parsed));
      onSubmit(effectiveLabelSetId, clamped);
      setTempLabelSetId(null);
    }
  };

  const hasLabel = labelValue !== undefined;

  return (
    <div className="space-y-2">
      <div className="text-xs">
        <span
          className={`font-semibold shrink-0 ${isRequiredWarning ? 'text-red-500' : ''}`}
        >
          {propertyKey}:
        </span>{' '}
        <span>{String(resultValue)}</span>
      </div>
      <div className="flex items-center gap-1">
        <Popover
          open={openPopover}
          onOpenChange={(open) => {
            setOpenPopover(open);
            if (!open) setTempLabelSetId(null);
          }}
        >
          <PopoverTrigger asChild>
            {hasLabel && activeLabelSetId ? (
              <LabelBadge
                labeledValue={String(labelValue)}
                labelSetId={activeLabelSetId}
                onClear={() => onClearLabel?.(activeLabelSetId)}
                onEdit={() => setOpenPopover(true)}
              />
            ) : (
              <TagButton />
            )}
          </PopoverTrigger>
          <PopoverContent className="w-64 p-1" align="start">
            {effectiveLabelSetId ? (
              <form
                className="flex flex-col gap-2 p-1"
                onSubmit={(e) => {
                  e.preventDefault();
                  submit();
                  setOpenPopover(false);
                }}
              >
                <input
                  type="number"
                  value={localValue}
                  onChange={(e) => setLocalValue(e.target.value)}
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
                onLabelSetCreated={(id) => {
                  setTempLabelSetId(id);
                }}
                schema={schema}
              />
            )}
          </PopoverContent>
        </Popover>
      </div>
    </div>
  );
};

interface TextWithCitationsInputProps {
  judgeResult: JudgeResultWithCitations;
  labelValue?: string;
  propertyKey: string;
  placeholder: string;
  onSubmit: (labelSetId: string, value: string) => void;
  onClearLabel?: (labelSetId: string) => void;
  schema: SchemaDefinition;
  isRequiredWarning?: boolean;
}

const TextWithCitationsInput = ({
  judgeResult,
  labelValue,
  propertyKey,
  placeholder,
  onSubmit,
  onClearLabel,
  schema,
  isRequiredWarning = false,
}: TextWithCitationsInputProps) => {
  const { collection_id: collectionId } = useParams<{
    collection_id: string;
  }>();
  const { activeLabelSetId } = useLabelSets();
  const pathname = usePathname();
  const router = useRouter();

  const citationNav = useCitationNavigation();

  //***************
  // Labels state *
  //***************

  const [value, setValue] = useState<string>(labelValue ?? '');

  // Sync local state when labelValue updates from server
  useEffect(() => {
    setValue(labelValue ?? '');
  }, [labelValue]);

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

  const [openPopover, setOpenPopover] = useState(false);
  const [tempLabelSetId, setTempLabelSetId] = useState<string | null>(null);
  const effectiveLabelSetId = activeLabelSetId || tempLabelSetId;

  useEffect(() => {
    if (openPopover) {
      // Use requestAnimationFrame to ensure DOM has updated
      requestAnimationFrame(() => {
        adjustHeight();
      });
    }
  }, [openPopover]);

  const hasLabel = labelValue !== undefined;

  return (
    <div className="space-y-2">
      <div
        className="text-xs cursor-pointer group"
        onClick={navigateToAgentRun}
      >
        <span className={'font-semibold shrink-0'}>
          {propertyKey}{' '}
          <span
            className={cn(
              'font-normal',
              isRequiredWarning ? 'text-red-500' : ''
            )}
          >
            {isRequiredWarning ? '(required)' : ''}
          </span>
          :
        </span>{' '}
        <CitationNavigationContext.Provider value={citationNavValue}>
          <TextWithCitations text={resultValue} citations={citations} />
        </CitationNavigationContext.Provider>
      </div>
      <div className="flex items-center gap-1 flex-wrap">
        <Popover
          open={openPopover}
          onOpenChange={(open) => {
            setOpenPopover(open);
            if (!open) setTempLabelSetId(null);
          }}
        >
          <PopoverTrigger asChild>
            {hasLabel && activeLabelSetId ? (
              <LabelBadge
                labeledValue={labelValue}
                labelSetId={activeLabelSetId}
                onClear={() => onClearLabel?.(activeLabelSetId)}
                onEdit={() => setOpenPopover(true)}
              />
            ) : (
              <TagButton />
            )}
          </PopoverTrigger>
          <PopoverContent className="w-96 p-1" align="start">
            {effectiveLabelSetId ? (
              <form
                className="flex flex-col p-1 gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  onSubmit(effectiveLabelSetId, value);
                  setOpenPopover(false);
                  setTempLabelSetId(null);
                }}
              >
                <Textarea
                  ref={textareaRef}
                  value={value}
                  placeholder={placeholder}
                  onChange={(e) => {
                    setValue(e.target.value);
                    adjustHeight();
                  }}
                  className="min-h-[24px] max-h-[20vh] text-xs resize-vertical"
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      onSubmit(effectiveLabelSetId, value);
                      setOpenPopover(false);
                      setTempLabelSetId(null);
                    }
                  }}
                />

                <Button size="sm" type="submit">
                  Save
                </Button>
              </form>
            ) : (
              <LabelSetMenuItems
                onLabelSetCreated={(id) => {
                  setTempLabelSetId(id);
                }}
                schema={schema}
              />
            )}
          </PopoverContent>
        </Popover>
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
  activeLabelSetId: string | null;
}

const JudgeResultCard = ({
  judgeResult,
  schema,
  labels,
  agentRunId,
  activeLabelSetId,
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

  // Helper to get the label value for a specific field from the active label set
  const getLabelValue = (key: string) => {
    if (!activeLabelSetId || !formState[activeLabelSetId]) return undefined;
    return formState[activeLabelSetId][key];
  };

  const clearLabelField = async (key: string) => {
    if (!activeLabelSetId) return;
    const labelSetId = activeLabelSetId;
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
          agentRunId,
        }).unwrap();
      } else {
        // Otherwise update the label
        await updateLabel({
          collectionId,
          labelId: labelForSet.id,
          label_value: currentFields,
          agentRunId,
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

  // Helper to check if labeling has started (any fields are filled for active label set)
  const hasStartedLabeling = () => {
    if (!activeLabelSetId || !formState[activeLabelSetId]) return false;
    return Object.keys(formState[activeLabelSetId]).length > 0;
  };

  // Helper to check if a field is required and unfilled
  const isRequiredAndUnfilled = (key: string) => {
    const isRequired = schema.required?.includes(key);
    const isFilled = getLabelValue(key) !== undefined;
    return isRequired && !isFilled && hasStartedLabeling();
  };

  const save = async (key: string, value: any) => {
    if (!collectionId || !activeLabelSetId) return;
    const labelSetId = activeLabelSetId;

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
          agentRunId,
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
              labelValue={getLabelValue(key)}
              propertyKey={key}
              placeholder={'Enter an updated explanation.'}
              onSubmit={(labelSetId, value) => save(key, value)}
              onClearLabel={() => clearLabelField(key)}
              schema={schema}
              isRequiredWarning={isRequiredAndUnfilled(key)}
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
              labelValue={getLabelValue(key)}
              onSubmit={(labelSetId, value) => save(key, value)}
              onClearLabel={() => clearLabelField(key)}
              schema={schema}
              isRequiredWarning={isRequiredAndUnfilled(key)}
            />
          );
        }

        if (property.type === 'boolean') {
          return (
            <BooleanInput
              key={key}
              propertyKey={key}
              resultValue={judgeResult.output[key] as boolean}
              labelValue={getLabelValue(key)}
              onSubmit={(labelSetId, value) => save(key, value)}
              onClearLabel={() => clearLabelField(key)}
              schema={schema}
              isRequiredWarning={isRequiredAndUnfilled(key)}
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
              labelValue={getLabelValue(key)}
              maximum={property.maximum}
              minimum={property.minimum}
              onSubmit={(labelSetId, value) => save(key, value)}
              onClearLabel={() => clearLabelField(key)}
              schema={schema}
              isRequiredWarning={isRequiredAndUnfilled(key)}
            />
          );
        }

        return null;
      })}
    </div>
  );
};

export default JudgeResultCard;
