'use client';

// This component is no longer needed as auto-reconnect is handled locally in CounterfactualExperimentViewer
// Keeping as empty component for backward compatibility
export default function ExperimentAutoReconnect({
  workspaceId,
  experimentConfigId,
}: {
  workspaceId: string;
  experimentConfigId: string;
}) {
  return null;
}
