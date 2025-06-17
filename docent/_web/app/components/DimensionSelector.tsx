import { ArrowLeftRight } from 'lucide-react';
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
  setIODims,
  setIODimByMetadataKey,
} from '../store/experimentViewerSlice';
import { useAppDispatch, useAppSelector } from '../store/hooks';

interface DimensionSelectorProps {
  className?: string;
}

export default function DimensionSelector({
  className,
}: DimensionSelectorProps) {
  const dispatch = useAppDispatch();

  const {
    innerDimId,
    outerDimId,
    dimensionsMap,
    agentRunMetadataFields = [],
  } = useAppSelector((state) => state.frame);

  const selectedInnerMetadataKey = useMemo(() => {
    return innerDimId && dimensionsMap?.[innerDimId]?.metadata_key;
  }, [dimensionsMap, innerDimId]);

  const selectedOuterMetadataKey = useMemo(() => {
    return outerDimId && dimensionsMap?.[outerDimId]?.metadata_key;
  }, [dimensionsMap, outerDimId]);

  const handleInnerDimChange = (value: string) => {
    if (value === 'None') {
      dispatch(setIODims({ innerDimId: undefined, outerDimId }));
    } else {
      dispatch(setIODimByMetadataKey({ metadataKey: value, type: 'inner' }));
    }
  };

  const handleOuterDimChange = (value: string) => {
    if (value === 'None') {
      dispatch(setIODims({ innerDimId, outerDimId: undefined }));
    } else {
      dispatch(setIODimByMetadataKey({ metadataKey: value, type: 'outer' }));
    }
  };

  const handleSwapDimensions = () => {
    if (innerDimId && outerDimId) {
      // Swap the dimensions using a single dispatch
      dispatch(
        setIODims({
          innerDimId: outerDimId,
          outerDimId: innerDimId,
        })
      );
    }
  };

  const showSwapButton =
    selectedInnerMetadataKey &&
    selectedOuterMetadataKey &&
    selectedOuterMetadataKey !== 'None';

  return (
    <div
      className={`flex flex-col lg:flex-row items-start sm:items-center gap-2 ${className || ''}`}
    >
      <div className="flex items-center space-x-1">
        <div className="flex items-center space-x-1">
          <span className="text-xs text-gray-500">Outer:</span>
          <Select
            value={selectedOuterMetadataKey || 'None'}
            onValueChange={handleOuterDimChange}
          >
            <SelectTrigger className="h-6 max-w-24 text-xs border-gray-200 bg-transparent hover:bg-gray-50 px-2 font-normal">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="None" className="text-xs">
                None
              </SelectItem>
              {agentRunMetadataFields
                .filter((field) => field.name.startsWith('metadata.')) // FIXME(mengk): FIX THIS HACK!!!
                .filter((field) => !field.name.includes('run_id')) // Filter out run_id because too high cardinality
                .map((field) => (
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

          {showSwapButton && (
            <Button
              variant="ghost"
              size="icon"
              className="h-6 px-0 rounded-full bg-gray-100 hover:bg-gray-200 transition-all duration-200 text-gray-500 hover:text-gray-800"
              onClick={handleSwapDimensions}
              title="Swap dimensions"
            >
              <ArrowLeftRight size={14} className="stroke-[1.5]" />
            </Button>
          )}

          <span className="text-xs text-gray-500">Inner:</span>
          <Select
            value={selectedInnerMetadataKey || 'None'}
            onValueChange={handleInnerDimChange}
          >
            <SelectTrigger className="h-6 max-w-24 text-xs border-gray-200 bg-transparent hover:bg-gray-50 px-2 font-normal">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {/* Do not allow a None option here */}
              {agentRunMetadataFields
                .filter((field) => field.name.startsWith('metadata.')) // FIXME(mengk): FIX THIS HACK!!!
                .filter((field) => !field.name.includes('run_id')) // Filter out run_id because too high cardinality
                .map((field) => (
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
        </div>
      </div>
    </div>
  );
}
