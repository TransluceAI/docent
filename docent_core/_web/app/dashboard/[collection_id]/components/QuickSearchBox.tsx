import { useState } from 'react';

import {
  AlertTriangle,
  Earth,
  HelpCircle,
  Search,
  ConciergeBell,
} from 'lucide-react';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';

import { cn } from '@/lib/utils';

import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from '@/components/ui/input-group';

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
  modelPicker?: React.ReactNode;
}

export default function QuickSearchBox({
  onGuided,
  onDirect,
  isLoading,
  modelPicker,
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
      <fieldset>
        <InputGroup>
          <InputGroupTextarea
            className="h-48 resize-none p-2 text-xs font-mono"
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
          <InputGroupAddon align="block-end" className="p-2">
            {modelPicker}
            <div className="flex justify-end ml-auto items-center gap-2">
              <InputGroupButton
                type="button"
                size="sm"
                className="gap-2 h-7 text-xs"
                onClick={submitDirect}
                variant="outline"
                disabled={!hasWritePermission || emptyInput || isLoading}
              >
                <Search className="size-3 -ml-0.5" />
                Direct search
              </InputGroupButton>
              <InputGroupButton
                type="submit"
                variant="default"
                size="sm"
                className="gap-2 h-7 text-xs"
                disabled={!hasWritePermission || emptyInput || isLoading}
              >
                <ConciergeBell className="size-3.5 -ml-0.5" />
                Guided search
              </InputGroupButton>
            </div>
          </InputGroupAddon>
        </InputGroup>
      </fieldset>
    </form>
  );

  return (
    <div className="space-y-2 overflow-x-visible">
      <div className="flex items-center justify-between">
        <div className="flex flex-col">
          <div className="text-sm font-semibold">Run rubric</div>
        </div>
        <div className="flex items-center gap-2">
          <div className="text-[11px] text-muted-foreground">Try a preset:</div>
          <div className="flex flex-wrap gap-1">
            {PRESET_QUERIES.map((preset, index) => {
              const IconComponent = preset.icon;
              return (
                <button
                  key={preset.id}
                  onClick={() => handleSelectPreset(preset.query)}
                  onMouseEnter={() => handlePresetHover(preset.query)}
                  onMouseLeave={handlePresetLeave}
                  className={cn(
                    'inline-flex items-center gap-1.5 px-2 py-1 bg-background border border-border rounded-md text-xs font-medium text-primary disabled:opacity-50 hover:bg-secondary hover:border-border transition-colors',
                    index === 0 ? 'hidden 2xl:inline-flex' : ''
                  )}
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
      {searchForm}
      {/* <div>
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
      </div> */}
    </div>
  );
}
