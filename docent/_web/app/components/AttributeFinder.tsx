import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { toast } from '@/hooks/use-toast';
import {
  AlertTriangle,
  CircleX,
  Clock,
  CornerDownLeft,
  Earth,
  HelpCircle,
  Loader2,
  Pencil,
  RefreshCw,
  Share2,
  Sparkles,
  XOctagon,
} from 'lucide-react';
import { useEffect, useState, useCallback } from 'react';
import type { MetadataType, PrimitiveFilter } from '@/app/types/frameTypes';
import BinEditor from './BinEditor';
import {
  addBaseFilter,
  clearAttributeQuery,
  clearBaseFilters,
  removeBaseFilter,
  requestAttributes,
  requestClusters,
  cancelCurrentClusterRequest,
  setAttributeQueryTextboxValue,
  setCurAttributeQuery,
  setAttributeQueryDimId,
} from '../store/attributeFinderSlice';
import { useAppDispatch } from '../store/hooks';
import { useSelector } from 'react-redux';
import { RootState } from '../store/store';
import {
  addAttributeDimension,
  deleteDimension,
  deleteFilter,
} from '../store/frameSlice';

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
  const dispatch = useAppDispatch();

  const frameGridId = useSelector(
    (state: RootState) => state.frame.frameGridId
  );
  const dimensions = useSelector((state: RootState) => state.frame.dimensions);
  const baseFilter = useSelector((state: RootState) => state.frame.baseFilter);
  const transcriptMetadataFields = useSelector(
    (state: RootState) => state.frame.transcriptMetadataFields
  );
  const marginals = useSelector((state: RootState) => state.frame.marginals);
  const curAttributeQuery = useSelector(
    (state: RootState) => state.attributeFinder.curAttributeQuery
  );
  const loadingAttributesForId = useSelector(
    (state: RootState) => state.attributeFinder.loadingAttributesForId
  );
  const loadingProgress = useSelector(
    (state: RootState) => state.attributeFinder.loadingProgress
  );
  const searchHistory = useSelector(
    (state: RootState) => state.attributeFinder.searchHistory
  );
  const attributeSearches = useSelector(
    (state: RootState) => state.attributeFinder.attributeSearches
  );
  const attributeQueryTextboxValue = useSelector(
    (state: RootState) => state.attributeFinder.attributeQueryTextboxValue
  );
  const [metadataKey, setMetadataKey] = useState('');
  const [metadataValue, setMetadataValue] = useState('');
  const [metadataType, setMetadataType] = useState<MetadataType | undefined>(
    undefined
  );
  const [metadataOp, setMetadataOp] = useState<string>('==');
  const [isEnhancingQuery, setIsEnhancingQuery] = useState(false);
  const [placeholderText, setPlaceholderText] = useState(
    DEFAULT_PLACEHOLDER_TEXT
  );
  const [clusterFeedback, setClusterFeedback] = useState('');
  const [showFeedbackInput, setShowFeedbackInput] = useState(false);

  // Find the active dimension state based on the current attribute query
  const attributeQueryDimId = useSelector(
    (state: RootState) => state.attributeFinder.attributeQueryDimId
  );
  const activeDim =
    curAttributeQuery && dimensions
      ? dimensions.find((dim) => dim.id === attributeQueryDimId)
      : null;

  // Metadata filter manipulation
  const onUpdateMetadataFilter = useCallback(() => {
    if (!frameGridId) return;

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

      dispatch(clearAttributeQuery());
      dispatch(
        addBaseFilter({
          type: 'primitive',
          key_path: parsedKey.split('.'),
          value: parsedValue,
          op: metadataOp,
        } as PrimitiveFilter)
      );
    }

    // Reset form
    setMetadataKey('');
    setMetadataValue('');
  }, [
    metadataValue,
    metadataType,
    metadataKey,
    metadataOp,
    dispatch,
    frameGridId,
  ]);

  // Auto-submit when a value is selected from a dropdown
  useEffect(() => {
    if (metadataType === 'bool' && metadataValue && metadataKey) {
      onUpdateMetadataFilter();
    }
  }, [metadataValue, metadataType, metadataKey, onUpdateMetadataFilter]);

  const handleSearch = () => {
    if (!attributeQueryTextboxValue?.trim()) {
      toast({
        title: 'Missing search query',
        description: 'Please enter a search query',
        variant: 'destructive',
      });
      return;
    }

    // Search history is now handled in the context via requestAttributes
    const trimmedQuery = attributeQueryTextboxValue.trim();
    dispatch(requestAttributes(trimmedQuery));

    // Reset form
    dispatch(setAttributeQueryTextboxValue(''));
  };

  const handleEditAttribute = () => {
    if (activeDim) {
      dispatch(setAttributeQueryTextboxValue(activeDim.attribute || ''));
      dispatch(clearAttributeQuery());
    }
  };

  const handleRequestClusters = () => {
    if (!activeDim) return;

    // If bins exist and feedback is not being shown yet, show the feedback input
    if (activeDim.bins && activeDim.bins.length > 0 && !showFeedbackInput) {
      setShowFeedbackInput(true);
      return;
    }

    // Use the context's requestClusters function
    dispatch(
      requestClusters({ dimensionId: activeDim.id, feedback: clusterFeedback })
    );

    // Clear feedback after sending and hide the input
    setClusterFeedback('');
    setShowFeedbackInput(false);
  };

  const handleCancelFeedback = () => {
    setShowFeedbackInput(false);
    setClusterFeedback('');
  };

  const [isPresetHovered, setIsPresetHovered] = useState(false);

  const handleSelectPreset = (query: string) => {
    dispatch(setAttributeQueryTextboxValue(query));
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
          {baseFilter && baseFilter.filters.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-2">
              {baseFilter.filters.map((subFilter) => (
                <div
                  key={subFilter.id}
                  className="inline-flex items-center gap-x-1 text-xs bg-indigo-50 text-indigo-800 border border-indigo-100 pl-1.5 pr-1 py-0.5 rounded-md"
                >
                  {(() => {
                    if (subFilter.type === 'primitive') {
                      const filterCast = subFilter as PrimitiveFilter;
                      return (
                        <>
                          <span className="">
                            {filterCast.key_path.join('.')}
                          </span>
                          <span className="text-indigo-400">
                            {filterCast.op || '=='}
                          </span>
                          <span className="font-mono">
                            {String(filterCast.value)}
                          </span>
                        </>
                      );
                    } else {
                      return `${subFilter.type} filter`;
                    }
                  })()}
                  <button
                    onClick={() => dispatch(removeBaseFilter(subFilter.id))}
                    className="ml-0.5 hover:bg-indigo-100 rounded-full p-0.5 text-indigo-400 hover:text-indigo-600 transition-colors"
                  >
                    <CircleX size={12} />
                  </button>
                </div>
              ))}
              <button
                onClick={() => dispatch(clearBaseFilters())}
                className="inline-flex items-center gap-x-1 text-xs bg-red-50 text-red-500 border border-red-100 px-1.5 py-0.5 rounded-md hover:bg-red-100 transition-colors"
              >
                <RefreshCw className="h-3 w-3 mr" />
                Clear
              </button>
            </div>
          )}
          <div className="grid grid-cols-[1fr_auto_1fr_auto] gap-2">
            <div className="space-y-1">
              <div className="text-xs text-gray-600">Filter by</div>
              <Select
                value={metadataKey}
                onValueChange={(value: string) => {
                  setMetadataKey(value);
                  const selectedField = transcriptMetadataFields?.find(
                    (f) => f.name === value
                  );
                  if (selectedField) {
                    setMetadataType(selectedField.type);
                    setMetadataValue('');
                    // Reset operator to == when changing fields if not text, else '~*'
                    setMetadataOp(selectedField.name === 'text' ? '~*' : '==');
                  }
                }}
              >
                <SelectTrigger className="h-8 text-xs bg-white font-mono text-gray-600">
                  <SelectValue placeholder="Select field" />
                </SelectTrigger>
                <SelectContent>
                  {transcriptMetadataFields?.map((field) => (
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
            {metadataType === 'int' || metadataType === 'float' ? (
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
            ) : (
              <div className="space-y-1">
                <div className="text-xs text-gray-600">Operator</div>
                <Select value={metadataOp} onValueChange={setMetadataOp}>
                  <SelectTrigger className="h-8 text-xs bg-white font-mono text-gray-600 w-16">
                    <SelectValue placeholder="==" />
                  </SelectTrigger>
                  <SelectContent>
                    {metadataType === 'str' && (
                      <SelectItem value="~*" className="font-mono text-xs">
                        ~*
                      </SelectItem>
                    )}
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
                Value{metadataType ? ` (${metadataType})` : ''}
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
                  !frameGridId ||
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
          {activeDim ? (
            <div className="space-y-2">
              <div className="flex items-center">
                <div className="flex-1 px-2 py-1 bg-indigo-50 border border-indigo-100 rounded text-xs font-mono whitespace-pre-wrap text-indigo-800">
                  {activeDim.attribute}
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
                    onClick={() => dispatch(clearAttributeQuery())}
                    className="inline-flex items-center gap-x-1 text-xs bg-red-50 text-red-500 border border-red-100 px-1.5 py-0.5 rounded-md hover:bg-red-100 transition-colors"
                  >
                    <RefreshCw className="h-3 w-3 mr" />
                    Clear
                  </button>
                </div>
              </div>

              {/* Progress bar for attribute updates */}
              {loadingAttributesForId &&
                loadingAttributesForId === curAttributeQuery &&
                loadingProgress && (
                  <div className="mt-2 mb-2 space-y-1">
                    <div className="flex justify-between text-xs text-gray-600">
                      <span className="flex items-center">
                        Processing datapoints
                        <Loader2 className="h-3 w-3 ml-1.5 animate-spin text-gray-500" />
                      </span>
                      <span>
                        {loadingProgress[0]} / {loadingProgress[1]}
                      </span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-1.5">
                      <div
                        className="bg-blue-600 h-1.5 rounded-full transition-all duration-300 ease-in-out"
                        style={{
                          width: `${
                            loadingProgress[1] > 0
                              ? Math.min(
                                  (loadingProgress[0] / loadingProgress[1]) *
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
                  !frameGridId ||
                  activeDim.loading_clusters ||
                  activeDim.loading_marginals ||
                  (loadingAttributesForId === curAttributeQuery &&
                    loadingAttributesForId !== null) ||
                  showFeedbackInput // Disable button when feedback input is visible
                }
              >
                {activeDim.loading_clusters ? (
                  <Loader2 className="h-3 w-3 mr-2 animate-spin" />
                ) : (
                  <Sparkles className="h-3 w-3 mr-2" />
                )}
                {activeDim.bins && activeDim.bins.length > 0
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
              {activeDim.bins && activeDim.bins.length > 0 && (
                <div className="space-y-2 mt-3">
                  <div className="text-xs text-gray-600 font-medium">
                    Clusters
                  </div>
                  {activeDim.bins.map((bin) => (
                    <BinEditor
                      key={bin.id}
                      bin={bin}
                      loading={activeDim.loading_marginals || false}
                      marginalJudgments={
                        marginals?.[activeDim.id]?.[bin.id] || undefined
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
                    value={isPresetHovered ? '' : attributeQueryTextboxValue}
                    onChange={(e) =>
                      dispatch(setAttributeQueryTextboxValue(e.target.value))
                    }
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
                    <Button
                      type="button"
                      size="sm"
                      className="gap-1 h-8 text-xs"
                      onClick={handleSearch}
                      disabled={!attributeQueryTextboxValue?.trim()}
                    >
                      Search
                      <CornerDownLeft className="size-3" />
                    </Button>
                  </div>
                </fieldset>
              </div>

              {/* Search History Section - Updated with consistent colors */}
              {attributeSearches && attributeSearches.length > 0 && (
                <div className="max-h-[20rem] overflow-y-auto pr-1">
                  <div className="flex justify-between items-center mb-1">
                    <div className="text-xs font-medium text-gray-500">
                      Saved Searches
                    </div>
                  </div>
                  {attributeSearches.map((search, index) => {
                    const completionPercentage =
                      search.num_total > 0
                        ? Math.min(
                            (search.num_judgments_computed / search.num_total) *
                              100,
                            100
                          )
                        : 0;
                    const isComplete = completionPercentage === 100;
                    // Extract first 8 characters of UUID for display
                    const shortDimId = search.dim_id.split('-')[0];

                    return (
                      <div
                        key={index}
                        className="group mb-1 border border-gray-100 rounded hover:border-indigo-300 hover:bg-indigo-50 transition-all"
                      >
                        <div className="flex items-center py-1.5 px-2 text-xs bg-white">
                          <code
                            className="px-1 bg-gray-50 border border-gray-100 rounded text-[10px] text-gray-500 mr-2 flex-shrink-0"
                            title={search.dim_id}
                          >
                            {shortDimId}
                          </code>
                          <div
                            className="font-mono text-gray-800 truncate flex-1 cursor-pointer"
                            title={search.attribute}
                            onClick={() => {
                              dispatch(
                                setAttributeQueryTextboxValue(search.attribute)
                              );
                            }}
                          >
                            {search.attribute}
                          </div>
                          <div className="flex items-center ml-2 space-x-1.5 flex-shrink-0">
                            <div className="flex items-center gap-1.5">
                              <div
                                className="relative w-12 h-1.5 bg-gray-100 rounded-full overflow-hidden flex-shrink-0"
                                title={`${search.num_judgments_computed} of ${search.num_total} processed`}
                              >
                                <div
                                  className={`absolute top-0 left-0 h-full ${isComplete ? 'bg-indigo-500' : 'bg-blue-500'}`}
                                  style={{ width: `${completionPercentage}%` }}
                                ></div>
                              </div>
                              <span className="text-[9px] text-gray-500 whitespace-nowrap">
                                {Math.round(completionPercentage)}% computed
                              </span>
                            </div>
                            <button
                              className="hover:bg-indigo-50 rounded p-0.5 text-indigo-400 hover:text-indigo-600 transition-colors"
                              onClick={(e) => {
                                e.stopPropagation();
                                // No action for now
                              }}
                              title="Share this search"
                            >
                              <Share2 className="h-3 w-3" />
                            </button>
                            <button
                              className="hover:bg-red-50 rounded p-0.5 text-red-400 hover:text-red-600 transition-colors"
                              onClick={async (e) => {
                                e.stopPropagation();
                                await dispatch(deleteDimension(search.dim_id))
                                  .unwrap()
                                  .then(() => {
                                    toast({
                                      title: 'Deleted saved search',
                                      description:
                                        'Your saved search has been deleted successfully',
                                      variant: 'default',
                                    });
                                  });
                              }}
                              title="Delete this saved search"
                            >
                              <XOctagon className="h-3 w-3" />
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default AttributeFinder;
