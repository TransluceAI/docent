type SchemaProperty =
  | { type: 'string'; enum: string[] }
  | { type: 'string'; citations: boolean }
  | { type: 'integer'; maximum: number; minimum: number }
  | { type: 'boolean' };

type SchemaDefinition = {
  type: 'object';
  properties: Record<string, SchemaProperty>;
};

export type { SchemaProperty, SchemaDefinition };
