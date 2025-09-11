'use client';
import { useState, useMemo } from 'react';
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
import { useResultFilterControls } from '@/providers/use-result-filters';
import { Operator } from '@/providers/use-result-filters';
import posthog from 'posthog-js';

function FilterControls() {
  const { options, filters, setFilters, getValidOps, schema } =
    useResultFilterControls();

  const [path, setPath] = useState<string>();
  const [op, setOp] = useState<Operator>('==');
  const [value, setValue] = useState<string>('');

  const enumOptions = useMemo<string[]>(() => {
    if (!path || !schema) return [];
    if (
      schema.properties[path].type === 'string' &&
      'enum' in schema.properties[path]
    ) {
      return schema.properties[path].enum;
    }
    return [];
  }, [path, schema]);

  const addFilter = () => {
    if (!path) return;
    setFilters([...filters, { path, op, value }]);

    posthog.capture('filter_added', {
      path,
      op,
      value,
    });
  };

  return (
    <div className="grid grid-cols-[1fr_auto_1fr_auto] gap-1.5">
      <div>
        <div className="text-xs text-muted-foreground font-mono ml-1 mb-1">
          Field
        </div>
        <Select value={path} onValueChange={setPath}>
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
        <Select value={op} onValueChange={(v) => setOp(v as Operator)}>
          <SelectTrigger className="h-7 text-xs bg-background font-mono text-muted-foreground w-20">
            <SelectValue placeholder="==" />
          </SelectTrigger>
          <SelectContent>
            {getValidOps(path || '').map((o) => (
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
        {enumOptions.length > 0 ? (
          <Select value={value} onValueChange={setValue}>
            <SelectTrigger className="h-7 text-xs bg-background font-mono text-muted-foreground">
              <SelectValue placeholder="Select value" />
            </SelectTrigger>
            <SelectContent>
              {enumOptions.map((opt) => (
                <SelectItem key={opt} value={opt} className="font-mono text-xs">
                  {opt}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Enter value"
            className="h-7 text-xs bg-background font-mono text-muted-foreground w-full rounded border border-border px-2"
            onKeyDown={(e) => {
              if (e.key === 'Enter') addFilter();
            }}
          />
        )}
      </div>
      <div>
        <div className="text-xs text-muted-foreground mb-1">&nbsp;</div>
        <Button
          size="sm"
          className="h-7 text-xs px-2"
          onClick={addFilter}
          disabled={!path}
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
              Filters
              <Badge variant="secondary" className="ml-1 h-4 px-1 text-[10px]">
                {filters.length}
              </Badge>
            </>
          ) : (
            'Add filter'
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[520px] p-3" align="start">
        <FilterControls />
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
