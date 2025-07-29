import { useState, useEffect, useRef, useCallback } from 'react';

export function useDragAndDrop(onFileDropped: (file: File) => void) {
  const [dragState, setDragState] = useState<
    'none' | 'over-page' | 'over-zone'
  >('none');
  const dragCounterRef = useRef(0);

  useEffect(() => {
    const handleDragEnter = (e: DragEvent) => {
      e.preventDefault();
      dragCounterRef.current++;
      const hasFiles = e.dataTransfer?.types.includes('Files');
      if (hasFiles && dragCounterRef.current === 1) {
        setDragState('over-page');
      }
    };

    const handleDragLeave = (e: DragEvent) => {
      e.preventDefault();
      dragCounterRef.current--;
      if (dragCounterRef.current === 0) {
        setDragState('none');
      }
    };

    const handleDrop = (e: DragEvent) => {
      e.preventDefault();
      dragCounterRef.current = 0;
      setDragState('none');
    };

    const handleWindowBlur = () => {
      // Reset drag state when window loses focus (e.g., browser opens dropped file)
      dragCounterRef.current = 0;
      setDragState('none');
    };

    document.addEventListener('dragenter', handleDragEnter);
    document.addEventListener('dragleave', handleDragLeave);
    document.addEventListener('drop', handleDrop);
    window.addEventListener('blur', handleWindowBlur);

    return () => {
      document.removeEventListener('dragenter', handleDragEnter);
      document.removeEventListener('dragleave', handleDragLeave);
      document.removeEventListener('drop', handleDrop);
      window.removeEventListener('blur', handleWindowBlur);
    };
  }, []);

  const dropZoneHandlers = {
    onDragOver: useCallback(
      (e: React.DragEvent) => {
        e.preventDefault();
        const hasFiles = e.dataTransfer.types.includes('Files');
        if (hasFiles && dragState === 'over-page') {
          setDragState('over-zone');
        }
      },
      [dragState]
    ),

    onDragLeave: useCallback((e: React.DragEvent) => {
      e.preventDefault();
      setDragState('over-page');
    }, []),

    onDrop: useCallback(
      (e: React.DragEvent) => {
        e.preventDefault();
        dragCounterRef.current = 0;
        setDragState('none');

        const files = Array.from(e.dataTransfer.files);
        if (files.length > 0) {
          onFileDropped(files[0]);
        }
      },
      [onFileDropped]
    ),
  };

  return {
    isDragActive: dragState !== 'none',
    isOverDropZone: dragState === 'over-zone',
    dropZoneHandlers,
  };
}
