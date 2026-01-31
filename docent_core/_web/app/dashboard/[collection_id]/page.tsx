'use client';

import { redirect, useParams } from 'next/navigation';

export default function DocentDashboard() {
  const params = useParams();
  const collectionId = params.collection_id as string;
  redirect(`/dashboard/${collectionId}/agent_run`);
}
