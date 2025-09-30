'use client';

import React, { useState, useEffect, useMemo, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import * as SliderPrimitive from '@radix-ui/react-slider';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useDebounce } from '@/hooks/use-debounce';
import { useGetMetadataFieldRangeQuery } from '@/app/api/collectionApi';

interface StepFilterProps {
  collectionId: string;
  metadataData: Record<string, Record<string, unknown>>;
  onStepFilterChange: (stepValue: number | null) => void;
  currentValue?: number | null;
  disabled?: boolean;
}

export const StepFilter: React.FC<StepFilterProps> = ({
  collectionId,
  metadataData,
  onStepFilterChange,
  currentValue = null,
  disabled = false,
}) => {
  const [stepValue, setStepValue] = useState<number | null>(null);
  const [inputValue, setInputValue] = useState<string>('');
  const previousDebouncedValue = useRef<number | null>(null);

  // Debounce the step value changes to avoid too many API calls
  const debouncedStepValue = useDebounce(stepValue, 75);

  const { data: metadataRangeData } = useGetMetadataFieldRangeQuery(
    { collectionId, fieldName: 'metadata.step' },
    { skip: !collectionId }
  );

  // Calculate min and max step values from locally loaded metadata as fallback
  const localStepRange = useMemo(() => {
    const stepValues: number[] = [];

    Object.values(metadataData).forEach((record) => {
      const stepValue = record['metadata.step'];
      if (typeof stepValue === 'number' && Number.isInteger(stepValue)) {
        stepValues.push(stepValue);
      }
    });

    if (stepValues.length === 0) {
      return { min: 0, max: 100, hasStepData: false };
    }

    return {
      min: Math.min(...stepValues),
      max: Math.max(...stepValues),
      hasStepData: true,
    };
  }, [metadataData]);

  const apiStepRange = useMemo(() => {
    if (!metadataRangeData) {
      return null;
    }

    const { min, max } = metadataRangeData;
    if (min === null || max === null) {
      return null;
    }

    const normalizedMin = Math.floor(min);
    const normalizedMax = Math.ceil(max);

    if (!Number.isFinite(normalizedMin) || !Number.isFinite(normalizedMax)) {
      return null;
    }

    return {
      min: normalizedMin,
      max: normalizedMax,
      hasStepData: true,
    };
  }, [metadataRangeData]);

  const stepRange = useMemo(() => {
    if (apiStepRange) {
      return apiStepRange;
    }

    if (localStepRange.hasStepData) {
      return localStepRange;
    }

    if (currentValue !== null) {
      return {
        min: currentValue,
        max: currentValue,
        hasStepData: true,
      };
    }

    return localStepRange;
  }, [apiStepRange, localStepRange, currentValue]);

  // Check if step filter should be shown
  const shouldShowStepFilter = stepRange.hasStepData;

  // Sync internal state with currentValue prop
  useEffect(() => {
    setStepValue(currentValue);
  }, [currentValue]);

  // Update input value when step value changes
  useEffect(() => {
    if (stepValue !== null) {
      setInputValue(stepValue.toString());
    } else {
      setInputValue('');
    }
  }, [stepValue]);

  // Call onChange handler only when debounced value actually changes
  useEffect(() => {
    // Only call onChange if the debounced value has actually changed
    if (debouncedStepValue !== previousDebouncedValue.current) {
      previousDebouncedValue.current = debouncedStepValue;
      onStepFilterChange(debouncedStepValue);
    }
  }, [debouncedStepValue, onStepFilterChange]);

  // Handle slider change
  const handleSliderChange = (value: number[]) => {
    const newValue = value[0];
    setStepValue(newValue);
  };

  // Handle input change
  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setInputValue(value);

    // Parse and validate the input
    const numValue = parseInt(value, 10);
    if (value === '') {
      setStepValue(null);
    } else if (
      !isNaN(numValue) &&
      Number.isInteger(numValue) &&
      numValue >= stepRange.min &&
      numValue <= stepRange.max
    ) {
      setStepValue(numValue);
    }
  };

  // Handle input blur - reset to valid value if invalid
  const handleInputBlur = () => {
    if (
      inputValue !== '' &&
      (stepValue === null || inputValue !== stepValue.toString())
    ) {
      setInputValue(stepValue?.toString() || '');
    }
  };

  // Clear the filter
  const handleClear = () => {
    setStepValue(null);
    setInputValue('');
  };

  // Don't render if no step data is available
  if (!shouldShowStepFilter) {
    return null;
  }

  const clampToRange = (value: number) => {
    if (!stepRange.hasStepData) {
      return value;
    }
    return Math.min(Math.max(value, stepRange.min), stepRange.max);
  };

  const sliderValue =
    stepValue !== null ? clampToRange(stepValue) : stepRange.min;

  const isEnabled = stepValue !== null;

  return (
    <div className="space-y-2">
      {/* Slider and Text input in a row */}
      <div className="flex items-center gap-2">
        <div className="text-xs text-muted-foreground font-mono min-w-0">
          Step:
        </div>
        <div className="flex-1 pt-5">
          <div className="relative">
            <div className="px-1">
              <SliderPrimitive.Root
                value={[sliderValue]}
                onValueChange={handleSliderChange}
                min={stepRange.min}
                max={stepRange.max}
                step={1}
                disabled={disabled}
                className={cn(
                  'relative flex w-full touch-none select-none items-center',
                  disabled && 'opacity-50 cursor-not-allowed'
                )}
              >
                <SliderPrimitive.Track className="relative h-1.5 w-full grow overflow-hidden rounded-full bg-primary/20">
                  {/* No Range component - just the track */}
                </SliderPrimitive.Track>
                <SliderPrimitive.Thumb className="block h-4 w-4 rounded-full border border-primary/50 bg-background shadow transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50" />
              </SliderPrimitive.Root>
            </div>
            {/* Min and Max labels under slider ends */}
            <div className="flex justify-between mt-2 pl-1 pr-1">
              <div className="text-xs text-muted-foreground font-mono">
                {stepRange.min}
              </div>
              <div className="text-xs text-muted-foreground font-mono">
                {stepRange.max}
              </div>
            </div>
          </div>
        </div>

        <Input
          type="number"
          value={inputValue}
          onChange={handleInputChange}
          onBlur={handleInputBlur}
          placeholder={`${stepRange.min}-${stepRange.max}`}
          min={stepRange.min}
          max={stepRange.max}
          className={cn(
            'h-7 text-xs bg-background font-mono text-muted-foreground w-20',
            isEnabled && 'border-blue-border bg-blue-bg/20'
          )}
        />

        <div className="h-5 w-5 flex items-center justify-center">
          {isEnabled && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleClear}
              className="h-5 w-5 p-0 text-muted-foreground hover:text-primary"
            >
              <X className="h-3 w-3" />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
};
