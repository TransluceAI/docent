export const PROVIDERS = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'google', label: 'Google' },
  { value: 'openrouter', label: 'OpenRouter' },
] as const;

export function getProviderLabel(provider: string): string {
  const providerConfig = PROVIDERS.find((p) => p.value === provider);
  return providerConfig?.label || provider;
}
