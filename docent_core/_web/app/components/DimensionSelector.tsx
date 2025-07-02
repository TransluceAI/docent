import { ArrowLeftRight, RotateCcw } from 'lucide-react';
import React, { useMemo } from 'react';

import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

import {
  useSetIODimsMutation,
  useSetIODimByMetadataKeyMutation,
} from '../api/experimentViewerApi';
import { useAppSelector } from '../store/hooks';

interface DimensionSelectorProps {
  className?: string;
}

export default function DimensionSelector({
  className,
}: DimensionSelectorProps) {
  const [setIODims] = useSetIODimsMutation();
  const [setIODimByMetadataKey] = useSetIODimByMetadataKeyMutation();

  // Collection slice
  const collectionId = useAppSelector((state) => state.collection.collectionId);
  const innerBinKey = useAppSelector((state) => state.collection.innerBinKey);
  const outerBinKey = useAppSelector((state) => state.collection.outerBinKey);
  const agentRunMetadataFields =
    useAppSelector((state) => state.collection.agentRunMetadataFields) || [];

  // In the new system, innerBinKey and outerBinKey are metadata keys directly
  const innerDim = useMemo(() => {
    if (!innerBinKey) return null;
    return innerBinKey;
  }, [innerBinKey]);

  const outerDim = useMemo(() => {
    if (!outerBinKey) return null;
    return outerBinKey;
  }, [outerBinKey]);

  const handleInnerDimChange = (value: string) => {
    if (!collectionId) return;

    if (value === 'None') {
      setIODims({ collectionId, innerBinKey: undefined, outerBinKey });
    } else {
      setIODimByMetadataKey({ collectionId, metadataKey: value, type: 'inner' });
    }
  };

  const handleOuterDimChange = (value: string) => {
    if (!collectionId) return;

    if (value === 'None') {
      setIODims({ collectionId, innerBinKey, outerBinKey: undefined });
    } else {
      setIODimByMetadataKey({ collectionId, metadataKey: value, type: 'outer' });
    }
  };

  const handleSwapDimensions = () => {
    if (!collectionId || !innerBinKey || !outerBinKey) return;

    setIODims({
      collectionId,
      innerBinKey: outerBinKey,
      outerBinKey: innerBinKey,
    });
  };

  const handleClearDimensions = () => {
    if (!collectionId) return;

    setIODims({ collectionId, innerBinKey: undefined, outerBinKey: undefined });
  };

  const showSwapButton = innerDim && outerDim && outerDim !== 'None';

  const showClearButton =
    (innerDim && innerDim !== 'None') || (outerDim && outerDim !== 'None');

  const filteredAgentRunMetadataFields = useMemo(() => {
    const fields = agentRunMetadataFields || [];
    return fields.filter((field) =>
      field.name.startsWith('metadata.')
    ); // FIXME(mengk): FIX THIS HACK!!!
    // .filter((field) => !field.name.includes('run_id')) // Filter out run_id because too high cardinality
  }, [agentRunMetadataFields]);

  return (
    <div
      className={`flex flex-col lg:flex-row items-start sm:items-center gap-2 ${className || ''}`}
    >
      <div className="flex items-center space-x-1">
        <div className="flex items-center space-x-1">
          <span className="text-xs text-muted-foreground">Outer:</span>
          <Select
            value={outerDim || 'None'}
            onValueChange={handleOuterDimChange}
          >
            <SelectTrigger className="h-6 max-w-24 w-24 text-xs border-border bg-transparent hover:bg-secondary px-2 font-normal">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="None" className="text-xs">
                None
              </SelectItem>
              {filteredAgentRunMetadataFields.map((field) => (
                <SelectItem
                  key={field.name}
                  value={field.name.replace('metadata.', '')} // FIXME(mengk): FIX THIS HACK!!!
                  className="text-xs"
                >
                  {field.name.replace('metadata.', '')}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Button
            variant="ghost"
            size="icon"
            className="h-6 px-1 w-6 hover:bg-accent transition-all duration-200 text-muted-foreground hover:text-primary"
            onClick={handleSwapDimensions}
            title="Swap dimensions"
            disabled={!showSwapButton}
          >
            <ArrowLeftRight size={14} className="stroke-[1.5]" />
          </Button>

          <span className="text-xs text-muted-foreground">Inner:</span>
          <Select
            value={innerDim || 'None'}
            onValueChange={handleInnerDimChange}
          >
            <SelectTrigger className="h-6 max-w-24 text-xs w-24 border-border bg-transparent hover:bg-secondary px-2 font-normal">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="None" className="text-xs">
                None
              </SelectItem>
              {filteredAgentRunMetadataFields.map((field) => (
                <SelectItem
                  key={field.name}
                  value={field.name.replace('metadata.', '')} // FIXME(mengk): FIX THIS HACK!!!
                  className="text-xs"
                >
                  {field.name.replace('metadata.', '')}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 px-1 w-6 hover:bg-accent transition-all duration-200 text-muted-foreground hover:text-primary"
                onClick={handleClearDimensions}
                disabled={!showClearButton}
              >
                <RotateCcw size={14} className="stroke-[1.5]" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">
              <p>Clear selected keys</p>
            </TooltipContent>
          </Tooltip>
        </div>
      </div>
    </div>
  );
}
