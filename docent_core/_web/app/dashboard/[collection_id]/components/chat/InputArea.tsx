'use client';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useScrollToBottom } from '@/app/hooks/use-scroll-to-bottom';
import { useWindowSize, useLocalStorage } from 'usehooks-ts';
import { AnimatePresence, motion } from 'framer-motion';
import { Button } from '@/components/ui/button';
import { ArrowDown, ArrowUpIcon, Loader2, TriangleAlert } from 'lucide-react';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';

export default function InputArea({
  className,
  onSendMessage,
  disabled,
  isLoading,
  footer,
  errorMessage,
}: {
  className?: string;
  onSendMessage: (message: string) => void;
  disabled: boolean;
  isLoading?: boolean;
  footer?: React.ReactNode;
  errorMessage?: string;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { width } = useWindowSize();

  const [input, setInput] = useState('');

  useEffect(() => {
    if (textareaRef.current) {
      adjustHeight();
    }
  }, []);

  const adjustHeight = () => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight + 2}px`;
    }
  };

  const resetHeight = () => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const [localStorageInput, setLocalStorageInput] = useLocalStorage(
    'input',
    ''
  );

  useEffect(() => {
    if (textareaRef.current) {
      const domValue = textareaRef.current.value;
      // Prefer DOM value over localStorage to handle hydration
      const finalValue = domValue || localStorageInput || '';
      setInput(finalValue);
      adjustHeight();
    }
    // Only run once after hydration
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setLocalStorageInput(input);
  }, [input, setLocalStorageInput]);

  const handleInput = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(event.target.value);
    adjustHeight();
  };

  const submitForm = useCallback(() => {
    onSendMessage(input);

    setLocalStorageInput('');
    resetHeight();
    setInput('');

    if (width && width > 768) {
      textareaRef.current?.focus();
    }
  }, [input, setInput, setLocalStorageInput, width, onSendMessage]);

  const { isAtBottom, scrollToBottom } = useScrollToBottom();

  return (
    <div className="relative w-full flex flex-col gap-4">
      <AnimatePresence>
        {!isAtBottom && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            transition={{ type: 'spring', stiffness: 300, damping: 20 }}
            className="absolute inset-x-0 bottom-28 z-50 mx-auto w-fit"
          >
            <Button
              data-testid="scroll-to-bottom-button"
              className="rounded-full"
              size="icon"
              variant="outline"
              onClick={(event) => {
                event.preventDefault();
                scrollToBottom();
              }}
            >
              <ArrowDown size={16} />
            </Button>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex flex-col bg-yellow-50 dark:bg-yellow-900 rounded-2xl text-sm">
        {errorMessage && (
          <div className="px-2 py-2 flex items-center gap-1 text-yellow-800 dark:text-yellow-400">
            <TriangleAlert className="h-4 w-4" />
            <span className="text-xs">{errorMessage}</span>
          </div>
        )}
        <div className="overflow-clip bg-muted dark:border-zinc-700 p-2 rounded-2xl border border-transparent focus-within:border-foreground">
          <Textarea
            data-testid="multimodal-input"
            ref={textareaRef}
            placeholder="Send a message..."
            value={input}
            onChange={handleInput}
            className={cn(
              'min-h-[24px] max-h-[calc(75dvh)] overflow-hidden p-0 border-none focus-visible:ring-0 shadow-none resize-none',
              className
            )}
            rows={1}
            autoFocus
            onKeyDown={(event) => {
              if (
                event.key === 'Enter' &&
                !event.shiftKey &&
                !event.nativeEvent.isComposing
              ) {
                event.preventDefault();

                if (!disabled) {
                  submitForm();
                }
              }
            }}
          />
          <div>
            <div className="mt-2 px-1 flex flex-row justify-end">
              {footer}
              <Button
                data-testid="send-button"
                className="rounded-full p-1.5 h-fit border dark:border-zinc-600"
                onClick={(event) => {
                  event.preventDefault();
                  submitForm();
                }}
                disabled={input.length === 0 || disabled || isLoading}
              >
                {isLoading ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <ArrowUpIcon size={14} />
                )}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
