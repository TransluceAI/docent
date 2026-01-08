type ArrayProperty = {
  type: 'array';
  items: SchemaProperty;
  description?: string;
};

type ObjectProperty = {
  type: 'object';
  properties: Record<string, SchemaProperty>;
  required?: string[];
  additionalProperties?: false;
  description?: string;
};

type SchemaProperty =
  | { type: 'string'; enum: string[]; description?: string }
  | { type: 'string'; citations: boolean; description?: string }
  | { type: 'string'; description?: string }
  | {
      type: 'integer' | 'number';
      maximum?: number;
      minimum?: number;
      description?: string;
    }
  | { type: 'boolean'; description?: string }
  | ArrayProperty
  | ObjectProperty;

type SchemaDefinition = {
  type: 'object';
  properties: Record<string, SchemaProperty>;
  required?: string[];
};

export const isComplexType = (
  property: SchemaProperty
): property is ArrayProperty | ObjectProperty => {
  return property.type === 'array' || property.type === 'object';
};

export type { SchemaProperty, SchemaDefinition, ArrayProperty, ObjectProperty };
