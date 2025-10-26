type SchemaProperty =
  | { type: 'string'; enum: string[] }
  | { type: 'string'; citations: boolean }
  | { type: 'integer' | 'number'; maximum: number; minimum: number }
  | { type: 'boolean' };

type SchemaDefinition = {
  type: 'object';
  properties: Record<string, SchemaProperty>;
  required?: string[];
};

export type { SchemaProperty, SchemaDefinition };
