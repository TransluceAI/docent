'use client';

import { useParams } from 'next/navigation';
import { ConversationView } from '@/components/conversation/ConversationView';

export default function CollectionConversationPage() {
  const params = useParams();
  const sessionId = (params?.session_id as string) || null;

  return (
    <div className="flex flex-1 flex-col bg-card min-h-0 border rounded-lg p-3">
      <ConversationView sessionId={sessionId} />
    </div>
  );
}
