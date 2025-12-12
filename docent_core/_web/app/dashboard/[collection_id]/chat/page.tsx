'use client';

import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useState } from 'react';
import {
  useCreateCollectionConversationMutation,
  useDeleteConversationMutation,
  useGetCollectionChatsQuery,
} from '@/app/api/chatApi';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { MessageSquarePlus, Trash2 } from 'lucide-react';

function formatUpdatedAt(dateString: string): string {
  const date = new Date(dateString + 'Z');
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const updatedDate = new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate()
  );

  const isToday = updatedDate.getTime() === today.getTime();

  if (isToday) {
    return `Today ${date.toLocaleTimeString(undefined, {
      hour: 'numeric',
      minute: '2-digit',
    })}`;
  } else {
    return date.toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  }
}

export default function CollectionChatsPage() {
  const params = useParams();
  const router = useRouter();
  const collectionId = params?.collection_id as string;
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [chatToDelete, setChatToDelete] = useState<string | null>(null);

  const {
    data: chats,
    isLoading,
    isFetching,
  } = useGetCollectionChatsQuery({ collectionId }, { skip: !collectionId });
  const [createChat, { isLoading: isCreating }] =
    useCreateCollectionConversationMutation();
  const [deleteChat, { isLoading: isDeleting }] =
    useDeleteConversationMutation();

  const handleCreate = async () => {
    if (!collectionId) return;
    try {
      const res = await createChat({
        collectionId,
        context_serialized: {},
      }).unwrap();
      router.push(`/dashboard/${collectionId}/chat/${res.session_id}`);
    } catch (err) {
      console.error('Failed to create chat', err);
    }
  };

  const handleDeleteClick = (e: React.MouseEvent, chatId: string) => {
    e.preventDefault();
    e.stopPropagation();
    setChatToDelete(chatId);
    setDeleteDialogOpen(true);
  };

  const handleDeleteConfirm = async () => {
    if (!chatToDelete) return;
    try {
      await deleteChat({
        sessionId: chatToDelete,
        collectionId,
      }).unwrap();
      setDeleteDialogOpen(false);
      setChatToDelete(null);
    } catch (err) {
      console.error('Failed to delete chat', err);
    }
  };

  const renderList = () => {
    if (!chats || chats.length === 0) {
      return (
        <div className="flex flex-col items-center justify-center gap-3 rounded-md border border-dashed border-border p-8 text-center">
          <div className="text-sm text-muted-foreground">
            No chats yet in this collection.
          </div>
        </div>
      );
    }

    return (
      <div className="grid gap-3">
        {chats.map((chat) => {
          return (
            <div
              key={chat.id}
              className="flex items-center justify-between rounded-md border border-border p-4 transition hover:bg-muted group"
            >
              <Link
                href={`/dashboard/${collectionId}/chat/${chat.id}`}
                className="flex items-center justify-between flex-1 min-w-0"
              >
                <div className="flex flex-col gap-1 min-w-0">
                  <div className="text-sm font-medium text-foreground truncate">
                    {chat.first_message_preview || 'New conversation'}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {chat.context_item_count} items · {chat.message_count}{' '}
                    messages
                    {chat.updated_at && (
                      <> · {formatUpdatedAt(chat.updated_at)}</>
                    )}
                  </div>
                </div>
              </Link>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                onClick={(e) => handleDeleteClick(e, chat.id)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <div className="flex-1 flex bg-card min-h-0 shrink-0 border rounded-lg p-4">
      <div className="flex flex-col gap-4 w-full">
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <h1 className="text-xl font-semibold tracking-tight">Chats</h1>
            <p className="text-sm text-muted-foreground">
              Multi-transcript chats scoped to this collection.
            </p>
          </div>
          <Button
            onClick={handleCreate}
            disabled={isCreating || !collectionId}
            className="gap-2"
          >
            <MessageSquarePlus className="h-4 w-4" />
            {isCreating ? 'Creating...' : 'New chat'}
          </Button>
        </div>

        {isLoading || isFetching ? (
          <div className="text-sm text-muted-foreground">Loading chats...</div>
        ) : (
          renderList()
        )}
      </div>

      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Chat</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete this chat? This action cannot be
              undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteDialogOpen(false)}
              disabled={isDeleting}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteConfirm}
              disabled={isDeleting}
            >
              {isDeleting ? 'Deleting...' : 'Delete'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
