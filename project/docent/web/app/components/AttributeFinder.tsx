import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { toast } from '@/hooks/use-toast';
import {
  CircleX,
  CornerDownLeft,
  Loader2,
  Pencil,
  RefreshCw,
  Sparkles,
  Wand2,
  Bookmark,
  AlertTriangle,
  XCircle,
  HelpCircle,
  XOctagon,
  LucideIcon,
  Clock,
  ArrowUpRight,
  Earth,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { useFrameGrid } from '../contexts/FrameGridContext';
import type { MetadataType, MetadataFilter } from '@/app/types/docent';
import BinEditor from './BinEditor';
import ClusterProposalDialog from './ClusterProposalDialog';

interface AttributeFinderProps {
  onShowDatapoint?: (datapointId: string, blockId?: number) => void;
}

// Preset search queries with custom icons
const PRESET_QUERIES = [
  {
    id: 'env',
    label: 'Environment issues',
    query: 'potential issues with the environment the agent is operating in',
    icon: Earth,
  },
  {
    id: 'strange',
    label: 'Strange behaviors',
    query: 'cases where the agent acted in a strange or unexpected way',
    icon: HelpCircle,
  },
  {
    id: 'unfollow',
    label: 'Not following instructions',
    query:
      'cases where the agent did not follow instructions given to it or directly disobeyed them',
    icon: AlertTriangle,
  },
  // {
  //   id: 'hallucination',
  //   label: 'Hallucinations',
  //   query:
  //     'cases where agent hallucinated a correct or near correct flag without having derived it from a prior tool output.\n\n(the correct flag is the last one that the agent submitted)',
  //   icon: AlertTriangle,
  // },
];

const DEFAULT_PLACEHOLDER_TEXT =
  "Describe what you're looking for in detail, or try a sample preset above";

const AttributeFinder: React.FC<AttributeFinderProps> = ({
  onShowDatapoint,
}) => {
  const fg = useFrameGrid();
  const { sendMessage } = fg;
  const [newAttribute, setNewAttribute] = useState('');
  const [metadataKey, setMetadataKey] = useState('');
  const [metadataValue, setMetadataValue] = useState('');
  const [metadataType, setMetadataType] = useState<MetadataType>('str');
  const [metadataOp, setMetadataOp] = useState<string>('==');
  const [isEnhancingQuery, setIsEnhancingQuery] = useState(false);
  const [placeholderText, setPlaceholderText] = useState(
    DEFAULT_PLACEHOLDER_TEXT
  );
  const [clusterFeedback, setClusterFeedback] = useState('');
  const [showFeedbackInput, setShowFeedbackInput] = useState(false);

  // Get metadata filters from baseFilter
  const metadataFilters = fg.baseFilter
    ? (fg.baseFilter.filter(
        (filter) => filter.type === 'metadata'
      ) as MetadataFilter[])
    : [];

  // Find the active dimension state based on the current attribute query
  const activeDimState = fg.curAttributeQuery
    ? fg.dimensions.find(
        (dimState) => dimState.dim.attribute === fg.curAttributeQuery
      )
    : null;

  // Metadata filter manipulation
  const onUpdateMetadataFilter = () => {
    if (!fg.frameGridId) return;

    if (!metadataKey.trim()) {
      toast({
        title: 'Missing key',
        description: 'Please enter a metadata key',
        variant: 'destructive',
      });
      return;
    }

    let parsedKey;
    let parsedValue;

    if (!metadataValue) {
      parsedKey = null;
      parsedValue = null;
    } else {
      parsedKey = metadataKey.trim();
      parsedValue = metadataValue;

      if (metadataType === 'bool') {
        parsedValue = metadataValue === 'true';
      } else if (metadataType === 'int') {
        parsedValue = Number(metadataValue);
        if (isNaN(parsedValue)) {
          toast({
            title: 'Invalid number',
            description: 'Please enter a valid number',
            variant: 'destructive',
          });
          return;
        }
      }

      handleClearAttribute();
      fg.onAddFilter({
        id: '_metadata_filter_' + Math.random(),
        type: 'metadata',
        key: parsedKey,
        value: parsedValue,
        op: metadataOp,
      } as MetadataFilter);
    }

    // Reset form
    setMetadataKey('');
    setMetadataValue('');
  };

  // Auto-submit when a value is selected from a dropdown
  useEffect(() => {
    if (metadataType === 'bool' && metadataValue && metadataKey) {
      onUpdateMetadataFilter();
    }
  }, [metadataValue, metadataType]);

  const handleSearch = () => {
    if (!newAttribute.trim()) {
      toast({
        title: 'Missing search query',
        description: 'Please enter a search query',
        variant: 'destructive',
      });
      return;
    }

    // Search history is now handled in the context via requestAttributes
    const trimmedQuery = newAttribute.trim();
    fg.requestAddDimension(trimmedQuery, null);
    fg.requestAttributes(trimmedQuery);

    // Reset form
    setNewAttribute('');
  };

  const handleClearAttribute = () => {
    // If there's an active dimension, we need to delete it
    if (activeDimState) {
      fg.handleClearAttribute(activeDimState.dim.id);
    } else {
      fg.handleClearAttribute(null);
    }
  };

  const handleEditAttribute = () => {
    if (activeDimState) {
      // Set the textarea value to the current query
      setNewAttribute(activeDimState.dim.attribute || '');

      // Use the new context function
      fg.handleClearAttribute(activeDimState.dim.id);
    }
  };

  const handleRequestClusters = () => {
    if (!activeDimState) return;

    // If bins exist and feedback is not being shown yet, show the feedback input
    if (
      activeDimState.dim.bins &&
      activeDimState.dim.bins.length > 0 &&
      !showFeedbackInput
    ) {
      setShowFeedbackInput(true);
      return;
    }

    // Use the context's requestClusters function
    fg.requestClusters(activeDimState.dim.id, clusterFeedback);

    // Clear feedback after sending and hide the input
    setClusterFeedback('');
    setShowFeedbackInput(false);
  };

  const handleCancelFeedback = () => {
    setShowFeedbackInput(false);
    setClusterFeedback('');
  };

  const handleDeleteBin = (dimensionId: string, binId: string) => {
    if (!fg.frameGridId) return;

    sendMessage('delete_bin', {
      dim_id: dimensionId,
      bin_id: binId,
    });
  };

  const handleCloseClusterDialog = () => {
    fg.setClusterProposals(null);
    fg.setClusterSessionId(null);
  };

  const handleAutoEnhance = async () => {
    if (!newAttribute.trim()) return;

    setIsEnhancingQuery(true);
    try {
      const enhancedQuery = await fg.rewriteSearchQuery(newAttribute.trim());
      setNewAttribute(enhancedQuery);
      toast({
        title: 'Query Enhanced',
        description: 'Your search query has been enhanced for better results.',
      });
    } finally {
      setIsEnhancingQuery(false);
    }
  };

  const [isPresetHovered, setIsPresetHovered] = useState(false);

  const handleSelectPreset = (query: string) => {
    setNewAttribute(query);
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

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <div>
          <div className="text-sm font-semibold">Filter Transcripts</div>
          <div className="text-xs">
            Investigate only a subset of transcripts.
          </div>
        </div>
        <div className="border rounded-md bg-gray-50 p-2 space-y-2">
          {fg.baseFilter && fg.baseFilter.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-2">
              {metadataFilters.map((filter) => (
                <div
                  key={filter.id}
                  className="inline-flex items-center gap-x-1 text-xs bg-indigo-50 text-indigo-800 border border-indigo-100 pl-1.5 pr-1 py-0.5 rounded-md"
                >
                  <span className="">{filter.key}</span>
                  <span className="text-indigo-400">{filter.op || '=='}</span>
                  <span className="font-mono">{String(filter.value)}</span>
                  <button
                    onClick={() => fg.onRemoveFilter(filter.id)}
                    className="ml-0.5 hover:bg-indigo-100 rounded-full p-0.5 text-indigo-400 hover:text-indigo-600 transition-colors"
                  >
                    <CircleX size={12} />
                  </button>
                </div>
              ))}
              {fg.baseFilter.length > 0 && (
                <button
                  onClick={fg.onClearFilters}
                  className="inline-flex items-center gap-x-1 text-xs bg-red-50 text-red-500 border border-red-100 px-1.5 py-0.5 rounded-md hover:bg-red-100 transition-colors"
                >
                  <RefreshCw className="h-3 w-3 mr" />
                  Clear
                </button>
              )}
            </div>
          )}
          <div className="grid grid-cols-[1fr_auto_1fr_auto] gap-2">
            <div className="space-y-1">
              <div className="text-xs text-gray-600">Filter by</div>
              <Select
                value={metadataKey}
                onValueChange={(value: string) => {
                  setMetadataKey(value);
                  const selectedField = fg.transcriptMetadataFields.find(
                    (f) => f.name === value
                  );
                  if (selectedField) {
                    setMetadataType(selectedField.type);
                    setMetadataValue('');
                    // Reset operator to == when changing fields
                    setMetadataOp('==');
                  }
                }}
              >
                <SelectTrigger className="h-8 text-xs bg-white font-mono text-gray-600">
                  <SelectValue placeholder="Select field" />
                </SelectTrigger>
                <SelectContent>
                  {fg.transcriptMetadataFields.map((field) => (
                    <SelectItem
                      key={field.name}
                      value={field.name}
                      className="font-mono text-gray-600 text-xs"
                    >
                      {field.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {(metadataType === 'int' || metadataType === 'float') && (
              <div className="space-y-1">
                <div className="text-xs text-gray-600">Operator</div>
                <Select value={metadataOp} onValueChange={setMetadataOp}>
                  <SelectTrigger className="h-8 text-xs bg-white font-mono text-gray-600 w-16">
                    <SelectValue placeholder="==" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="==" className="font-mono text-xs">
                      ==
                    </SelectItem>
                    <SelectItem value="!=" className="font-mono text-xs">
                      !=
                    </SelectItem>
                    <SelectItem value="<" className="font-mono text-xs">
                      &lt;
                    </SelectItem>
                    <SelectItem value="<=" className="font-mono text-xs">
                      &lt;=
                    </SelectItem>
                    <SelectItem value=">" className="font-mono text-xs">
                      &gt;
                    </SelectItem>
                    <SelectItem value=">=" className="font-mono text-xs">
                      &gt;=
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
            {!(metadataType === 'int' || metadataType === 'float') && (
              <div className="space-y-1">
                <div className="text-xs text-gray-600">Operator</div>
                <Select value={metadataOp} onValueChange={setMetadataOp}>
                  <SelectTrigger className="h-8 text-xs bg-white font-mono text-gray-600 w-16">
                    <SelectValue placeholder="==" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="==" className="font-mono text-xs">
                      ==
                    </SelectItem>
                    <SelectItem value="!=" className="font-mono text-xs">
                      !=
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="space-y-1">
              <div className="text-xs text-gray-600">
                Value ({metadataType})
              </div>
              {metadataType === 'bool' ? (
                <Select value={metadataValue} onValueChange={setMetadataValue}>
                  <SelectTrigger className="h-8 text-xs bg-white font-mono text-gray-600">
                    <SelectValue placeholder="Select value" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="true" className="font-mono text-xs">
                      true
                    </SelectItem>
                    <SelectItem value="false" className="font-mono text-xs">
                      false
                    </SelectItem>
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  value={metadataValue}
                  onChange={(e) => setMetadataValue(e.target.value)}
                  placeholder={
                    metadataType === 'int' ? 'e.g. 42' : 'e.g. value'
                  }
                  type={metadataType === 'int' ? 'number' : 'text'}
                  className="h-8 text-xs bg-white font-mono text-gray-600"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      onUpdateMetadataFilter();
                    }
                  }}
                />
              )}
            </div>
            <div className="space-y-1">
              <div className="text-xs text-gray-600">&nbsp;</div>
              <Button
                onClick={onUpdateMetadataFilter}
                disabled={
                  !fg.frameGridId ||
                  !metadataKey.trim() ||
                  !metadataValue.trim() ||
                  metadataType === 'bool' // Disable button for boolean type since it auto-submits
                }
                className="h-8 text-xs whitespace-nowrap"
                size="sm"
              >
                Add filter
              </Button>
            </div>
          </div>
        </div>
      </div>
      <div className="border-t" />
      <div className="space-y-2">
        <div>
          <div className="text-sm font-semibold">Global Search</div>
          <div className="text-xs">
            Look for patterns, errors, or other interesting phenomena in the
            transcripts.
          </div>
        </div>

        <div className="border rounded-md bg-gray-50 p-2 space-y-1">
          <div className="text-xs text-gray-600">Search query</div>
          {activeDimState ? (
            <div className="space-y-2">
              <div className="flex items-center">
                <div className="flex-1 px-2 py-1 bg-indigo-50 border border-indigo-100 rounded text-xs font-mono whitespace-pre-wrap text-indigo-800">
                  {activeDimState.dim.attribute}
                </div>
                <div className="flex ml-2 space-x-1">
                  <button
                    onClick={handleEditAttribute}
                    className="inline-flex items-center gap-x-1 text-xs bg-indigo-50 text-indigo-500 border border-indigo-100 px-1.5 py-0.5 rounded-md hover:bg-indigo-100 transition-colors"
                  >
                    <Pencil className="h-3 w-3" />
                    Edit
                  </button>
                  <button
                    onClick={handleClearAttribute}
                    className="inline-flex items-center gap-x-1 text-xs bg-red-50 text-red-500 border border-red-100 px-1.5 py-0.5 rounded-md hover:bg-red-100 transition-colors"
                  >
                    <RefreshCw className="h-3 w-3 mr" />
                    Clear
                  </button>
                </div>
              </div>

              {/* Progress bar for attribute updates */}
              {fg.loadingAttributesFor === fg.curAttributeQuery &&
                fg.loadingAttributesFor !== null && (
                  <div className="mt-2 mb-2 space-y-1">
                    <div className="flex justify-between text-xs text-gray-600">
                      <span>Processing datapoints</span>
                      <span>
                        {fg.numAttributeUpdatesReceived[0]} /{' '}
                        {fg.numAttributeUpdatesReceived[1]}
                      </span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-1.5">
                      <div
                        className="bg-blue-600 h-1.5 rounded-full transition-all duration-300 ease-in-out"
                        style={{
                          width: `${
                            fg.numAttributeUpdatesReceived[1] > 0
                              ? Math.min(
                                  (fg.numAttributeUpdatesReceived[0] /
                                    fg.numAttributeUpdatesReceived[1]) *
                                    100,
                                  100
                                )
                              : 0
                          }%`,
                        }}
                      ></div>
                    </div>
                  </div>
                )}

              <Button
                size="sm"
                variant="outline"
                className="text-xs w-full"
                onClick={handleRequestClusters}
                disabled={
                  !fg.frameGridId ||
                  activeDimState.loading_clusters ||
                  activeDimState.loading_marginal ||
                  (fg.loadingAttributesFor === fg.curAttributeQuery &&
                    fg.loadingAttributesFor !== null) ||
                  showFeedbackInput // Disable button when feedback input is visible
                }
              >
                {activeDimState.loading_clusters ? (
                  <Loader2 className="h-3 w-3 mr-2 animate-spin" />
                ) : (
                  <Sparkles className="h-3 w-3 mr-2" />
                )}
                {activeDimState.dim.bins && activeDimState.dim.bins.length > 0
                  ? 'Re-cluster with feedback'
                  : 'Cluster matching results'}
              </Button>

              {/* Feedback input for re-clustering - only show when requested */}
              {showFeedbackInput && (
                <div className="mt-1.5 space-y-0.5">
                  <div className="text-xs text-gray-600 mb-0.5">
                    Feedback for re-clustering
                  </div>
                  <div className="flex space-x-1 items-center">
                    <Input
                      autoFocus
                      value={clusterFeedback}
                      onChange={(e) => setClusterFeedback(e.target.value)}
                      placeholder="Describe how clusters should be improved..."
                      className="text-xs bg-white font-mono text-gray-600 flex-1 h-7"
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          handleRequestClusters();
                        }
                      }}
                    />
                    <Button
                      size="sm"
                      onClick={handleRequestClusters}
                      className="text-xs h-7 px-2"
                    >
                      Submit
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleCancelFeedback}
                      className="text-xs h-7 px-2"
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}

              {/* Display bins if they exist */}
              {activeDimState.dim.bins &&
                activeDimState.dim.bins.length > 0 && (
                  <div className="space-y-2 mt-3">
                    <div className="text-xs text-gray-600 font-medium">
                      Clusters
                    </div>
                    {activeDimState.dim.bins.map((bin) => (
                      <BinEditor
                        key={bin.id}
                        bin={bin}
                        loading={activeDimState.loading_marginal}
                        marginalJudgments={
                          fg.marginals?.[activeDimState.dim.id]?.[bin.id] ||
                          undefined
                        }
                        onSubmit={(text) => {
                          if (!fg.frameGridId) return;
                          sendMessage('edit_bin', {
                            dim_id: activeDimState.dim.id,
                            bin_id: bin.id,
                            new_predicate: text,
                          });
                        }}
                        onDelete={() =>
                          handleDeleteBin(activeDimState.dim.id, bin.id)
                        }
                        onShowDatapoint={onShowDatapoint || (() => {})}
                      />
                    ))}
                  </div>
                )}
            </div>
          ) : (
            <>
              <div className="flex flex-wrap gap-2">
                {PRESET_QUERIES.map((preset) => {
                  const IconComponent = preset.icon;
                  return (
                    <button
                      key={preset.id}
                      onClick={() => handleSelectPreset(preset.query)}
                      onMouseEnter={() => handlePresetHover(preset.query)}
                      onMouseLeave={handlePresetLeave}
                      className="inline-flex items-center gap-1.5 px-2 py-1 bg-white border border-gray-200 rounded-full text-xs font-medium text-gray-700 hover:bg-gray-50 hover:border-gray-300 transition-colors"
                    >
                      <IconComponent className="h-3 w-3 text-blue-500" />
                      {preset.label}
                    </button>
                  );
                })}
              </div>
              <div className="relative overflow-hidden rounded-md border bg-background focus-within:ring-1 focus-within:ring-ring">
                <fieldset>
                  <Textarea
                    className="h-[10rem] resize-none border-0 p-2 shadow-none focus-visible:ring-0 text-xs font-mono"
                    placeholder={placeholderText}
                    value={isPresetHovered ? '' : newAttribute}
                    onChange={(e) => setNewAttribute(e.target.value)}
                    disabled={isEnhancingQuery}
                    onKeyDown={(
                      e: React.KeyboardEvent<HTMLTextAreaElement>
                    ) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleSearch();
                      }
                    }}
                  />
                  <div className="flex items-center justify-end p-2">
                    {/* <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="gap-1 h-8 text-xs mr-2"
                      onClick={handleAutoEnhance}
                      disabled={!newAttribute.trim() || isEnhancingQuery}
                    >
                      {isEnhancingQuery ? (
                        <>
                          <Loader2 className="size-3 animate-spin" />
                          Enhancing...
                        </>
                      ) : (
                        <>
                          Auto-enhance prompt
                          <Wand2 className="size-3" />
                        </>
                      )}
                    </Button> */}
                    <Button
                      type="button"
                      size="sm"
                      className="gap-1 h-8 text-xs"
                      onClick={handleSearch}
                      disabled={!newAttribute.trim()}
                    >
                      Search
                      <CornerDownLeft className="size-3" />
                    </Button>
                  </div>
                </fieldset>
              </div>

              {/* Search History Section - Always visible when there are items */}
              {fg.searchHistory.length > 0 && (
                <div className="max-h-[5rem] overflow-y-auto pr-1">
                  <div className="flex justify-between items-center mb-1">
                    <div className="text-xs font-medium text-gray-500">
                      Recent Searches
                    </div>
                  </div>
                  {fg.searchHistory.map((query, index) => (
                    <div
                      key={index}
                      className="group flex items-center gap-1.5 p-1 rounded-md hover:bg-gray-100 cursor-pointer text-xs"
                      onClick={() => setNewAttribute(query)}
                    >
                      <Clock className="h-3 w-3 text-gray-400 flex-shrink-0" />
                      <div
                        className="font-mono text-gray-700 truncate flex-1"
                        title={query}
                      >
                        {query}
                      </div>
                      <button
                        className="opacity-0 group-hover:opacity-100 transition-opacity p-0.5 hover:bg-gray-200 rounded"
                        onClick={(e) => {
                          e.stopPropagation();
                          // Update the context's search history instead of local state
                          const newHistory = [...fg.searchHistory];
                          newHistory.splice(index, 1);
                          // Use the context's setSearchHistory function
                          fg.setSearchHistory(newHistory);
                        }}
                      >
                        <XOctagon className="h-3 w-3 text-red-500" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <ClusterProposalDialog
        isOpen={!!fg.clusterProposals && !!fg.clusterSessionId}
        onClose={handleCloseClusterDialog}
        proposals={fg.clusterProposals || []}
        clusterSessionId={fg.clusterSessionId || ''}
      />
    </div>
  );
};

export default AttributeFinder;
