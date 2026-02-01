'use client';

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  Copy,
  MoreVertical,
  PanelLeft,
  PanelLeftClose,
  Pencil,
  Plus,
  Sparkles,
  Trash2,
} from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn, copyToClipboard } from '@/lib/utils';
import { useDebounce } from '@/hooks/use-debounce';
import {
  useCreateDataTableMutation,
  useDeleteDataTableMutation,
  useDuplicateDataTableMutation,
  useGenerateNameMutation,
  useListDataTablesQuery,
  useUpdateDataTableMutation,
} from '@/app/api/dataTableApi';
import type { DataTable, DataTableState } from '@/app/types/dataTableTypes';
import type { DqlExecuteResponse } from '@/app/types/dqlTypes';
import DQLEditor from '@/app/components/DQLEditor';
import UuidPill from '@/components/UuidPill';

const AUTO_SAVE_DEBOUNCE_MS = 700;
const UNTITLED_NAME = 'Untitled data table';

type DataTableExplorerProps = {
  collectionId?: string;
  canEdit: boolean;
};

const normalizeName = (value: string) => {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : UNTITLED_NAME;
};

const isDefaultTableName = (name: string) => {
  const trimmed = name.trim();
  if (trimmed === UNTITLED_NAME) {
    return true;
  }
  // Match "Data Table N" where N is a number
  return /^Data Table \d+$/i.test(trimmed);
};

const serializeState = (state: DataTableState | null | undefined) => {
  try {
    // Exclude chatState from comparison since it's managed separately by useDqlChat
    const { chatState: _, ...stateWithoutChat } = state ?? {};
    return JSON.stringify(stateWithoutChat);
  } catch {
    return '';
  }
};

export default function DataTableExplorer({
  collectionId,
  canEdit,
}: DataTableExplorerProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const urlTableId = searchParams.get('table');

  const [isListOpen, setIsListOpen] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(urlTableId);
  const [editingTitleId, setEditingTitleId] = useState<string | null>(null);
  const [draftTableId, setDraftTableId] = useState<string | null>(null);
  const [localNames, setLocalNames] = useState<Record<string, string>>({});
  const resultCacheRef = useRef<Record<string, DqlExecuteResponse | null>>({});

  // Panel resize state
  const [panelWidth, setPanelWidth] = useState(256); // default: w-64 = 256px
  const isResizingRef = useRef(false);
  const resizeStartXRef = useRef(0);
  const resizeStartWidthRef = useRef(0);

  // Load panel width from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem('data-table-panel-width');
    if (stored) {
      const parsed = parseInt(stored, 10);
      if (!isNaN(parsed) && parsed >= 160 && parsed <= 480) {
        setPanelWidth(parsed);
      }
    }
  }, []);

  const { data: dataTables = [], isLoading } = useListDataTablesQuery(
    { collectionId: collectionId ?? '' },
    { skip: !collectionId }
  );
  const [createDataTable, { isLoading: isCreating }] =
    useCreateDataTableMutation();
  const [updateDataTable, { isLoading: isUpdating }] =
    useUpdateDataTableMutation();
  const [deleteDataTable] = useDeleteDataTableMutation();
  const [duplicateDataTable, { isLoading: isDuplicating }] =
    useDuplicateDataTableMutation();
  const [generateName] = useGenerateNameMutation();

  const sortedTables = useMemo(() => {
    return [...dataTables].sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    );
  }, [dataTables]);

  const activeTable = useMemo(() => {
    if (!sortedTables.length) {
      return null;
    }
    return (
      sortedTables.find((table) => table.id === activeId) ?? sortedTables[0]
    );
  }, [activeId, sortedTables]);

  const getDisplayName = useCallback(
    (table: DataTable) => localNames[table.id] ?? table.name,
    [localNames]
  );

  useEffect(() => {
    if (!dataTables.length) {
      setActiveId(null);
      setEditingTitleId(null);
      setDraftTableId(null);
      setLocalNames({});
      return;
    }
    if (!activeId || !dataTables.some((table) => table.id === activeId)) {
      const fallback = sortedTables[0] ?? dataTables[0];
      setActiveId(fallback.id);
      setEditingTitleId(null);
    }
  }, [activeId, dataTables, sortedTables]);

  // Track table ID we're navigating to via push (distinguishes our navigation from back/forward)
  const navigatingToRef = useRef<string | null>(null);
  // Use ref for activeId so URL sync effect only runs when urlTableId changes
  const activeIdRef = useRef(activeId);
  activeIdRef.current = activeId;

  // Sync activeId from URL (handles browser back/forward)
  useEffect(() => {
    if (!urlTableId) return;

    // Our push completed - clear tracking
    if (navigatingToRef.current === urlTableId) {
      navigatingToRef.current = null;
      return;
    }

    // Skip sync if we're mid-navigation (URL hasn't caught up yet)
    if (navigatingToRef.current) return;

    // Sync state from URL (back/forward or initial load)
    if (
      urlTableId !== activeIdRef.current &&
      dataTables.some((t) => t.id === urlTableId)
    ) {
      setActiveId(urlTableId);
    }
  }, [urlTableId, dataTables]);

  // Keep URL in sync with activeId (for fallback selection, initial load without URL param)
  useEffect(() => {
    if (!activeId || urlTableId === activeId || navigatingToRef.current) return;

    const params = new URLSearchParams(searchParams.toString());
    params.set('table', activeId);
    router.replace(`?${params.toString()}`, { scroll: false });
  }, [activeId, router, searchParams, urlTableId]);

  const [draftName, setDraftName] = useState('');
  const [draftDql, setDraftDql] = useState('');
  const [draftState, setDraftState] = useState<DataTableState>({});

  useEffect(() => {
    if (!dataTables.length) {
      return;
    }
    setLocalNames((prev) => {
      let changed = false;
      const next = { ...prev };
      dataTables.forEach((table) => {
        if (next[table.id] && next[table.id] === table.name) {
          delete next[table.id];
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, [dataTables]);

  useEffect(() => {
    if (!activeTable) {
      setDraftDql('');
      setDraftState({});
      setDraftTableId(null);
      return;
    }
    setDraftDql(activeTable.dql);
    setDraftState(activeTable.state ?? {});
    setDraftTableId(activeTable.id);
  }, [activeTable?.id]);

  useEffect(() => {
    if (!activeTable) {
      setDraftName('');
      return;
    }
    if (editingTitleId === activeTable.id) {
      return;
    }
    setDraftName(getDisplayName(activeTable));
  }, [activeTable?.id, editingTitleId, getDisplayName]);

  const debouncedDql = useDebounce(draftDql, AUTO_SAVE_DEBOUNCE_MS);
  const stateSignature = useMemo(
    () => serializeState(draftState),
    [draftState]
  );
  const debouncedStateSignature = useDebounce(
    stateSignature,
    AUTO_SAVE_DEBOUNCE_MS
  );
  const activeStateSignature = useMemo(
    () => serializeState(activeTable?.state ?? null),
    [activeTable?.state]
  );

  useEffect(() => {
    if (!activeTable || !collectionId || !canEdit) {
      return;
    }
    if (draftTableId !== activeTable.id) {
      return;
    }
    if (
      debouncedDql !== draftDql ||
      debouncedStateSignature !== stateSignature
    ) {
      return;
    }
    const trimmedDql = debouncedDql.trim();
    if (!trimmedDql) {
      return;
    }
    if (
      trimmedDql === activeTable.dql &&
      debouncedStateSignature === activeStateSignature
    ) {
      return;
    }
    // Omit chatState to avoid overwriting chat updates from useDqlChat
    const { chatState: _chatState, ...stateWithoutChat } = draftState;
    updateDataTable({
      collectionId,
      dataTableId: activeTable.id,
      dql: trimmedDql,
      state: stateWithoutChat,
    })
      .unwrap()
      .catch((error) => {
        console.error('Failed to save data table', error);
        toast.error('Unable to save data table changes.');
      });
  }, [
    activeTable,
    collectionId,
    canEdit,
    debouncedDql,
    debouncedStateSignature,
    activeStateSignature,
    draftState,
    draftTableId,
    draftDql,
    stateSignature,
    updateDataTable,
  ]);

  const handleCreate = useCallback(async () => {
    if (!collectionId) {
      return;
    }
    try {
      const data = await createDataTable({
        collectionId,
      }).unwrap();
      navigatingToRef.current = data.id;
      const params = new URLSearchParams(searchParams.toString());
      params.set('table', data.id);
      router.push(`?${params.toString()}`, { scroll: false });
      setActiveId(data.id);
      setIsListOpen(true);
    } catch (error) {
      console.error('Failed to create data table', error);
      toast.error('Unable to create a data table.');
    }
  }, [collectionId, createDataTable, router, searchParams]);

  const handleDuplicate = useCallback(
    async (table: DataTable) => {
      if (!collectionId) {
        return;
      }
      try {
        const data = await duplicateDataTable({
          collectionId,
          dataTableId: table.id,
        }).unwrap();
        navigatingToRef.current = data.id;
        const params = new URLSearchParams(searchParams.toString());
        params.set('table', data.id);
        router.push(`?${params.toString()}`, { scroll: false });
        setActiveId(data.id);
        setIsListOpen(true);
      } catch (error) {
        console.error('Failed to duplicate data table', error);
        toast.error('Unable to duplicate this data table.');
      }
    },
    [collectionId, duplicateDataTable, router, searchParams]
  );

  const handleDelete = useCallback(
    async (table: DataTable) => {
      if (!collectionId) {
        return;
      }
      const shouldDelete = window.confirm(
        `Delete "${table.name}"? This cannot be undone.`
      );
      if (!shouldDelete) {
        return;
      }
      try {
        await deleteDataTable({
          collectionId,
          dataTableId: table.id,
        }).unwrap();
        if (activeId === table.id) {
          setActiveId(null);
        }
      } catch (error) {
        console.error('Failed to delete data table', error);
        toast.error('Unable to delete this data table.');
      }
    },
    [activeId, collectionId, deleteDataTable]
  );

  const handleNameBlur = useCallback(async () => {
    if (!activeTable || !collectionId || !canEdit) {
      setEditingTitleId(null);
      return;
    }
    const nextName = normalizeName(draftName);
    setEditingTitleId(null);
    const previousName = getDisplayName(activeTable);
    if (nextName === previousName) {
      setDraftName(nextName);
      return;
    }
    // Optimistically update with user's input
    setDraftName(nextName);
    setLocalNames((prev) => ({ ...prev, [activeTable.id]: nextName }));
    try {
      // Backend may deduplicate the name, use the returned value
      const updatedTable = await updateDataTable({
        collectionId,
        dataTableId: activeTable.id,
        name: nextName,
      }).unwrap();
      // Update with the actual name from backend (may be deduplicated)
      const finalName = updatedTable.name;
      if (finalName !== nextName) {
        setDraftName(finalName);
        setLocalNames((prev) => ({ ...prev, [activeTable.id]: finalName }));
      }
    } catch (error) {
      console.error('Failed to rename data table', error);
      setLocalNames((prev) => {
        if (!prev[activeTable.id]) {
          return prev;
        }
        const next = { ...prev };
        delete next[activeTable.id];
        return next;
      });
      setDraftName(previousName);
      toast.error('Unable to rename this data table.');
    }
  }, [
    activeTable,
    canEdit,
    collectionId,
    draftName,
    getDisplayName,
    updateDataTable,
  ]);

  const handleNameKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      if (!activeTable) {
        return;
      }
      if (event.key === 'Enter') {
        event.preventDefault();
        handleNameBlur();
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        setDraftName(getDisplayName(activeTable));
        setEditingTitleId(null);
      }
    },
    [activeTable, getDisplayName, handleNameBlur]
  );

  const handleSelectTable = useCallback(
    (table: DataTable) => {
      if (table.id !== activeId) {
        navigatingToRef.current = table.id;
        const params = new URLSearchParams(searchParams.toString());
        params.set('table', table.id);
        router.push(`?${params.toString()}`, { scroll: false });
      }
      setActiveId(table.id);
      setEditingTitleId(null);
      setDraftName(getDisplayName(table));
      setDraftDql(table.dql);
      setDraftState(table.state ?? {});
      setDraftTableId(table.id);
    },
    [activeId, getDisplayName, router, searchParams]
  );

  const [isAutoRenaming, setIsAutoRenaming] = useState(false);

  const handleAutoRename = useCallback(
    async (table: DataTable) => {
      if (!collectionId || !table.dql.trim()) {
        toast.error('Cannot auto-rename: table has no query.');
        return;
      }

      setIsAutoRenaming(true);
      try {
        const { name: generatedName } = await generateName({
          collectionId,
          dql: table.dql,
        }).unwrap();

        const updatedTable = await updateDataTable({
          collectionId,
          dataTableId: table.id,
          name: generatedName,
        }).unwrap();

        const finalName = updatedTable.name;
        setLocalNames((prev) => ({ ...prev, [table.id]: finalName }));
        if (activeTable?.id === table.id) {
          setDraftName(finalName);
        }
        toast.success(`Renamed to "${finalName}"`);
      } catch (error) {
        console.error('Failed to auto-rename data table', error);
        toast.error('Unable to generate a name for this table.');
      } finally {
        setIsAutoRenaming(false);
      }
    },
    [activeTable?.id, collectionId, generateName, updateDataTable]
  );

  const handleSchemaVisibleChange = useCallback((next: boolean) => {
    setDraftState((current) => ({
      ...current,
      schemaVisible: next,
    }));
  }, []);

  const handleResultChange = useCallback(
    async (result: DqlExecuteResponse | null) => {
      if (!activeTable) {
        return;
      }
      resultCacheRef.current[activeTable.id] = result;

      // Auto-generate name on first successful query if table has a default name
      if (
        result &&
        collectionId &&
        canEdit &&
        !activeTable.state?.nameAutoGenerated &&
        isDefaultTableName(getDisplayName(activeTable))
      ) {
        const trimmedDql = draftDql.trim();
        if (!trimmedDql) {
          return;
        }

        try {
          const { name: generatedName } = await generateName({
            collectionId,
            dql: trimmedDql,
          }).unwrap();

          // Update the table with the generated name and flag
          // The backend may deduplicate the name, so use the returned value
          // Omit chatState to avoid overwriting chat updates from useDqlChat
          const { chatState: _chatState, ...stateWithoutChat } = draftState;
          const updatedTable = await updateDataTable({
            collectionId,
            dataTableId: activeTable.id,
            name: generatedName,
            state: { ...stateWithoutChat, nameAutoGenerated: true },
          }).unwrap();

          // Update local state with the actual name from the backend (may be deduplicated)
          const finalName = updatedTable.name;
          setLocalNames((prev) => ({ ...prev, [activeTable.id]: finalName }));
          setDraftName(finalName);
          setDraftState((prev) => ({ ...prev, nameAutoGenerated: true }));
        } catch (error) {
          // Silently fail - name generation is a nice-to-have
          console.debug('Failed to auto-generate data table name', error);
        }
      }
    },
    [
      activeTable,
      canEdit,
      collectionId,
      draftDql,
      draftState,
      generateName,
      getDisplayName,
      updateDataTable,
    ]
  );

  const schemaVisible = draftState.schemaVisible ?? false;
  const headerName = activeTable ? getDisplayName(activeTable) : UNTITLED_NAME;
  const cachedResult = activeTable
    ? resultCacheRef.current[activeTable.id]
    : undefined;

  // Panel resize handlers
  const handlePanelResizeStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      isResizingRef.current = true;
      resizeStartXRef.current = e.clientX;
      resizeStartWidthRef.current = panelWidth;
    },
    [panelWidth]
  );

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizingRef.current) return;
      const delta = e.clientX - resizeStartXRef.current;
      const newWidth = Math.max(
        160,
        Math.min(480, resizeStartWidthRef.current + delta)
      );
      setPanelWidth(newWidth);
    };

    const handleMouseUp = () => {
      isResizingRef.current = false;
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, []);

  // Persist panel width to localStorage (debounced)
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      localStorage.setItem('data-table-panel-width', String(panelWidth));
    }, 200);
    return () => clearTimeout(timeoutId);
  }, [panelWidth]);

  return (
    <div className="flex-1 flex min-h-0 min-w-0 overflow-hidden border rounded-lg bg-card">
      {isListOpen && (
        <div
          className="border-r bg-muted/30 flex flex-col min-h-0 relative"
          style={{ width: panelWidth }}
        >
          <div className="flex items-center justify-between h-10 px-3 border-b">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Data Tables
            </span>
            <div className="flex items-center gap-1">
              {canEdit && (
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  onClick={handleCreate}
                  disabled={isCreating || !collectionId}
                >
                  <Plus className="h-4 w-4" />
                </Button>
              )}
              <Button
                type="button"
                size="icon"
                variant="ghost"
                onClick={() => setIsListOpen(false)}
                disabled={dataTables.length === 0}
              >
                <PanelLeftClose className="h-4 w-4" />
              </Button>
            </div>
          </div>
          <div className="flex-1 overflow-auto p-2 space-y-1">
            {isLoading && (
              <div className="text-xs text-muted-foreground px-2 py-1">
                Loading data tables...
              </div>
            )}
            {!isLoading && dataTables.length === 0 && (
              <div className="text-xs text-muted-foreground px-2 py-1">
                No data tables yet.
              </div>
            )}
            {sortedTables.map((table) => {
              const isActive = table.id === activeTable?.id;
              return (
                <div
                  key={table.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => handleSelectTable(table)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      handleSelectTable(table);
                    }
                  }}
                  className={cn(
                    'group relative rounded-md px-2 py-1.5 text-sm cursor-pointer',
                    isActive
                      ? 'bg-muted text-foreground'
                      : 'hover:bg-muted/60 text-muted-foreground'
                  )}
                >
                  <span
                    className={cn(
                      'block truncate pr-1',
                      isActive && 'font-medium text-foreground'
                    )}
                  >
                    {getDisplayName(table)}
                  </span>
                  {canEdit && (
                    <div className="absolute right-1 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            type="button"
                            size="icon"
                            variant="ghost"
                            className="h-6 w-6 bg-muted/80 backdrop-blur-sm hover:bg-muted"
                            onClick={(event) => event.stopPropagation()}
                          >
                            <MoreVertical className="h-3.5 w-3.5" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem
                            onClick={() => handleAutoRename(table)}
                            disabled={isAutoRenaming}
                          >
                            <Sparkles className="mr-2 h-3.5 w-3.5" />
                            Auto-rename
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onClick={() => handleDuplicate(table)}
                            disabled={isDuplicating}
                          >
                            <Copy className="mr-2 h-3.5 w-3.5" />
                            Duplicate
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onClick={async () => {
                              const success = await copyToClipboard(table.id);
                              if (success) {
                                toast.success('Data table ID copied');
                              } else {
                                toast.error('Failed to copy ID');
                              }
                            }}
                          >
                            <Copy className="mr-2 h-3.5 w-3.5" />
                            Copy ID
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onClick={() => handleDelete(table)}
                            className="text-red-text"
                          >
                            <Trash2 className="mr-2 h-3.5 w-3.5" />
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {/* Resize handle */}
          <div
            className="absolute right-0 top-0 bottom-0 w-1 cursor-ew-resize hover:bg-primary/20"
            onMouseDown={handlePanelResizeStart}
          />
        </div>
      )}

      <div className="flex-1 flex flex-col min-h-0 min-w-0">
        {activeTable && (
          <div className="flex flex-wrap items-center justify-between h-10 gap-3 border-b px-3">
            <div className="flex min-w-0 flex-1 items-center gap-2">
              {!isListOpen && (
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  onClick={() => setIsListOpen(true)}
                >
                  <PanelLeft className="h-4 w-4" />
                </Button>
              )}
              {editingTitleId === activeTable.id && canEdit ? (
                <Input
                  autoFocus
                  value={draftName}
                  onChange={(event) => setDraftName(event.target.value)}
                  onFocus={(event) => event.target.select()}
                  onBlur={handleNameBlur}
                  onKeyDown={handleNameKeyDown}
                  className="h-auto w-full max-w-[24rem] border-0 bg-transparent p-0 text-sm font-semibold shadow-none focus-visible:ring-0 focus-visible:ring-offset-0"
                />
              ) : canEdit ? (
                <button
                  type="button"
                  className="group flex min-w-0 items-center gap-2 text-left text-sm font-semibold"
                  onClick={() => {
                    setDraftName(getDisplayName(activeTable));
                    setEditingTitleId(activeTable.id);
                  }}
                >
                  <span className="truncate">{normalizeName(headerName)}</span>
                  <Pencil className="h-3.5 w-3.5 text-muted-foreground opacity-70 transition-opacity group-hover:opacity-100" />
                </button>
              ) : (
                <span className="text-sm font-semibold truncate max-w-[16rem]">
                  {normalizeName(headerName)}
                </span>
              )}
              <UuidPill uuid={activeTable.id} />
            </div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              {isUpdating && <span>Saving...</span>}
              {canEdit && (
                <>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => handleDuplicate(activeTable)}
                    disabled={isDuplicating}
                  >
                    Duplicate
                  </Button>
                  <Button
                    type="button"
                    variant="destructive"
                    size="sm"
                    onClick={() => handleDelete(activeTable)}
                  >
                    Delete
                  </Button>
                </>
              )}
            </div>
          </div>
        )}

        <div className="flex-1 min-h-0 min-w-0 p-3">
          {activeTable ? (
            <DQLEditor
              key={activeTable.id}
              dataTableId={activeTable.id}
              collectionId={collectionId ?? undefined}
              initialQuery={draftDql}
              onQueryChange={setDraftDql}
              initialResult={cachedResult}
              onResultChange={handleResultChange}
              initialSchemaVisible={schemaVisible}
              onSchemaVisibleChange={handleSchemaVisibleChange}
              initialChatState={activeTable.state?.chatState}
              readOnly={!canEdit}
            />
          ) : (
            <div className="h-full flex flex-col items-center justify-center text-sm text-muted-foreground">
              <span>Create a data table to start exploring.</span>
              {canEdit && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="mt-3"
                  onClick={handleCreate}
                  disabled={isCreating}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  New Data Table
                </Button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
