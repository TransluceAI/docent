'use client';

// TODO(mengk): Labeling items that are nested is currently not supported and
// disabled. We'll deal with this later.

import React, { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
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
  // Edit mode props
  mode?: 'view' | 'edit';
  onChange?: (key: string, value: any) => void;
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
  mode = 'view',
  onChange,
}: SchemaValueRendererProps) {
  // Disable onClick in edit mode
  const effectiveOnClick = mode === 'edit' ? undefined : onClick;

  return (
    <div
      className={cn('space-y-1', effectiveOnClick && 'cursor-pointer')}
      onClick={effectiveOnClick}
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
          mode={mode}
          onValueChange={onChange ? (value) => onChange(key, value) : undefined}
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
  // Edit mode props
  mode?: 'view' | 'edit';
  onValueChange?: (value: any) => void;
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
  mode = 'view',
  onValueChange,
}: ValueRendererProps) {
  // Handle null/undefined - only show "null" in view mode
  // In edit mode, fall through to type-specific renderers which handle undefined values
  if ((value === null || value === undefined) && mode !== 'edit') {
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

  // Array type - force view mode with reduced opacity in edit mode
  // TODO(mengk): support editing array values!
  if (schema.type === 'array') {
    if (!Array.isArray(value) || value.length === 0) {
      return (
        <div
          className={cn(
            'flex items-center gap-1.5 text-xs',
            mode === 'edit' && 'opacity-70'
          )}
        >
          <label className="font-semibold">{propertyKey}:</label>
          <span className="italic text-muted-foreground">(empty array)</span>
        </div>
      );
    }

    const itemSchema = (schema as { type: 'array'; items: SchemaProperty })
      .items;

    return (
      <div className={cn(mode === 'edit' && 'opacity-70')}>
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
              mode="view"
            />
          ))}
          {value.length > MAX_ARRAY_ITEMS && (
            <div className="text-muted-foreground italic">
              ... and {value.length - MAX_ARRAY_ITEMS} more items
            </div>
          )}
        </CollapsibleSection>
      </div>
    );
  }

  // Object type - force view mode with reduced opacity in edit mode
  if (schema.type === 'object') {
    const properties =
      (schema as { type: 'object'; properties: Record<string, SchemaProperty> })
        .properties || {};
    const keys = Object.keys(value || {});

    if (keys.length === 0) {
      return (
        <div
          className={cn(
            'flex items-center gap-1.5 text-xs',
            mode === 'edit' && 'opacity-70'
          )}
        >
          <label className="font-semibold">{propertyKey}:</label>
          <span className="italic text-muted-foreground">(empty object)</span>
        </div>
      );
    }

    return (
      <div className={cn(mode === 'edit' && 'opacity-70')}>
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
                mode="view"
              />
            );
          })}
        </CollapsibleSection>
      </div>
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
        mode={mode}
        onValueChange={onValueChange}
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
        mode={mode}
        onValueChange={onValueChange}
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
        mode={mode}
        onValueChange={onValueChange}
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
        mode={mode}
        onValueChange={onValueChange}
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
  // Edit mode props
  mode?: 'view' | 'edit';
  onValueChange?: (value: string) => void;
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
  mode = 'view',
  onValueChange,
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

  // Edit mode: render as toggle buttons for small enums, dropdown for large enums
  if (mode === 'edit') {
    const useButtons = options.length <= 5;

    if (useButtons) {
      // Render toggle buttons for small enums
      return (
        <div className="gap-1 text-xs flex items-center flex-wrap">
          <label
            className={`font-semibold ${isRequiredWarning ? 'text-red-text' : ''}`}
          >
            {propertyKey}:
          </label>
          <div className="flex gap-1 flex-wrap">
            {options.map((opt) => (
              <Button
                key={opt}
                variant={value === opt ? 'default' : 'outline'}
                size="sm"
                className="h-7 text-xs px-1.5"
                onClick={() => onValueChange?.(opt)}
              >
                {opt}
              </Button>
            ))}
          </div>
        </div>
      );
    }

    // Keep existing Select dropdown for large enums (>5 options)
    return (
      <div className="gap-1 text-xs flex items-center flex-wrap">
        <label
          className={`font-semibold ${isRequiredWarning ? 'text-red-text' : ''}`}
        >
          {propertyKey}:
        </label>
        <Select value={value} onValueChange={onValueChange}>
          <SelectTrigger className="h-7 w-auto min-w-[100px] text-xs">
            <SelectValue placeholder="Select..." />
          </SelectTrigger>
          <SelectContent>
            {options.map((opt) => (
              <SelectItem key={opt} value={opt} className="text-xs">
                {opt}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    );
  }

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
  // Edit mode props
  mode?: 'view' | 'edit';
  onValueChange?: (value: boolean) => void;
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
  mode = 'view',
  onValueChange,
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

  // Edit mode: render as toggle buttons
  if (mode === 'edit') {
    return (
      <div className="gap-1 text-xs flex items-center">
        <label
          className={`font-semibold ${isRequiredWarning ? 'text-red-text' : ''}`}
        >
          {propertyKey}:
        </label>
        <div className="flex gap-1">
          <Button
            variant={value === true ? 'default' : 'outline'}
            size="sm"
            className="h-7 text-xs px-1.5"
            onClick={() => onValueChange?.(true)}
          >
            true
          </Button>
          <Button
            variant={value === false ? 'default' : 'outline'}
            size="sm"
            className="h-7 text-xs px-1.5"
            onClick={() => onValueChange?.(false)}
          >
            false
          </Button>
        </div>
      </div>
    );
  }

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
  // Edit mode props
  mode?: 'view' | 'edit';
  onValueChange?: (value: number) => void;
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
  mode = 'view',
  onValueChange,
}: NumberRendererProps) {
  const activeLabelSetId = activeLabelSet?.id;
  const [openPopover, setOpenPopover] = useState(false);
  const [localValue, setLocalValue] = useState(String(labelValue ?? ''));
  const [tempLabelSetId, setTempLabelSetId] = useState<string | null>(null);
  const effectiveLabelSetId = activeLabelSetId || tempLabelSetId;
  const [editInputValue, setEditInputValue] = useState<string>('');

  useEffect(() => {
    setLocalValue(labelValue !== undefined ? String(labelValue) : '');
  }, [labelValue]);

  // Sync edit input value with prop when entering edit mode or when prop changes
  useEffect(() => {
    if (mode === 'edit') {
      setEditInputValue(
        value !== undefined && value !== null ? String(value) : ''
      );
    }
  }, [value, mode]);

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

  // Edit mode: render as number input with blur-based validation
  if (mode === 'edit') {
    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      setEditInputValue(e.target.value);
    };

    const handleBlur = () => {
      const trimmed = editInputValue.trim();
      if (trimmed === '') {
        // Allow clearing - send undefined to parent
        onValueChange?.(undefined as any);
        return;
      }
      const parsed = isInteger ? parseInt(trimmed, 10) : parseFloat(trimmed);
      if (!isNaN(parsed)) {
        let clamped = parsed;
        if (minimum !== undefined) clamped = Math.max(minimum, clamped);
        if (maximum !== undefined) clamped = Math.min(maximum, clamped);
        onValueChange?.(clamped);
        // Update local state to show clamped value
        setEditInputValue(String(clamped));
      } else {
        // Reset to previous valid value on invalid input
        setEditInputValue(
          value !== undefined && value !== null ? String(value) : ''
        );
      }
    };

    return (
      <div className="gap-1 text-xs flex items-center flex-wrap">
        <label
          className={`font-semibold ${isRequiredWarning ? 'text-red-text' : ''}`}
        >
          {propertyKey}:
        </label>
        <Input
          type="number"
          value={editInputValue}
          onChange={handleChange}
          onBlur={handleBlur}
          className="h-7 w-24 text-xs"
          max={maximum}
          min={minimum}
          step={isInteger ? 1 : 'any'}
        />
      </div>
    );
  }

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
  // Edit mode props
  mode?: 'view' | 'edit';
  onValueChange?: (value: string) => void;
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
  mode = 'view',
  onValueChange,
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
  const editTextareaRef = React.useRef<HTMLTextAreaElement>(null);
  const adjustHeight = (ref: React.RefObject<HTMLTextAreaElement | null>) => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight + 2}px`;
  };

  useEffect(() => {
    if (openPopover) {
      requestAnimationFrame(() => adjustHeight(textareaRef));
    }
  }, [openPopover]);

  // Adjust edit textarea height when value changes
  useEffect(() => {
    if (mode === 'edit') {
      requestAnimationFrame(() => adjustHeight(editTextareaRef));
    }
  }, [mode, displayText]);

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
                    adjustHeight(textareaRef);
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

  // Edit mode: render as Textarea
  if (mode === 'edit') {
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
          </span>
        </div>
        <Textarea
          ref={editTextareaRef}
          value={displayText ?? ''}
          onChange={(e) => onValueChange?.(e.target.value)}
          className="min-h-[60px] text-xs resize-vertical"
        />
      </div>
    );
  }

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
