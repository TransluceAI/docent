'use client';

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';

export type TextSelectionItem = {
  text: string;
  transcriptIdx?: number;
  blockIdx?: number;
};

type TextSelectionContextValue = {
  selections: TextSelectionItem[];
  addSelection: (item: TextSelectionItem) => void;
  removeSelection: (index: number) => void;
  clearSelections: () => void;
  focusChatInput: () => void;
};

const defaultValue: TextSelectionContextValue = {
  selections: [],
  addSelection: () => {},
  removeSelection: () => {},
  clearSelections: () => {},
  focusChatInput: () => {},
};

const TextSelectionContext =
  createContext<TextSelectionContextValue>(defaultValue);

type UseTextSelectionProps = {
  containerRef?: React.RefObject<HTMLElement | null>;
  selectionItem?: TextSelectionItem;
};

export function useTextSelection({
  containerRef,
  selectionItem,
}: UseTextSelectionProps): TextSelectionContextValue {
  const textSelectionContext = useContext(TextSelectionContext);

  useEffect(() => {
    if (!containerRef) return;
    const handler = (e: KeyboardEvent) => {
      // Ctrl+I shortcut
      const isModifier = e.metaKey || e.ctrlKey;
      if (isModifier && (e.key === 'i' || e.key === 'I')) {
        const container = containerRef.current;
        if (!container) return;
        const sel = window.getSelection();
        if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return;
        const range = sel.getRangeAt(0);
        if (!container.contains(range.commonAncestorContainer as Node)) return;
        const selected = sel.toString().trim();
        if (!selected) return;
        e.preventDefault();
        textSelectionContext.addSelection({
          ...(selectionItem || {}),
          text: selected,
        });
        textSelectionContext.focusChatInput();
        try {
          sel.removeAllRanges();
        } catch {
          console.error('Failed to remove ranges from text selection');
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [containerRef, selectionItem, textSelectionContext]);

  // Do not throw if not inside provider; return context (possibly default no-op)
  return textSelectionContext ?? defaultValue;
}

export function TextSelectionProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [selections, setSelections] = useState<TextSelectionItem[]>([]);

  const addSelection = useCallback((item: TextSelectionItem) => {
    const text = (item.text || '').trim();
    if (!text) return;
    setSelections((prev) => {
      // Avoid immediate duplicates
      if (prev.length > 0 && prev[prev.length - 1]?.text === text) return prev;
      return [...prev, { ...item, text }];
    });
  }, []);

  const removeSelection = useCallback((index: number) => {
    setSelections((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const clearSelections = useCallback(() => setSelections([]), []);

  const focusChatInput = useCallback(() => {
    try {
      window.dispatchEvent(new Event('focus-chat-input' as any));
    } catch {
      console.error('Failed to focus chat input from text selection provider');
    }
  }, []);

  const value = useMemo(
    () => ({
      selections,
      addSelection,
      removeSelection,
      clearSelections,
      focusChatInput,
    }),
    [selections, addSelection, removeSelection, clearSelections, focusChatInput]
  );

  return (
    <TextSelectionContext.Provider value={value}>
      {children}
    </TextSelectionContext.Provider>
  );
}
