import { useState } from 'react';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';

import {
  Search,
  AlertTriangle,
  Earth,
  HelpCircle,
  FileSearch,
} from 'lucide-react';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
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
  onSubmit: (highLevelDescription: string, mode: 'explore' | 'full') => void;
  isLoading: boolean;
}

export default function QuickSearchBox({
  onSubmit,
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

  /**
   * Search mode
   */
  const [searchMode, setSearchMode] = useState<'explore' | 'full'>('explore');

  const hasWritePermission = useHasCollectionWritePermission();

  const searchFieldset = (
    <fieldset className="relative">
      <Textarea
        className="h-[10rem] resize-none border-0 p-2 shadow-none focus-visible:ring-0 text-xs font-mono"
        placeholder={placeholderText}
        value={isPresetHovered ? '' : searchQueryTextboxValue}
        disabled={!hasWritePermission}
        onChange={(e) => setSearchQueryTextboxValue(e.target.value)}
      />

      <div className="absolute right-2 bottom-2 flex items-center">
        <Button
          type="button"
          size="sm"
          className="gap-2 h-7 text-xs rounded-r-none border-r-0"
          onClick={() => onSubmit(searchQueryTextboxValue, searchMode)}
          disabled={!hasWritePermission || emptyInput || isLoading}
        >
          {searchMode === 'explore' ? (
            <FileSearch className="size-3 -ml-0.5" />
          ) : (
            <Search className="size-3 -ml-0.5" />
          )}
          {searchMode === 'explore' ? 'Explore' : 'Search'}
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              size="sm"
              className="h-7 w-7 px-1 rounded-l-none"
              disabled={!hasWritePermission || emptyInput || isLoading}
            >
              <span className="sr-only">Toggle search mode</span>
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
                className="size-3"
              >
                <path
                  fillRule="evenodd"
                  d="M5.23 7.21a.75.75 0 011.06.02L10 10.94l3.71-3.71a.75.75 0 111.06 1.06l-4.24 4.24a.75.75 0 01-1.06 0L5.21 8.29a.75.75 0 01.02-1.08z"
                  clipRule="evenodd"
                />
              </svg>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuItem
              onClick={() => setSearchMode('full')}
              className="text-xs"
            >
              <div className="flex flex-col">
                <span>Direct Search</span>
                <span className="text-muted-foreground text-[11px]">
                  Run a quick search across all data
                </span>
              </div>
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() => setSearchMode('explore')}
              className="text-xs"
            >
              <div className="flex flex-col">
                <span>Create a rubric (Preview)</span>
                <span className="text-muted-foreground text-[11px]">
                  Refine a rubric with our agent
                </span>
              </div>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </fieldset>
  );

  return (
    // <div className="bg-muted rounded-md space-y-1 border p-2">
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex flex-col">
          <div className="text-sm font-semibold">Quick search</div>
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
            <TooltipTrigger asChild>{searchFieldset}</TooltipTrigger>
            <TooltipContent>
              <p>
                This search box is disabled because you&apos;re in read-only
                mode
              </p>
            </TooltipContent>
          </Tooltip>
        ) : (
          searchFieldset
        )}
      </div>
    </div>
  );
}
