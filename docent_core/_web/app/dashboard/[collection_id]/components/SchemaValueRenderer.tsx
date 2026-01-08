'use client';

// TODO(mengk): Labeling items that are nested is currently not supported and
// disabled. We'll deal with this later.

import React, { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { LabelSet } from '@/app/api/labelApi';
import { SchemaDefinition, SchemaProperty } from '@/app/types/schema';
import { Tag, Pencil, X, ChevronRight, ChevronDown } from 'lucide-react';
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
import {
  TooltipContent,
  Tooltip,
  TooltipTrigger,
  TooltipProvider,
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

// =============================================================================
// Types
// =============================================================================

interface SchemaValueRendererProps {
  schema: SchemaDefinition;
  values: Record<string, any>;
  labelValues: Record<string, any>;
  activeLabelSet: LabelSet | null;
  onSaveLabel: (key: string, value: any) => void;
  onClearLabel: (key: string) => void;
  showLabels: boolean;
  canEditLabels: boolean;
  calculateAgreement?: (
    key: string
  ) => { agreed: number; total: number } | undefined;
  isRequiredAndUnfilled?: (key: string) => boolean;
  renderLabelSetMenu: (
    onLabelSetCreated: (id: string) => void
  ) => React.ReactNode;
  onClick?: () => void;
}

// =============================================================================
// Shared UI Components
// =============================================================================

export const TagButton = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement>
>(({ className, disabled, ...props }, ref) => {
  return (
    <button
      ref={ref}
      type="button"
      disabled={disabled}
      className={cn(
        'inline-flex items-center gap-1 border rounded-md border-dashed px-1 py-[0.1rem] text-xs text-muted-foreground',
        disabled
          ? 'opacity-60 cursor-not-allowed'
          : 'hover:bg-muted/70 text-muted-foreground cursor-pointer',
        className
      )}
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
  onClear?: () => void;
  disabled?: boolean;
}

export const LabelBadge = React.forwardRef<
  HTMLButtonElement,
  LabelBadgeProps & React.ButtonHTMLAttributes<HTMLButtonElement>
>(({ labeledValue, onClear, disabled, className, ...props }, ref) => {
  return (
    <button
      ref={ref}
      type="button"
      disabled={disabled}
      className={cn(
        'flex w-fit px-1 py-[0.1rem] border relative bg-green-bg border-green-border rounded-md group/label',
        disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer',
        className
      )}
      {...props}
    >
      <div className="flex items-center gap-1">
        <Tag className="size-3 flex-shrink-0 text-green-text" />
        <span className="text-primary text-xs">{labeledValue}</span>
        <X
          className={cn(
            'size-3 flex-shrink-0 text-green-text',
            disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'
          )}
          onPointerDown={(e) => {
            e.preventDefault();
            e.stopPropagation();
          }}
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            if (disabled) return;
            onClear?.();
          }}
        />
      </div>
    </button>
  );
});
LabelBadge.displayName = 'LabelBadge';

interface AgreementDisplayProps {
  agreed: number;
  total: number;
}

export const AgreementDisplay = ({ agreed, total }: AgreementDisplayProps) => {
  if (total <= 1) return null;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="text-muted-foreground mr-1">
            {agreed}/{total}
          </span>
        </TooltipTrigger>
        <TooltipContent>
          <p>
            {agreed} of {total} results agree with this value
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};

// =============================================================================
// Main Component
// =============================================================================

export function SchemaValueRenderer({
  schema,
  values,
  labelValues,
  activeLabelSet,
  onSaveLabel,
  onClearLabel,
  showLabels,
  canEditLabels,
  calculateAgreement,
  isRequiredAndUnfilled,
  renderLabelSetMenu,
  onClick,
}: SchemaValueRendererProps) {
  return (
    <div
      className={cn('space-y-1', onClick && 'cursor-pointer')}
      onClick={onClick}
    >
      {Object.entries(schema.properties).map(([key, property]) => (
        <ValueRenderer
          key={key}
          propertyKey={key}
          schema={property}
          value={values[key]}
          labelValue={labelValues[key]}
          activeLabelSet={activeLabelSet}
          onSaveLabel={(value) => onSaveLabel(key, value)}
          onClearLabel={() => onClearLabel(key)}
          showLabels={showLabels}
          canEditLabels={canEditLabels}
          agreement={calculateAgreement?.(key)}
          isRequiredWarning={isRequiredAndUnfilled?.(key) ?? false}
          renderLabelSetMenu={renderLabelSetMenu}
          depth={0}
        />
      ))}
    </div>
  );
}

// =============================================================================
// Collapsible Section (for arrays and objects)
// =============================================================================

interface CollapsibleSectionProps {
  propertyKey: string;
  summary: string;
  defaultExpanded: boolean;
  children: React.ReactNode;
}

function CollapsibleSection({
  propertyKey,
  summary,
  defaultExpanded,
  children,
}: CollapsibleSectionProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  return (
    <div className="text-xs">
      <button
        type="button"
        className="flex items-center gap-1 hover:bg-muted/50 rounded px-0.5 -ml-0.5"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        {isExpanded ? (
          <ChevronDown size={12} className="text-muted-foreground" />
        ) : (
          <ChevronRight size={12} className="text-muted-foreground" />
        )}
        <label className="font-semibold cursor-pointer">{propertyKey}:</label>
        <span className="text-muted-foreground">{summary}</span>
      </button>

      {isExpanded && (
        <div className="ml-4 mt-1 space-y-1 border-l border-border pl-2">
          {children}
        </div>
      )}
    </div>
  );
}

// =============================================================================
// Unified Value Renderer (handles all types recursively)
// =============================================================================

const MAX_DEPTH = 10;
const MAX_ARRAY_ITEMS = 20;

interface ValueRendererProps {
  propertyKey: string;
  schema: SchemaProperty;
  value: any;
  labelValue: any;
  activeLabelSet: LabelSet | null;
  onSaveLabel: (value: any) => void;
  onClearLabel: () => void;
  showLabels: boolean;
  canEditLabels: boolean;
  agreement?: { agreed: number; total: number };
  isRequiredWarning: boolean;
  renderLabelSetMenu: (
    onLabelSetCreated: (id: string) => void
  ) => React.ReactNode;
  depth: number;
}

function ValueRenderer({
  propertyKey,
  schema,
  value,
  labelValue,
  activeLabelSet,
  onSaveLabel,
  onClearLabel,
  showLabels,
  canEditLabels,
  agreement,
  isRequiredWarning,
  renderLabelSetMenu,
  depth,
}: ValueRendererProps) {
  // Handle null/undefined
  if (value === null || value === undefined) {
    return (
      <div className="flex items-center gap-1.5 text-xs">
        <label className="font-semibold">{propertyKey}:</label>
        <span className="italic text-muted-foreground">null</span>
      </div>
    );
  }

  // Handle depth limit
  if (depth >= MAX_DEPTH) {
    return (
      <div className="flex items-center gap-1.5 text-xs">
        <label className="font-semibold">{propertyKey}:</label>
        <span className="italic text-muted-foreground">...</span>
      </div>
    );
  }

  // Array type
  if (schema.type === 'array') {
    if (!Array.isArray(value) || value.length === 0) {
      return (
        <div className="flex items-center gap-1.5 text-xs">
          <label className="font-semibold">{propertyKey}:</label>
          <span className="italic text-muted-foreground">(empty array)</span>
        </div>
      );
    }

    const itemSchema = (schema as { type: 'array'; items: SchemaProperty })
      .items;

    return (
      <CollapsibleSection
        propertyKey={propertyKey}
        summary={`[${value.length} item${value.length !== 1 ? 's' : ''}]`}
        defaultExpanded={depth < 2}
      >
        {value.slice(0, MAX_ARRAY_ITEMS).map((item, index) => (
          <ValueRenderer
            key={index}
            propertyKey={`[${index}]`}
            schema={itemSchema}
            value={item}
            labelValue={undefined}
            activeLabelSet={activeLabelSet}
            onSaveLabel={() => {}}
            onClearLabel={() => {}}
            showLabels={false}
            canEditLabels={canEditLabels}
            agreement={undefined}
            isRequiredWarning={false}
            renderLabelSetMenu={renderLabelSetMenu}
            depth={depth + 1}
          />
        ))}
        {value.length > MAX_ARRAY_ITEMS && (
          <div className="text-muted-foreground italic">
            ... and {value.length - MAX_ARRAY_ITEMS} more items
          </div>
        )}
      </CollapsibleSection>
    );
  }

  // Object type
  if (schema.type === 'object') {
    const properties =
      (schema as { type: 'object'; properties: Record<string, SchemaProperty> })
        .properties || {};
    const keys = Object.keys(value || {});

    if (keys.length === 0) {
      return (
        <div className="flex items-center gap-1.5 text-xs">
          <label className="font-semibold">{propertyKey}:</label>
          <span className="italic text-muted-foreground">(empty object)</span>
        </div>
      );
    }

    return (
      <CollapsibleSection
        propertyKey={propertyKey}
        summary={`{${keys.length} field${keys.length !== 1 ? 's' : ''}}`}
        defaultExpanded={depth < 2}
      >
        {keys.map((key) => {
          const propSchema = properties[key] || { type: 'string' as const };
          return (
            <ValueRenderer
              key={key}
              propertyKey={key}
              schema={propSchema as SchemaProperty}
              value={value[key]}
              labelValue={undefined}
              activeLabelSet={activeLabelSet}
              onSaveLabel={() => {}}
              onClearLabel={() => {}}
              showLabels={false}
              canEditLabels={canEditLabels}
              agreement={undefined}
              isRequiredWarning={false}
              renderLabelSetMenu={renderLabelSetMenu}
              depth={depth + 1}
            />
          );
        })}
      </CollapsibleSection>
    );
  }

  // String with enum
  if (schema.type === 'string' && 'enum' in schema) {
    return (
      <EnumRenderer
        propertyKey={propertyKey}
        options={schema.enum}
        value={value}
        labelValue={labelValue}
        activeLabelSet={activeLabelSet}
        onSaveLabel={onSaveLabel}
        onClearLabel={onClearLabel}
        showLabels={showLabels}
        canEditLabels={canEditLabels}
        agreement={agreement}
        isRequiredWarning={isRequiredWarning}
        renderLabelSetMenu={renderLabelSetMenu}
      />
    );
  }

  // Plain string
  if (schema.type === 'string') {
    return (
      <StringRenderer
        propertyKey={propertyKey}
        value={value}
        labelValue={labelValue}
        activeLabelSet={activeLabelSet}
        onSaveLabel={onSaveLabel}
        onClearLabel={onClearLabel}
        showLabels={showLabels}
        canEditLabels={canEditLabels}
        isRequiredWarning={isRequiredWarning}
        renderLabelSetMenu={renderLabelSetMenu}
      />
    );
  }

  // Boolean
  if (schema.type === 'boolean') {
    return (
      <BooleanRenderer
        propertyKey={propertyKey}
        value={value}
        labelValue={labelValue}
        activeLabelSet={activeLabelSet}
        onSaveLabel={onSaveLabel}
        onClearLabel={onClearLabel}
        showLabels={showLabels}
        canEditLabels={canEditLabels}
        agreement={agreement}
        isRequiredWarning={isRequiredWarning}
        renderLabelSetMenu={renderLabelSetMenu}
      />
    );
  }

  // Number/Integer
  if (schema.type === 'integer' || schema.type === 'number') {
    return (
      <NumberRenderer
        propertyKey={propertyKey}
        value={value}
        labelValue={labelValue}
        maximum={schema.maximum}
        minimum={schema.minimum}
        isInteger={schema.type === 'integer'}
        activeLabelSet={activeLabelSet}
        onSaveLabel={onSaveLabel}
        onClearLabel={onClearLabel}
        showLabels={showLabels}
        canEditLabels={canEditLabels}
        isRequiredWarning={isRequiredWarning}
        renderLabelSetMenu={renderLabelSetMenu}
      />
    );
  }

  // Fallback for unknown types
  return (
    <div className="flex items-center gap-1.5 text-xs">
      <label className="font-semibold">{propertyKey}:</label>
      <PrimitiveValue value={value} />
    </div>
  );
}

// =============================================================================
// Type-Specific Renderers
// =============================================================================

// --- Enum Renderer ---
interface EnumRendererProps {
  propertyKey: string;
  options: string[];
  value: string;
  labelValue?: string;
  activeLabelSet: LabelSet | null;
  onSaveLabel: (value: string) => void;
  onClearLabel: () => void;
  showLabels: boolean;
  canEditLabels: boolean;
  agreement?: { agreed: number; total: number };
  isRequiredWarning: boolean;
  renderLabelSetMenu: (
    onLabelSetCreated: (id: string) => void
  ) => React.ReactNode;
}

function EnumRenderer({
  propertyKey,
  options,
  value,
  labelValue,
  activeLabelSet,
  onSaveLabel,
  onClearLabel,
  showLabels,
  canEditLabels,
  agreement,
  isRequiredWarning,
  renderLabelSetMenu,
}: EnumRendererProps) {
  const hasLabel = labelValue !== undefined;
  const activeLabelSetId = activeLabelSet?.id;
  const [tempLabelSetId, setTempLabelSetId] = useState<string | null>(null);
  const effectiveLabelSetId = activeLabelSetId || tempLabelSetId;

  const renderLabelUI = () => {
    if (!showLabels) return null;

    // Read-only mode: show disabled badge if there's a label
    if (!canEditLabels) {
      if (hasLabel && activeLabelSetId) {
        return <LabelBadge labeledValue={labelValue} disabled />;
      }
      return null;
    }

    // Editable mode: show full interactive UI
    return (
      <DropdownMenu
        onOpenChange={(open) => {
          if (!open) setTempLabelSetId(null);
        }}
      >
        <DropdownMenuTrigger asChild>
          {hasLabel && activeLabelSetId ? (
            <LabelBadge labeledValue={labelValue} onClear={onClearLabel} />
          ) : (
            <TagButton />
          )}
        </DropdownMenuTrigger>
        <DropdownMenuContent className="w-56" align="start">
          {effectiveLabelSetId ? (
            <DropdownMenuRadioGroup
              value={labelValue}
              onValueChange={(val) => {
                onSaveLabel(val);
                setTempLabelSetId(null);
              }}
            >
              {options.map((opt) => (
                <DropdownMenuRadioItem
                  className="text-xs"
                  key={opt}
                  value={opt}
                >
                  {opt}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          ) : (
            renderLabelSetMenu(setTempLabelSetId)
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    );
  };

  return (
    <div className="gap-1 text-xs flex items-center flex-wrap">
      <label
        className={`font-semibold ${isRequiredWarning ? 'text-red-text' : ''}`}
      >
        {propertyKey}:
      </label>
      <span>{value}</span>
      {agreement && (
        <AgreementDisplay agreed={agreement.agreed} total={agreement.total} />
      )}
      {renderLabelUI()}
    </div>
  );
}

// --- Boolean Renderer ---
interface BooleanRendererProps {
  propertyKey: string;
  value: boolean;
  labelValue?: boolean;
  activeLabelSet: LabelSet | null;
  onSaveLabel: (value: boolean) => void;
  onClearLabel: () => void;
  showLabels: boolean;
  canEditLabels: boolean;
  agreement?: { agreed: number; total: number };
  isRequiredWarning: boolean;
  renderLabelSetMenu: (
    onLabelSetCreated: (id: string) => void
  ) => React.ReactNode;
}

function BooleanRenderer({
  propertyKey,
  value,
  labelValue,
  activeLabelSet,
  onSaveLabel,
  onClearLabel,
  showLabels,
  canEditLabels,
  agreement,
  isRequiredWarning,
  renderLabelSetMenu,
}: BooleanRendererProps) {
  const hasLabel = labelValue !== undefined;
  const activeLabelSetId = activeLabelSet?.id;
  const [tempLabelSetId, setTempLabelSetId] = useState<string | null>(null);
  const effectiveLabelSetId = activeLabelSetId || tempLabelSetId;

  const renderLabelUI = () => {
    if (!showLabels) return null;

    // Read-only mode: show disabled badge if there's a label
    if (!canEditLabels) {
      if (hasLabel && activeLabelSetId) {
        return <LabelBadge labeledValue={String(labelValue)} disabled />;
      }
      return null;
    }

    // Editable mode: show full interactive UI
    return (
      <DropdownMenu
        onOpenChange={(open) => {
          if (!open) setTempLabelSetId(null);
        }}
      >
        <DropdownMenuTrigger asChild>
          {hasLabel && activeLabelSetId ? (
            <LabelBadge
              labeledValue={String(labelValue)}
              onClear={onClearLabel}
            />
          ) : (
            <TagButton />
          )}
        </DropdownMenuTrigger>
        <DropdownMenuContent className="w-56">
          {effectiveLabelSetId ? (
            <DropdownMenuRadioGroup
              value={String(labelValue ?? value)}
              onValueChange={(val) => {
                onSaveLabel(val === 'true');
                setTempLabelSetId(null);
              }}
            >
              {['true', 'false'].map((opt) => (
                <DropdownMenuRadioItem
                  className="text-xs"
                  key={opt}
                  value={opt}
                >
                  {opt}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          ) : (
            renderLabelSetMenu(setTempLabelSetId)
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    );
  };

  return (
    <div className="gap-1 text-xs flex items-center">
      <label
        className={`font-semibold ${isRequiredWarning ? 'text-red-text' : ''}`}
      >
        {propertyKey}:
      </label>
      <div className="flex items-center gap-1">
        <span className="text-blue-700">{String(value)}</span>
        {agreement && (
          <AgreementDisplay agreed={agreement.agreed} total={agreement.total} />
        )}
        {renderLabelUI()}
      </div>
    </div>
  );
}

// --- Number Renderer ---
interface NumberRendererProps {
  propertyKey: string;
  value: number;
  labelValue?: number;
  maximum?: number;
  minimum?: number;
  isInteger: boolean;
  activeLabelSet: LabelSet | null;
  onSaveLabel: (value: number) => void;
  onClearLabel: () => void;
  showLabels: boolean;
  canEditLabels: boolean;
  isRequiredWarning: boolean;
  renderLabelSetMenu: (
    onLabelSetCreated: (id: string) => void
  ) => React.ReactNode;
}

function NumberRenderer({
  propertyKey,
  value,
  labelValue,
  maximum,
  minimum,
  isInteger,
  activeLabelSet,
  onSaveLabel,
  onClearLabel,
  showLabels,
  canEditLabels,
  isRequiredWarning,
  renderLabelSetMenu,
}: NumberRendererProps) {
  const activeLabelSetId = activeLabelSet?.id;
  const [openPopover, setOpenPopover] = useState(false);
  const [localValue, setLocalValue] = useState(String(labelValue ?? ''));
  const [tempLabelSetId, setTempLabelSetId] = useState<string | null>(null);
  const effectiveLabelSetId = activeLabelSetId || tempLabelSetId;

  useEffect(() => {
    setLocalValue(labelValue !== undefined ? String(labelValue) : '');
  }, [labelValue]);

  const submit = () => {
    if (!effectiveLabelSetId || !canEditLabels) return;
    const trimmed = localValue.trim();
    const parsed =
      trimmed === ''
        ? NaN
        : isInteger
          ? parseInt(trimmed, 10)
          : Number(trimmed);
    if (!isNaN(parsed)) {
      let clamped = parsed;
      if (minimum !== undefined) clamped = Math.max(minimum, clamped);
      if (maximum !== undefined) clamped = Math.min(maximum, clamped);
      onSaveLabel(clamped);
      setTempLabelSetId(null);
    }
  };

  const hasLabel = labelValue !== undefined;

  const renderLabelUI = () => {
    if (!showLabels) return null;

    // Read-only mode: show disabled badge if there's a label
    if (!canEditLabels) {
      if (hasLabel && activeLabelSetId) {
        return <LabelBadge labeledValue={String(labelValue)} disabled />;
      }
      return null;
    }

    // Editable mode: show full interactive UI
    return (
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
              onClear={onClearLabel}
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
                step={isInteger ? 1 : 'any'}
              />
              <Button size="sm" type="submit">
                Save
              </Button>
            </form>
          ) : (
            renderLabelSetMenu((id) => setTempLabelSetId(id))
          )}
        </PopoverContent>
      </Popover>
    );
  };

  return (
    <div className="gap-1 text-xs flex items-center flex-wrap">
      <label
        className={`font-semibold ${isRequiredWarning ? 'text-red-text' : ''}`}
      >
        {propertyKey}:
      </label>
      <span className="text-blue-700">{String(value)}</span>
      {renderLabelUI()}
    </div>
  );
}

// --- String Renderer (unified for plain strings and strings with citations) ---
interface StringRendererProps {
  propertyKey: string;
  value: string | { text: string; citations?: any[] };
  labelValue?: string;
  activeLabelSet: LabelSet | null;
  onSaveLabel: (value: string) => void;
  onClearLabel: () => void;
  showLabels: boolean;
  canEditLabels: boolean;
  isRequiredWarning: boolean;
  renderLabelSetMenu: (
    onLabelSetCreated: (id: string) => void
  ) => React.ReactNode;
}

function StringRenderer({
  propertyKey,
  value,
  labelValue,
  activeLabelSet,
  onSaveLabel,
  onClearLabel,
  showLabels,
  canEditLabels,
  isRequiredWarning,
  renderLabelSetMenu,
}: StringRendererProps) {
  // Detect value type: object with text/citations vs plain string
  const hasCitations = value && typeof value === 'object' && 'text' in value;
  const displayText = hasCitations
    ? (value as { text: string }).text
    : (value as string);
  const citations = hasCitations
    ? (value as { citations?: any[] }).citations || []
    : [];

  const activeLabelSetId = activeLabelSet?.id;
  const [localValue, setLocalValue] = useState<string>(labelValue ?? '');
  const [openPopover, setOpenPopover] = useState(false);
  const [tempLabelSetId, setTempLabelSetId] = useState<string | null>(null);
  const effectiveLabelSetId = activeLabelSetId || tempLabelSetId;

  useEffect(() => {
    setLocalValue(labelValue ?? '');
  }, [labelValue]);

  const textareaRef = React.useRef<HTMLTextAreaElement>(null);
  const adjustHeight = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight + 2}px`;
  };

  useEffect(() => {
    if (openPopover) {
      requestAnimationFrame(() => adjustHeight());
    }
  }, [openPopover]);

  const hasLabel = labelValue !== undefined;

  const renderLabelUI = () => {
    if (!showLabels) return null;

    // Read-only mode: show disabled badge if there's a label
    if (!canEditLabels) {
      if (hasLabel && activeLabelSetId) {
        return (
          <div className="flex items-center gap-1 flex-wrap">
            <LabelBadge labeledValue={labelValue} disabled />
          </div>
        );
      }
      return null;
    }

    // Editable mode: show full interactive UI
    return (
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
              <LabelBadge labeledValue={labelValue} onClear={onClearLabel} />
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
                  onSaveLabel(localValue);
                  setOpenPopover(false);
                  setTempLabelSetId(null);
                }}
              >
                <Textarea
                  ref={textareaRef}
                  value={localValue}
                  placeholder="Enter an updated explanation."
                  onChange={(e) => {
                    setLocalValue(e.target.value);
                    adjustHeight();
                  }}
                  className="min-h-[24px] max-h-[20vh] text-xs resize-vertical"
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      onSaveLabel(localValue);
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
              renderLabelSetMenu((id) => setTempLabelSetId(id))
            )}
          </PopoverContent>
        </Popover>
      </div>
    );
  };

  return (
    <div className="space-y-1">
      <div className="text-xs">
        <span className="font-semibold shrink-0">
          {propertyKey}{' '}
          <span
            className={cn(
              'font-normal',
              isRequiredWarning ? 'text-red-text' : ''
            )}
          >
            {isRequiredWarning ? '(required)' : ''}
          </span>
          :
        </span>{' '}
        {citations.length > 0 ? (
          <TextWithCitations text={displayText} citations={citations} />
        ) : (
          <span className="whitespace-pre-wrap break-words">
            {displayText ?? (
              <span className="italic text-muted-foreground">null</span>
            )}
          </span>
        )}
      </div>
      {renderLabelUI()}
    </div>
  );
}

// =============================================================================
// Fallback Primitive Value Display
// =============================================================================

function PrimitiveValue({ value }: { value: any }) {
  if (typeof value === 'boolean') {
    return (
      <span className={cn(value ? 'text-green-text' : 'text-red-text')}>
        {value.toString()}
      </span>
    );
  }

  if (typeof value === 'number') {
    return <span className="text-blue-text">{value}</span>;
  }

  if (typeof value === 'string') {
    const displayValue =
      value.length > 100 ? value.slice(0, 100) + '...' : value;
    return <span className="break-words">{displayValue}</span>;
  }

  return (
    <span className="text-muted-foreground font-mono">
      {JSON.stringify(value)}
    </span>
  );
}

export default SchemaValueRenderer;
