import { FrameFilter, FramePredicate, Judgment } from '@/app/types/docent';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ChevronDown, ChevronRight, Pencil, Trash2, X } from 'lucide-react';
import React, { useEffect, useState } from 'react';
import { useFrameGrid } from '../contexts/FrameGridContext';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

interface BinEditorProps {
  bin: FrameFilter;
  marginalJudgments?: (Judgment | null)[][];
  onSubmit: (text: string) => void;
  onDelete: () => void;
  onShowDatapoint: (datapointId: string, blockId?: number) => void;
  loading?: boolean;
}

function countUniqueDatapoints(judgments: (Judgment | null)[][]): number {
  const uniqueDataIds = new Set<string>();
  judgments.forEach((row) => {
    row.forEach((judgment) => {
      if (judgment && judgment.matches) {
        uniqueDataIds.add(judgment.data_id);
      }
    });
  });
  return uniqueDataIds.size;
}

function countTotalAttributes(judgments: (Judgment | null)[][]): number {
  let attributeCount = 0;
  judgments.forEach((row) => {
    row.forEach((judgment) => {
      if (judgment && judgment.matches) {
        attributeCount++;
      }
    });
  });
  return attributeCount;
}

const JudgmentList: React.FC<{
  binId: string;
  judgments: (Judgment | null)[][];
  onShowDatapoint: (datapointId: string, blockId?: number) => void;
}> = ({ binId, judgments, onShowDatapoint }) => {
  const fg = useFrameGrid();
  const { isConnected, sendMessage } = fg;
  const [showOnlyMatches, setShowOnlyMatches] = useState(true);
  const [filteredJudgments, setFilteredJudgments] =
    useState<(Judgment | null)[][]>();
  const [attributesLoading, setAttributesLoading] = useState<boolean>(false);

  useEffect(() => {
    setFilteredJudgments(
      showOnlyMatches
        ? judgments.map((row) => row.filter((j) => j && j.matches))
        : judgments
    );
  }, [judgments]);

  const renderAttributeValue = (value: string, dataId: string) => {
    const blockPattern = /B(\d+)/g;
    const parts: (string | JSX.Element)[] = [];
    let lastIndex = 0;
    let match;
    let partIndex = 0;

    while ((match = blockPattern.exec(value)) !== null) {
      // Add text before the match
      if (match.index > lastIndex) {
        parts.push(
          <span key={`text-${partIndex}`}>
            {value.slice(lastIndex, match.index)}
          </span>
        );
        partIndex++;
      }

      // Add the clickable block reference
      const blockIndex = parseInt(match[1], 10);
      parts.push(
        <button
          key={`block-ref-${partIndex}`}
          onClick={(e) => {
            e.stopPropagation(); // Prevent triggering the parent div's onClick
            if (onShowDatapoint) {
              onShowDatapoint(dataId, blockIndex);
            }
          }}
          className="px-0.5 py-0.25 bg-indigo-200 text-indigo-800 rounded hover:bg-indigo-400 hover:text-white transition-colors font-medium"
        >
          {match[0]}
        </button>
      );
      partIndex++;

      lastIndex = blockPattern.lastIndex;
    }

    // Add any remaining text
    if (lastIndex < value.length) {
      parts.push(
        <span key={`text-${partIndex}`}>{value.slice(lastIndex)}</span>
      );
    }

    return parts;
  };

  return (
    <div className="space-y-2">
      {attributesLoading ? (
        <div className="flex items-center justify-center py-8">
          <div className="animate-spin rounded-full h-3 w-3 border-2 border-gray-400 border-t-transparent" />
        </div>
      ) : (
        <div className="mt-2 space-y-1">
          <div className="flex items-center mb-1">
            <div className="h-2 w-2 rounded-full bg-indigo-500 mr-1.5"></div>
            <span className="text-xs font-medium text-indigo-700">
              Matching attributes
            </span>
          </div>

          {filteredJudgments &&
            filteredJudgments.map((row, i) =>
              row.map((judgment, j) => {
                if (!judgment) return null;
                const attrList = fg.attributeMap.get(judgment.data_id);
                const attributeIdList = attrList?.get(judgment.attribute_id);
                const attributeValue = attributeIdList
                  ? attributeIdList[judgment.attribute_idx]?.attribute || ''
                  : '';

                return (
                  <div
                    key={`${i}-${j}`}
                    className={`group bg-indigo-50 rounded-md p-1.5 text-xs text-indigo-900 leading-snug mt-1 hover:bg-indigo-100 transition-colors cursor-pointer border border-transparent hover:border-indigo-200`}
                    onClick={() => {
                      onShowDatapoint(judgment.data_id);
                      // If there's a block citation in the attribute value, scroll to the first one
                      if (attributeValue) {
                        const match = attributeValue.match(/B(\d+)/);
                        if (match && onShowDatapoint) {
                          const blockIndex = parseInt(match[1], 10);
                          onShowDatapoint(judgment.data_id, blockIndex);
                        }
                      }
                    }}
                  >
                    {attributeValue !== undefined && (
                      <p className="mb-0.5">
                        {renderAttributeValue(attributeValue, judgment.data_id)}
                      </p>
                    )}
                    <div className="flex items-center gap-1 text-[10px] text-indigo-600 mt-1">
                      <span className="opacity-70">
                        {judgment.attribute_id}
                        {judgment.attribute_idx !== null && (
                          <>, idx: {judgment.attribute_idx}</>
                        )}
                      </span>
                      <span className="ml-1 opacity-70">
                        data_id: {judgment.data_id}
                      </span>
                    </div>
                  </div>
                );
              })
            )}
        </div>
      )}
    </div>
  );
};

export default function BinEditor({
  bin,
  marginalJudgments,
  onSubmit,
  onDelete,
  onShowDatapoint,
  loading,
}: BinEditorProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [text, setText] = useState(
    'predicate' in bin ? (bin as FramePredicate).predicate : bin.id
  );

  const hasJudgments = marginalJudgments && marginalJudgments.length > 0;
  const matchCount = hasJudgments ? countTotalAttributes(marginalJudgments) : 0;

  if (isEditing) {
    return (
      <div className="flex items-center gap-2">
        <Input
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="h-6 text-xs"
          autoFocus
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              onSubmit(text);
              setIsEditing(false);
            } else if (e.key === 'Escape') {
              setIsEditing(false);
              setText(
                'predicate' in bin ? (bin as FramePredicate).predicate : bin.id
              );
            }
          }}
        />
        <div className="flex gap-1 shrink-0">
          <Button
            size="icon"
            variant="ghost"
            className="h-6 w-6"
            onClick={() => setIsEditing(false)}
          >
            <X className="h-3 w-3" />
          </Button>
          <Button
            variant="default"
            className="h-6 px-2 text-xs"
            onClick={() => {
              onSubmit(text);
              setIsEditing(false);
            }}
          >
            Save
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="text-xs p-1.5 bg-white rounded border border-gray-200 flex items-center gap-1.5">
        {/* Expand/collapse button on the left */}
        {hasJudgments && (
          <Button
            size="icon"
            variant="ghost"
            className="h-5 w-5 flex-shrink-0"
            onClick={() => setIsExpanded(!isExpanded)}
          >
            {isExpanded ? (
              <ChevronDown className="h-3 w-3 text-gray-500" />
            ) : (
              <ChevronRight className="h-3 w-3 text-gray-500" />
            )}
          </Button>
        )}

        {/* Match count at the beginning */}
        {(hasJudgments || loading) && (
          <div className="flex-shrink-0 flex items-center">
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="text-xs px-1.5 py-0.5 rounded-sm bg-gray-100 text-gray-600 cursor-default flex items-center">
                    {loading && (!hasJudgments || matchCount === 0) ? (
                      <div className="animate-spin rounded-full h-3 w-3 border-2 border-gray-300 border-t-gray-500" />
                    ) : (
                      <>
                        {matchCount}
                        {loading && (
                          <div className="animate-spin ml-1 rounded-full h-2 w-2 border-[1.5px] border-gray-300 border-t-gray-500 inline-block" />
                        )}
                      </>
                    )}
                  </span>
                </TooltipTrigger>
                <TooltipContent side="top" className="text-xs">
                  {loading && (!hasJudgments || matchCount === 0)
                    ? 'Loading attributes...'
                    : `${matchCount} matching attribute${matchCount !== 1 ? 's' : ''}`}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        )}

        {/* Bin ID */}
        <div className="flex-1 text-xs text-gray-700 ml-1">{bin.id}</div>

        {/* Action buttons on the right */}
        <Button
          size="icon"
          variant="ghost"
          className="h-5 w-5 text-gray-500"
          onClick={() => setIsEditing(true)}
          disabled={loading}
        >
          <Pencil className="h-3 w-3" />
        </Button>
        <Button
          size="icon"
          variant="ghost"
          className="h-5 w-5 text-gray-500"
          onClick={() => onDelete()}
          disabled={loading}
        >
          <Trash2 className="h-3 w-3" />
        </Button>
      </div>
      {isExpanded && marginalJudgments && (
        <div className="pl-4">
          <JudgmentList
            binId={bin.id}
            judgments={marginalJudgments}
            onShowDatapoint={onShowDatapoint}
          />
        </div>
      )}
    </div>
  );
}
