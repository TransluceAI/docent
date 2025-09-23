'use client';
import React, {
  ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { useScrollToBottom } from '@/app/hooks/use-scroll-to-bottom';
import { useWindowSize, useLocalStorage } from 'usehooks-ts';
import { AnimatePresence, motion } from 'framer-motion';
import { Button } from '@/components/ui/button';
import {
  ArrowDown,
  ArrowUpIcon,
  Loader2,
  RotateCwIcon,
  Square,
  TriangleAlert,
} from 'lucide-react';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';

interface InputAreaProps {
  className?: string;
  onSendMessage: (message: string) => void;
  onCancelMessage?: () => void;
  onRetry?: () => void;
  disabled: boolean;
  isSendingMessage?: boolean;
  inputHeaderElement?: ReactNode;
  footer?: ReactNode;
  errorMessage?: string;
}

export default function InputArea({
  className,
  onSendMessage,
  onCancelMessage,
  onRetry,
  disabled,
  isSendingMessage,
  footer,
  errorMessage,
  inputHeaderElement,
}: InputAreaProps) {
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

  // Minimal handler to programmatically focus this input (e.g., via Cmd/Ctrl+J)
  useEffect(() => {
    const focusHandler = () => {
      const el = textareaRef.current;
      if (!el || el.disabled) return;

      // Small delay to ensure element is ready
      setTimeout(() => {
        el.focus();
        const len = el.value?.length ?? 0;
        el.setSelectionRange(len, len);
      }, 0);
    };

    window.addEventListener('focus-chat-input', focusHandler);
    return () => window.removeEventListener('focus-chat-input', focusHandler);
  }, []);

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

  const sentButton = () => {
    return (
      <Button
        type="button"
        data-testid="send-button"
        className={cn(
          'shrink-0 rounded-full h-7 w-7 border dark:border-zinc-600',
          isSendingMessage &&
            !onCancelMessage &&
            'pointer-events-none opacity-60'
        )}
        size="icon"
        onClick={(event) => {
          event.preventDefault();
          if (isSendingMessage) {
            if (onCancelMessage) {
              onCancelMessage();
            }
          } else {
            submitForm();
          }
        }}
        disabled={disabled}
      >
        {isSendingMessage && onCancelMessage ? (
          <Square size={12} />
        ) : isSendingMessage ? (
          <Loader2 size={14} className="animate-spin" />
        ) : (
          <ArrowUpIcon size={14} />
        )}
      </Button>
    );
  };

  const retryButton = () => {
    return (
      <Button
        type="button"
        className="shrink-0 text-xs gap-1 px-2 h-7 rounded-full"
        onClick={(e) => {
          e.preventDefault();
          onRetry?.();
        }}
      >
        <RotateCwIcon className="size-3" /> Retry
      </Button>
    );
  };

  return (
    <div className="relative w-full flex flex-col gap-4">
      <AnimatePresence>
        {!isAtBottom && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            transition={{ type: 'spring', stiffness: 300, damping: 20 }}
            className="absolute inset-x-0 z-50 mx-auto w-fit"
            style={{ bottom: 'calc(100% + 16px)' }}
          >
            <Button
              type="button"
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

      <div className="flex flex-col bg-muted rounded-2xl text-sm ring-offset-background focus-within:outline-none focus-within:ring-1 focus-within:ring-ring focus-within:ring-offset-1">
        {errorMessage && (
          <div className="gap-1 px-2 pt-2 flex items-center text-yellow-700 dark:text-yellow-400">
            <TriangleAlert className="h-4 w-4" />
            <span className="text-xs">{errorMessage}</span>
          </div>
        )}
        {inputHeaderElement && (
          <div className="px-2 pt-2">{inputHeaderElement}</div>
        )}
        <div className="overflow-clip bg-muted dark:border-zinc-700 p-2 rounded-2xl border border-transparent">
          <Textarea
            data-testid="multimodal-input"
            ref={textareaRef}
            placeholder="Send a message..."
            value={input}
            onChange={handleInput}
            className={cn(
              'min-h-[24px] max-h-[calc(75dvh)] overflow-hidden p-0 border-none shadow-none resize-none focus-visible:ring-0',
              className
            )}
            disabled={disabled || typeof errorMessage === 'string'}
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
              {onRetry && errorMessage ? retryButton() : sentButton()}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
