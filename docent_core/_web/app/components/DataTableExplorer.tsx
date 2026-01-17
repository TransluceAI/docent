'use client';

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react';
import {
  Copy,
  MoreVertical,
  PanelLeft,
  PanelLeftClose,
  Pencil,
  Plus,
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
import { cn } from '@/lib/utils';
import { useDebounce } from '@/hooks/use-debounce';
import {
  useCreateDataTableMutation,
  useDeleteDataTableMutation,
  useDuplicateDataTableMutation,
  useListDataTablesQuery,
  useUpdateDataTableMutation,
} from '@/app/api/dataTableApi';
import type { DataTable, DataTableState } from '@/app/types/dataTableTypes';
import DQLEditor from '@/app/components/DQLEditor';

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

const serializeState = (state: DataTableState | null | undefined) => {
  try {
    return JSON.stringify(state ?? {});
  } catch {
    return '';
  }
};

export default function DataTableExplorer({
  collectionId,
  canEdit,
}: DataTableExplorerProps) {
  const [isListOpen, setIsListOpen] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [editingTitleId, setEditingTitleId] = useState<string | null>(null);
  const titleInputRef = useRef<HTMLInputElement | null>(null);
  const [draftTableId, setDraftTableId] = useState<string | null>(null);
  const [localNames, setLocalNames] = useState<Record<string, string>>({});

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

  useEffect(() => {
    if (!activeTable || editingTitleId !== activeTable.id) {
      return;
    }
    titleInputRef.current?.focus();
    titleInputRef.current?.select();
  }, [activeTable?.id, editingTitleId]);

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
    updateDataTable({
      collectionId,
      dataTableId: activeTable.id,
      dql: trimmedDql,
      state: draftState,
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
      setActiveId(data.id);
      setIsListOpen(true);
    } catch (error) {
      console.error('Failed to create data table', error);
      toast.error('Unable to create a data table.');
    }
  }, [collectionId, createDataTable]);

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
        setActiveId(data.id);
        setIsListOpen(true);
      } catch (error) {
        console.error('Failed to duplicate data table', error);
        toast.error('Unable to duplicate this data table.');
      }
    },
    [collectionId, duplicateDataTable]
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

  const handleNameBlur = useCallback(() => {
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
    setDraftName(nextName);
    setLocalNames((prev) => ({ ...prev, [activeTable.id]: nextName }));
    updateDataTable({
      collectionId,
      dataTableId: activeTable.id,
      name: nextName,
    })
      .unwrap()
      .catch((error) => {
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
      });
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
      setActiveId(table.id);
      setEditingTitleId(null);
      setDraftName(getDisplayName(table));
      setDraftDql(table.dql);
      setDraftState(table.state ?? {});
      setDraftTableId(table.id);
    },
    [getDisplayName]
  );

  const handleRename = useCallback(
    (table: DataTable) => {
      handleSelectTable(table);
      setEditingTitleId(table.id);
    },
    [handleSelectTable]
  );

  const handleSchemaVisibleChange = useCallback((next: boolean) => {
    setDraftState((current) => ({
      ...current,
      schemaVisible: next,
    }));
  }, []);

  const schemaVisible = draftState.schemaVisible ?? false;
  const headerName = activeTable ? getDisplayName(activeTable) : UNTITLED_NAME;

  return (
    <div className="flex-1 flex min-h-0 min-w-0 overflow-hidden border rounded-lg bg-card">
      {isListOpen && (
        <div className="w-64 border-r bg-muted/30 flex flex-col min-h-0">
          <div className="flex items-center justify-between px-3 py-2 border-b">
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
                    'group flex items-center gap-2 rounded-md px-2 py-1.5 text-sm cursor-pointer',
                    isActive
                      ? 'bg-muted text-foreground'
                      : 'hover:bg-muted/60 text-muted-foreground'
                  )}
                >
                  <span
                    className={cn(
                      'flex-1 truncate',
                      isActive && 'font-medium text-foreground'
                    )}
                  >
                    {getDisplayName(table)}
                  </span>
                  {canEdit && (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          type="button"
                          size="icon"
                          variant="ghost"
                          className="h-7 w-7 opacity-0 group-hover:opacity-100"
                          onClick={(event) => event.stopPropagation()}
                        >
                          <MoreVertical className="h-3.5 w-3.5" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => handleRename(table)}>
                          <Pencil className="mr-2 h-3.5 w-3.5" />
                          Rename
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => handleDuplicate(table)}
                          disabled={isDuplicating}
                        >
                          <Copy className="mr-2 h-3.5 w-3.5" />
                          Duplicate
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
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="flex-1 flex flex-col min-h-0 min-w-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b px-3 py-2">
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
            {activeTable ? (
              editingTitleId === activeTable.id && canEdit ? (
                <Input
                  ref={titleInputRef}
                  value={draftName}
                  onChange={(event) => setDraftName(event.target.value)}
                  onBlur={handleNameBlur}
                  onKeyDown={handleNameKeyDown}
                  className="h-auto w-full max-w-[24rem] border-0 bg-transparent p-0 text-sm font-semibold shadow-none focus-visible:ring-0 focus-visible:ring-offset-0"
                />
              ) : canEdit ? (
                <button
                  type="button"
                  className="group flex min-w-0 flex-1 items-center gap-2 text-left text-sm font-semibold"
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
              )
            ) : (
              <span className="text-sm text-muted-foreground">
                Select a data table
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            {isUpdating && <span>Saving...</span>}
            {canEdit && activeTable && (
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

        <div className="flex-1 min-h-0 min-w-0 p-3">
          {activeTable ? (
            <DQLEditor
              key={activeTable.id}
              collectionId={collectionId ?? undefined}
              initialQuery={draftDql}
              onQueryChange={setDraftDql}
              initialSchemaVisible={schemaVisible}
              onSchemaVisibleChange={handleSchemaVisibleChange}
              readOnly={!canEdit}
              autoRunKey={activeTable.id}
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
