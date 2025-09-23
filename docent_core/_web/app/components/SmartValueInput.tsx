'use client';

import React, {
  useState,
  useRef,
  useEffect,
  useCallback,
  useMemo,
} from 'react';
import { createPortal } from 'react-dom';
import { cn } from '@/lib/utils';

import { Input } from '@/components/ui/input';
import { useGetFieldValuesQuery } from '../api/collectionApi';
import { useDebounce } from '../../hooks/use-debounce';

// Styling constants for easy maintenance
const DROPDOWN_STYLES = {
  // Font properties that affect text measurement
  FONT_SIZE: '12px',
  FONT_FAMILY: 'monospace',

  // Spacing and sizing
  PADDING: 24, // px on each side
  MAX_WIDTH: 500, // px - reduced from 800px for better viewport fit
  MIN_DROPDOWN_OFFSET: 4, // px below input

  // Z-index for dropdown positioning
  Z_INDEX: 9999,

  // Dropdown appearance
  MAX_HEIGHT: '12rem', // 48 * 0.25rem = 12rem

  // Off-screen prevention
  VIEWPORT_EDGE_BUFFER: 8, // px from viewport edges
} as const;

interface SmartValueInputProps {
  collectionId: string;
  fieldName: string;
  value: string;
  onValueChange: (value: string) => void;
  onEnter?: () => void;
  placeholder?: string;
  className?: string;
  type?: 'text' | 'number';
}

// Helper function to measure text width consistently
const measureTextWidth = (text: string): number => {
  const span = document.createElement('span');
  span.style.fontSize = DROPDOWN_STYLES.FONT_SIZE;
  span.style.fontFamily = DROPDOWN_STYLES.FONT_FAMILY;
  span.style.visibility = 'hidden';
  span.style.position = 'absolute';
  span.style.whiteSpace = 'nowrap';
  span.textContent = text;
  document.body.appendChild(span);
  const width = span.getBoundingClientRect().width;
  document.body.removeChild(span);
  return width;
};

export const SmartValueInput = React.forwardRef<
  HTMLInputElement,
  SmartValueInputProps
>(
  (
    {
      collectionId,
      fieldName,
      value,
      onValueChange,
      onEnter,
      placeholder = 'Enter value...',
      className,
      type = 'text',
    },
    ref
  ) => {
    const [open, setOpen] = useState(false);
    const [inputValue, setInputValue] = useState(value);
    const [dropdownPosition, setDropdownPosition] = useState({
      top: 0,
      left: 0,
      width: 0,
    });
    const [dropdownWidth, setDropdownWidth] = useState(0);
    const inputRef = useRef<HTMLInputElement>(null);
    const blurTimeoutRef = useRef<NodeJS.Timeout>();

    // Debounce search to avoid too many API calls
    const debouncedSearch = useDebounce(inputValue, 300);

    // Only enable dropdown/search for metadata fields
    const isMetadataField = fieldName.startsWith('metadata.');

    const { data: fieldValuesData, isFetching } = useGetFieldValuesQuery(
      {
        collectionId,
        fieldName,
        search: debouncedSearch || undefined,
      },
      {
        skip: !collectionId || !fieldName || !isMetadataField,
      }
    );

    const values = fieldValuesData?.values || [];

    // Track the previous fieldName to detect field changes
    const prevFieldNameRef = useRef(fieldName);
    const [isFieldChanging, setIsFieldChanging] = useState(false);

    // Close dropdown when fieldName changes to prevent showing stale values
    useEffect(() => {
      if (prevFieldNameRef.current !== fieldName) {
        setOpen(false);
        setIsFieldChanging(true);
        prevFieldNameRef.current = fieldName;
      }
    }, [fieldName]);

    // Close dropdown immediately if field is not a metadata field
    useEffect(() => {
      if (!isMetadataField) {
        setOpen(false);
      }
    }, [isMetadataField]);

    // Reset field changing state when new data loads
    useEffect(() => {
      if (isFieldChanging && !isFetching && fieldValuesData) {
        setIsFieldChanging(false);
      }
    }, [isFieldChanging, isFetching, fieldValuesData]);

    const displayValues = useMemo(() => {
      if (isFieldChanging) {
        return [];
      }

      if (inputValue) {
        const clientFiltered = values.filter((val) =>
          val.toLowerCase().includes(inputValue.toLowerCase())
        );

        return clientFiltered;
      }

      // Default: use server results
      return values;
    }, [isFieldChanging, inputValue, values]);

    // Update input value when value prop changes
    useEffect(() => {
      setInputValue(value);
    }, [value]);

    // Cleanup timeout on unmount
    useEffect(() => {
      return () => {
        if (blurTimeoutRef.current) {
          clearTimeout(blurTimeoutRef.current);
        }
      };
    }, []);

    const updateDropdownPosition = useCallback(() => {
      // Use the forwarded ref if available, otherwise fall back to internal ref
      const currentRef = (ref as React.RefObject<HTMLInputElement>) || inputRef;
      if (currentRef?.current) {
        const rect = currentRef.current.getBoundingClientRect();
        const inputWidth = rect.width;

        // Calculate optimal dropdown width based on content
        let maxContentWidth = 0;
        if (displayValues.length > 0) {
          maxContentWidth = Math.max(
            ...displayValues.map((val) => measureTextWidth(val))
          );
        }

        // Add padding and some buffer for better readability
        let contentWidth = maxContentWidth + DROPDOWN_STYLES.PADDING * 2;

        // If no display values yet, calculate width based on current input value
        if (maxContentWidth === 0 && inputValue) {
          const inputTextWidth = measureTextWidth(inputValue);
          contentWidth = inputTextWidth + DROPDOWN_STYLES.PADDING * 2;
        }

        // Calculate final width: use content width, but don't go below input width or above max
        const finalWidth = Math.max(
          inputWidth,
          Math.min(contentWidth, DROPDOWN_STYLES.MAX_WIDTH)
        );

        // Check if dropdown would go off-screen to the right or left
        const viewportWidth = window.innerWidth;
        const rightEdge = rect.left + finalWidth;
        let adjustedLeft = rect.left;

        // Handle case where dropdown is wider than viewport
        if (
          finalWidth >
          viewportWidth - DROPDOWN_STYLES.VIEWPORT_EDGE_BUFFER * 2
        ) {
          // Dropdown is too wide for viewport - center it with minimum margins
          adjustedLeft = DROPDOWN_STYLES.VIEWPORT_EDGE_BUFFER;
        } else if (rightEdge > viewportWidth) {
          // Would go off-screen to the right - position so dropdown ends at viewport edge
          adjustedLeft =
            viewportWidth - finalWidth - DROPDOWN_STYLES.VIEWPORT_EDGE_BUFFER;

          // Ensure the adjusted position doesn't go off-screen to the left
          if (adjustedLeft < DROPDOWN_STYLES.VIEWPORT_EDGE_BUFFER) {
            adjustedLeft = DROPDOWN_STYLES.VIEWPORT_EDGE_BUFFER;
          }
        } else if (rect.left < DROPDOWN_STYLES.VIEWPORT_EDGE_BUFFER) {
          // Would go off-screen to the left
          adjustedLeft = DROPDOWN_STYLES.VIEWPORT_EDGE_BUFFER;
        }

        setDropdownPosition({
          top: rect.bottom + window.scrollY,
          left: adjustedLeft + window.scrollX,
          width: inputWidth, // Keep original input width for positioning
        });
        setDropdownWidth(finalWidth);
      }
    }, [displayValues, inputValue, ref]);

    // Open dropdown when data finishes loading and input is focused, or show loading state
    useEffect(() => {
      // Don't open dropdown for non-metadata fields
      if (!isMetadataField) {
        return;
      }

      const currentRef = (ref as React.RefObject<HTMLInputElement>) || inputRef;
      if (currentRef?.current === document.activeElement) {
        const isSearching = isFetching || inputValue !== debouncedSearch;
        if (
          (values.length > 0 && !isSearching) ||
          (isSearching && collectionId && fieldName)
        ) {
          setOpen(true);
          requestAnimationFrame(() => {
            updateDropdownPosition();
          });
        }
      }
    }, [
      values.length,
      isFetching,
      ref,
      updateDropdownPosition,
      collectionId,
      fieldName,
      inputValue,
      debouncedSearch,
      isMetadataField,
    ]);

    const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      const newValue = e.target.value;
      setInputValue(newValue);
      onValueChange(newValue);

      // Clear any existing blur timeout
      if (blurTimeoutRef.current) {
        clearTimeout(blurTimeoutRef.current);
      }

      // Don't open dropdown for non-metadata fields
      if (!isMetadataField) {
        setOpen(false);
        return;
      }

      // Open suggestions if we have values and not currently fetching new data
      // OR show loading state if we're fetching/debouncing and focused
      const isSearching = isFetching || inputValue !== debouncedSearch;
      if (
        (values.length > 0 && !isSearching) ||
        (isSearching && collectionId && fieldName)
      ) {
        setOpen(true);
        // Update position after state change
        requestAnimationFrame(() => {
          updateDropdownPosition();
        });
      } else {
        setOpen(false);
      }
    };

    const handleSelectValue = (selectedValue: string) => {
      setInputValue(selectedValue);
      onValueChange(selectedValue);
      setOpen(false);
      // Focus back to input after selection
      requestAnimationFrame(() => {
        const currentRef =
          (ref as React.RefObject<HTMLInputElement>) || inputRef;
        currentRef?.current?.focus();
      });
    };

    const handleInputFocus = () => {
      // Don't open dropdown for non-metadata fields
      if (!isMetadataField) {
        return;
      }

      const isSearching = isFetching || inputValue !== debouncedSearch;
      if (
        (values.length > 0 && !isSearching) ||
        (isSearching && collectionId && fieldName)
      ) {
        // Clear any existing blur timeout
        if (blurTimeoutRef.current) {
          clearTimeout(blurTimeoutRef.current);
        }

        setOpen(true);
        // Update position after state change
        requestAnimationFrame(() => {
          updateDropdownPosition();
        });
      }
    };

    // Handle clicking outside to close dropdown
    useEffect(() => {
      const handleClickOutside = (event: MouseEvent) => {
        // Check if the click is on the dropdown itself
        const target = event.target as Element;
        const isDropdownClick = target.closest('[data-dropdown="true"]');

        // Use the forwarded ref if available, otherwise fall back to internal ref
        const currentRef =
          (ref as React.RefObject<HTMLInputElement>) || inputRef;
        if (
          currentRef?.current &&
          !currentRef.current.contains(event.target as Node) &&
          !isDropdownClick
        ) {
          setOpen(false);
        }
      };

      if (open) {
        document.addEventListener('mousedown', handleClickOutside);
        return () =>
          document.removeEventListener('mousedown', handleClickOutside);
      }
    }, [open, ref]);

    // Recalculate dropdown position when displayValues change
    useEffect(() => {
      if (open && values.length > 0) {
        updateDropdownPosition();
      }
    }, [displayValues, open, updateDropdownPosition, values.length]);

    const handleInputBlur = () => {
      // Clear any existing timeout
      if (blurTimeoutRef.current) {
        clearTimeout(blurTimeoutRef.current);
      }

      // Delay closing to allow for selection
      blurTimeoutRef.current = setTimeout(() => setOpen(false), 200);
    };

    return (
      <div className="relative">
        <Input
          ref={ref || inputRef}
          value={inputValue}
          onChange={handleInputChange}
          onFocus={handleInputFocus}
          onBlur={handleInputBlur}
          placeholder={placeholder}
          type={type}
          className={cn(
            'h-7 text-xs bg-background font-mono text-muted-foreground hover:bg-secondary hover:text-primary',
            className
          )}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              onEnter?.();
            }
          }}
        />
        {open &&
          typeof window !== 'undefined' &&
          createPortal(
            <div
              data-dropdown="true"
              className="fixed bg-background border border-border rounded-md shadow-lg overflow-y-auto overflow-x-auto"
              style={{
                top: `${dropdownPosition.top + DROPDOWN_STYLES.MIN_DROPDOWN_OFFSET}px`,
                left: `${dropdownPosition.left}px`,
                width: `${dropdownWidth}px`,
                zIndex: DROPDOWN_STYLES.Z_INDEX,
                maxHeight: DROPDOWN_STYLES.MAX_HEIGHT,
              }}
            >
              <div className="p-1 relative">
                {(() => {
                  const isSearching =
                    isFetching || inputValue !== debouncedSearch;
                  const isInitialLoad =
                    (isSearching || isFieldChanging) &&
                    displayValues.length === 0;

                  // If we're searching/changing field but have no current results, show loading message
                  if (isInitialLoad) {
                    return (
                      <div className="px-2 py-2 text-xs text-muted-foreground text-center">
                        {isFieldChanging
                          ? 'Loading values...'
                          : inputValue !== debouncedSearch
                            ? 'Searching...'
                            : 'Loading values...'}
                      </div>
                    );
                  }

                  // Show current results (even while searching for new ones)
                  if (displayValues.length > 0) {
                    return (
                      <>
                        {/* Search indicator - absolute positioned so it doesn't affect layout */}
                        {isSearching && !isFieldChanging && (
                          <div className="absolute -top-6 left-0 right-0 px-2 py-1 text-xs text-muted-foreground text-center bg-background border border-border rounded-t-md shadow-sm">
                            {inputValue !== debouncedSearch
                              ? 'Searching...'
                              : 'Loading...'}
                          </div>
                        )}

                        {/* Results list - position unchanged */}
                        <div
                          className={cn(
                            isSearching && 'opacity-70 transition-opacity'
                          )}
                        >
                          {displayValues.map((val) => (
                            <div
                              key={val}
                              className={cn(
                                'px-2 py-1 text-xs font-mono cursor-pointer hover:bg-secondary rounded-sm whitespace-nowrap',
                                inputValue === val && 'bg-secondary'
                              )}
                              onClick={() => handleSelectValue(val)}
                            >
                              {val}
                            </div>
                          ))}
                        </div>
                      </>
                    );
                  }

                  return (
                    <div className="px-2 py-2 text-xs text-muted-foreground text-center">
                      No matches found
                    </div>
                  );
                })()}
              </div>
            </div>,
            document.body
          )}
      </div>
    );
  }
);

SmartValueInput.displayName = 'SmartValueInput';
