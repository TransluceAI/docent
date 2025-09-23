'use client';
import { useState, useMemo, useReducer, useEffect, useRef } from 'react';
import { Button } from '../../components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../components/ui/select';
import { Badge } from '../../components/ui/badge';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { FunnelPlus, X } from 'lucide-react';
import {
  useResultFilterControls,
  Operator,
} from '@/providers/use-result-filters';
import posthog from 'posthog-js';
import { toast } from '@/hooks/use-toast';
import { SchemaProperty } from '../types/schema';

interface FilterControlsProps {
  setIsPopoverOpen: (open: boolean) => void;
}

type Step = 'field' | 'operator' | 'value' | null;

interface FilterState {
  path?: string;
  op?: Operator;
  value: string;
  step: Step;
}

type Action =
  | { type: 'selectField'; path: string }
  | { type: 'selectOperator'; op: Operator }
  | { type: 'setValue'; value: string }
  | { type: 'openStep'; step: Step }
  | { type: 'reset' };

function reducer(state: FilterState, action: Action): FilterState {
  switch (action.type) {
    case 'selectField':
      return { path: action.path, op: undefined, value: '', step: 'operator' };
    case 'selectOperator':
      return { ...state, op: action.op, step: 'value' };
    case 'setValue':
      return { ...state, value: action.value };
    case 'openStep':
      return { ...state, step: action.step };
    case 'reset':
      return { path: undefined, op: undefined, value: '', step: null };
    default:
      return state;
  }
}

function FilterControls({ setIsPopoverOpen }: FilterControlsProps) {
  const { options, filters, setFilters, getValidOps, schema } =
    useResultFilterControls();

  const [state, dispatch] = useReducer(reducer, {
    path: undefined,
    op: undefined,
    value: '',
    step: null as Step,
  });
  const inputRef = useRef<HTMLInputElement | null>(null);

  const property = useMemo<SchemaProperty | undefined>(() => {
    if (!state.path || !schema) return;
    return schema.properties[state.path];
  }, [state.path, schema]);

  useEffect(() => {
    const isEnum = property?.type === 'string' && 'enum' in property;
    if (state.step === 'value' && !isEnum) {
      inputRef.current?.focus();
    }
  }, [state.step, property]);

  const addFilter = () => {
    const { path, op, value } = state;
    if (!path || !op) return;

    const existingFilter = filters.find(
      (f) => f.path === path && f.op === op && f.value === value
    );
    if (existingFilter) {
      toast({
        title: 'Filter already exists',
        description: 'Please enter a different filter',
      });
    } else {
      setFilters([...filters, { path, op, value }]);

      posthog.capture('filter_added', {
        path,
        op,
        value,
      });
    }

    setIsPopoverOpen(false);
    dispatch({ type: 'reset' });
  };

  const Selector = (options: string[]) => {
    return (
      <Select
        value={state.value}
        open={state.step === 'value'}
        onOpenChange={(o) =>
          dispatch({ type: 'openStep', step: o ? 'value' : null })
        }
        onValueChange={(v) => {
          dispatch({ type: 'setValue', value: v });
        }}
      >
        <SelectTrigger className="h-7 text-xs bg-background font-mono text-muted-foreground">
          <SelectValue placeholder="Select value" />
        </SelectTrigger>
        <SelectContent>
          {options.map((opt) => (
            <SelectItem key={opt} value={opt} className="font-mono text-xs">
              {opt}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  };

  return (
    <div className="grid grid-cols-[1fr_auto_1fr_auto] gap-1.5">
      <div>
        <div className="text-xs text-muted-foreground font-mono ml-1 mb-1">
          Field
        </div>
        <Select
          value={state.path}
          open={state.step === 'field'}
          onOpenChange={(o) =>
            dispatch({ type: 'openStep', step: o ? 'field' : null })
          }
          onValueChange={(v) => {
            dispatch({ type: 'selectField', path: v });
          }}
        >
          <SelectTrigger className="h-7 text-xs bg-background font-mono text-muted-foreground">
            <SelectValue placeholder="Select field" />
          </SelectTrigger>
          <SelectContent>
            {options.map((k) => (
              <SelectItem key={k} value={k} className="font-mono text-xs">
                {k}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div>
        <div className="text-xs text-muted-foreground font-mono mr-1 mb-1">
          Operator
        </div>
        <Select
          value={state.op}
          open={state.step === 'operator'}
          onOpenChange={(o) =>
            dispatch({ type: 'openStep', step: o ? 'operator' : null })
          }
          onValueChange={(v) => {
            dispatch({ type: 'selectOperator', op: v as Operator });
          }}
        >
          <SelectTrigger className="h-7 text-xs bg-background font-mono text-muted-foreground w-20">
            <SelectValue placeholder="Select operator" />
          </SelectTrigger>
          <SelectContent>
            {getValidOps(state.path || '').map((o) => (
              <SelectItem key={o} value={o} className="font-mono text-xs">
                {o}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div>
        <div className="text-xs text-muted-foreground font-mono ml-1 mb-1">
          Value
        </div>
        {(() => {
          if (property?.type === 'string' && 'enum' in property)
            return Selector(property.enum);
          if (property?.type === 'boolean') return Selector(['true', 'false']);
          return (
            <input
              value={state.value}
              onChange={(e) =>
                dispatch({ type: 'setValue', value: e.target.value })
              }
              placeholder="Enter value"
              className="h-7 text-xs bg-background font-mono text-muted-foreground w-full rounded border border-border px-2"
              ref={inputRef}
              onKeyDown={(e) => {
                if (e.key === 'Enter') addFilter();
              }}
            />
          );
        })()}
      </div>
      <div>
        <div className="text-xs text-muted-foreground mb-1">&nbsp;</div>
        <Button
          size="sm"
          className="h-7 text-xs px-2"
          onClick={addFilter}
          disabled={!state.path || !state.op}
        >
          Add Filter
        </Button>
      </div>
    </div>
  );
}

export function ResultFilterControlsTrigger() {
  const { filters } = useResultFilterControls();
  const [isPopoverOpen, setIsPopoverOpen] = useState(false);

  return (
    <Popover open={isPopoverOpen} onOpenChange={setIsPopoverOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="gap-1 h-7 text-xs"
        >
          <FunnelPlus className="h-3 w-3" />
          {filters.length > 0 ? (
            <>
              <span className="hidden xl:inline">Filters</span>
              <Badge variant="secondary" className="ml-1 h-4 px-1 text-[10px]">
                {filters.length}
              </Badge>
            </>
          ) : (
            <span className="hidden xl:inline">Add filter</span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[520px] p-3" align="start">
        <FilterControls setIsPopoverOpen={setIsPopoverOpen} />
      </PopoverContent>
    </Popover>
  );
}

export function ResultFilterControlsBadges() {
  const { filters, setFilters, labeled, setLabeled } =
    useResultFilterControls();

  const removeFilter = (idx: number) => {
    setFilters(filters.filter((_, i) => i !== idx));
  };

  const clearAll = () => {
    setFilters([]);
  };

  const showFilters = filters && filters.length > 0;

  return (
    <div className="flex flex-wrap gap-1.5 max-h-7 h-7 items-center">
      <span className="text-xs text-muted-foreground">Filters:</span>
      {!showFilters && (
        <span className="text-xs text-muted-foreground font-mono">None</span>
      )}
      {showFilters &&
        filters.map((f, idx) => (
          <div
            key={`${f.path}-${idx}`}
            className="inline-flex items-center gap-x-1 text-xs bg-indigo-50 dark:bg-indigo-950/30 text-primary border border-indigo-200 dark:border-indigo-800 pl-1.5 pr-1 py-0.5 rounded-md"
          >
            <span className="font-mono">{f.path}</span>
            <span className="text-indigo-500 dark:text-indigo-400 font-mono">
              {f.op}
            </span>
            <span className="font-mono truncate max-w-12">
              {Array.isArray(f.value) ? f.value.join(',') : String(f.value)}
            </span>
            <button
              onClick={() => removeFilter(idx)}
              className="p-0.5 text-primary hover:text-primary/50 transition-colors"
              title="Remove filter"
            >
              <X size={10} />
            </button>
          </div>
        ))}
      {labeled && (
        <div className="inline-flex items-center gap-x-1 text-xs bg-indigo-50 dark:bg-indigo-950/30 text-primary border border-indigo-200 dark:border-indigo-800 pl-1.5 pr-1 py-0.5 rounded-md">
          <span className="font-mono">Show labeled</span>
          <button
            onClick={() => setLabeled(false)}
            className="p-0.5 text-primary hover:text-primary/50 transition-colors"
            title="Remove filter"
          >
            <X size={10} />
          </button>
        </div>
      )}
      {(showFilters || labeled) && (
        <button
          onClick={() => {
            clearAll();
            setLabeled(false);
          }}
          className="inline-flex items-center gap-x-1 text-xs bg-red-50 dark:bg-red-950/30 text-primary border border-red-200 dark:border-red-800 px-1.5 py-0.5 rounded-md hover:bg-red-100 dark:hover:bg-red-950/50 transition-colors"
        >
          Clear
        </button>
      )}
    </div>
  );
}
