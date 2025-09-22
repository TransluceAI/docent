import { useState } from 'react';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';

import {
  AlertTriangle,
  Earth,
  HelpCircle,
  Search,
  ConciergeBell,
} from 'lucide-react';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from '@/components/ui/tooltip';

const DEFAULT_PLACEHOLDER_TEXT =
  'Describe an agent behavior you want to explore...';
const PRESET_QUERIES = [
  {
    id: 'env',
    label: 'Scaffolding issues',
    query: 'potential issues with the environment the agent is operating in',
    icon: Earth,
    color: 'text-blue-text',
  },
  {
    id: 'strange',
    label: 'Strange behaviors',
    query: 'cases where the agent acted in a strange or unexpected way',
    icon: HelpCircle,
    color: 'text-orange-text',
  },
  {
    id: 'unfollow',
    label: 'Disobeying prompt',
    query:
      'cases where the agent did not follow instructions given to it or directly disobeyed them',
    icon: AlertTriangle,
    color: 'text-red-text',
  },
];

interface QuickSearchBoxProps {
  onGuided: (highLevelDescription: string) => void;
  onDirect: (highLevelDescription: string) => void;
  isLoading: boolean;
}

export default function QuickSearchBox({
  onGuided,
  onDirect,
  isLoading,
}: QuickSearchBoxProps) {
  /**
   * Presets
   */
  const [isPresetHovered, setIsPresetHovered] = useState(false);
  const [searchQueryTextboxValue, setSearchQueryTextboxValue] = useState('');
  const emptyInput = searchQueryTextboxValue.trim() === '';
  const [placeholderText, setPlaceholderText] = useState(
    DEFAULT_PLACEHOLDER_TEXT
  );
  const handleSelectPreset = (query: string) => {
    setSearchQueryTextboxValue(query);
    setIsPresetHovered(false);
  };
  const handlePresetHover = (query: string) => {
    setIsPresetHovered(true);
    setPlaceholderText(query);
  };
  const handlePresetLeave = () => {
    setIsPresetHovered(false);
    setPlaceholderText(DEFAULT_PLACEHOLDER_TEXT);
  };

  const hasWritePermission = useHasCollectionWritePermission();

  const submitGuided = () => {
    if (!hasWritePermission || emptyInput || isLoading) return;
    onGuided(searchQueryTextboxValue);
  };

  const submitDirect = () => {
    if (!hasWritePermission || emptyInput || isLoading) return;
    onDirect(searchQueryTextboxValue);
  };

  const searchForm = (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submitGuided();
      }}
    >
      <fieldset className="relative">
        <Textarea
          className="h-[10rem] resize-none border-0 p-2 shadow-none focus-visible:ring-0 text-xs font-mono"
          placeholder={placeholderText}
          value={isPresetHovered ? '' : searchQueryTextboxValue}
          disabled={!hasWritePermission}
          onChange={(e) => setSearchQueryTextboxValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              submitGuided();
            }
          }}
        />

        <div className="absolute right-2 bottom-2 flex items-center gap-2">
          <Button
            type="button"
            size="sm"
            className="gap-2 h-7 text-xs"
            onClick={submitDirect}
            variant="outline"
            disabled={!hasWritePermission || emptyInput || isLoading}
          >
            <Search className="size-3 -ml-0.5" />
            Direct search
          </Button>
          <Button
            type="submit"
            size="sm"
            className="gap-2 h-7 text-xs"
            disabled={!hasWritePermission || emptyInput || isLoading}
          >
            <ConciergeBell className="size-3.5 -ml-0.5" />
            Guided search
          </Button>
        </div>
      </fieldset>
    </form>
  );

  return (
    // <div className="bg-muted rounded-md space-y-1 border p-2">
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex flex-col">
          <div className="text-sm font-semibold">Create a rubric</div>
          <div className="text-xs text-muted-foreground">
            Find and explore occurrences of an agent behavior
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="text-[11px] text-muted-foreground">Try a preset:</div>
          <div className="flex flex-wrap gap-1">
            {PRESET_QUERIES.map((preset) => {
              const IconComponent = preset.icon;
              return (
                <button
                  key={preset.id}
                  onClick={() => handleSelectPreset(preset.query)}
                  onMouseEnter={() => handlePresetHover(preset.query)}
                  onMouseLeave={handlePresetLeave}
                  className="inline-flex items-center gap-1.5 px-2 py-1 bg-background border border-border rounded-md text-xs font-medium text-primary disabled:opacity-50 hover:bg-secondary hover:border-border transition-colors"
                  disabled={!hasWritePermission}
                >
                  <IconComponent className={`h-3 w-3 ${preset.color}`} />
                  {preset.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>
      <div className="relative overflow-hidden rounded-md border bg-background focus-within:ring-1 focus-within:ring-ring">
        {!hasWritePermission ? (
          <Tooltip>
            <TooltipTrigger asChild>{searchForm}</TooltipTrigger>
            <TooltipContent>
              <p>
                This search box is disabled because you&apos;re in read-only
                mode
              </p>
            </TooltipContent>
          </Tooltip>
        ) : (
          searchForm
        )}
      </div>
    </div>
  );
}
