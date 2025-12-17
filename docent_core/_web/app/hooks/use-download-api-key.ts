import { useCallback, useState } from 'react';

import { apiRestClient } from '@/app/services/apiService';
import { toast } from 'sonner';

let cachedApiKey: string | null = null;
let inflightApiKeyPromise: Promise<string> | null = null;

const buildDownloadApiKeyName = (createdAt: Date): string => {
  const timestamp = createdAt
    .toISOString()
    .replace('T', ' ')
    .replace(/\.\d{3}Z$/, ' UTC');
  return `Docent download key (${timestamp})`;
};

const createDownloadApiKey = async (): Promise<string> => {
  const name = buildDownloadApiKeyName(new Date());

  const response = await apiRestClient.post('/api-keys', { name });
  const apiKey = (response.data as { api_key?: string }).api_key;
  if (!apiKey) {
    throw new Error('API key was not returned by the server');
  }

  toast.success(
    'Generated a key for Python downloads. Rotate it in Settings as needed.'
  );

  return apiKey;
};

export const useDownloadApiKey = () => {
  const [isLoading, setIsLoading] = useState(false);

  const getApiKey = useCallback(async (): Promise<string> => {
    if (cachedApiKey) {
      return cachedApiKey;
    }

    if (inflightApiKeyPromise) {
      return inflightApiKeyPromise;
    }

    setIsLoading(true);
    inflightApiKeyPromise = createDownloadApiKey()
      .then((apiKey) => {
        cachedApiKey = apiKey;
        return apiKey;
      })
      .catch((error) => {
        console.error('Failed to create download API key', error);
        toast.error('Unable to generate an API key for the sample script.');
        throw error;
      })
      .finally(() => {
        setIsLoading(false);
        inflightApiKeyPromise = null;
      });

    return inflightApiKeyPromise;
  }, []);

  return { getApiKey, isLoading };
};
