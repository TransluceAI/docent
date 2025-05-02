export const BASE_URL = process.env.NEXT_PUBLIC_API_HOST;
if (!BASE_URL) {
  throw new Error('NEXT_PUBLIC_API_HOST is not set');
}

export const BASE_DOCENT_PATH = '';
