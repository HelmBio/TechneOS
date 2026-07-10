"use client";

import { SchemaField } from "./schema-field";

export interface SchemaFormProps {
  schema: Record<string, unknown> | null | undefined;
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
}

/**
 * Collect default values from a JSON Schema properties map, mirroring the
 * same recursion logic used by the task detail page.
 */
export function collectDefaults(
  properties: Record<string, Record<string, unknown>>,
): Record<string, unknown> {
  const vals: Record<string, unknown> = {};
  for (const [name, prop] of Object.entries(properties)) {
    if (prop.default !== undefined) {
      vals[name] = prop.default;
    } else if (prop.type === "object" && prop.properties) {
      vals[name] = collectDefaults(
        prop.properties as Record<string, Record<string, unknown>>,
      );
    } else if (
      prop.type === "array" &&
      (prop.items as Record<string, unknown>)?.type === "object" &&
      (prop.items as Record<string, unknown>)?.properties
    ) {
      const itemProps = (prop.items as Record<string, unknown>)
        .properties as Record<string, Record<string, unknown>>;
      const firstRow: Record<string, unknown> = {};
      for (const [k, p] of Object.entries(itemProps)) {
        if (p.default !== undefined) {
          firstRow[k] = p.default;
        }
      }
      vals[name] = [firstRow];
    } else if (prop.enum && Array.isArray(prop.enum) && prop.enum.length > 0) {
      vals[name] = prop.enum[0];
    } else if (prop.type === "boolean") {
      vals[name] = false;
    }
  }
  return vals;
}

/**
 * Renders all properties from a JSON Schema as structured form fields.
 *
 * Each property is rendered by SchemaField which handles all common types:
 * object (nested), enum, array-of-enums, array-of-objects (growing table),
 * boolean, number, integer, string (short/long).
 */
export function SchemaForm({ schema, values, onChange }: SchemaFormProps) {
  if (!schema || typeof schema !== "object") return null;

  const props = (
    "properties" in schema && typeof schema.properties === "object"
      ? (schema.properties as Record<string, Record<string, unknown>>)
      : {}
  );
  const requiredFields = ("required" in schema && Array.isArray(schema.required)
    ? (schema.required as string[])
    : []) as string[];

  const entries = Object.entries(props);
  if (entries.length === 0) return null;

  return (
    <div className="space-y-4">
      {entries.map(([name, prop]) => (
        <SchemaField
          key={name}
          name={name}
          property={prop}
          value={values[name]}
          onChange={(v) => onChange({ ...values, [name]: v })}
          required={requiredFields.includes(name)}
          valuesContext={values}
        />
      ))}
    </div>
  );
}
