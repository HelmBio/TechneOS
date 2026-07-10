"use client";

import DatasetSelector from "@/components/dataset-selector";
import GrowingTable from "./growing-table";

export interface SchemaFieldProps {
  name: string;
  property: Record<string, unknown>;
  value: unknown;
  onChange: (value: unknown) => void;
  required?: boolean;
  valuesContext?: Record<string, unknown>;
}

export function SchemaField({
  name,
  property,
  value,
  onChange,
  required = false,
  valuesContext,
}: SchemaFieldProps) {
  const label = (property.title as string) || name;
  const description = property.description as string | undefined;

  const dependsOn = property["x-depends-on"] as
    | { property?: string; value?: unknown }
    | undefined;
  if (
    dependsOn?.property &&
    valuesContext?.[dependsOn.property] !== dependsOn.value
  ) {
    return null;
  }

  // object with nested properties → recursive sub-section
  if (property.type === "object" && property.properties) {
    const subProps = property.properties as Record<
      string,
      Record<string, unknown>
    >;
    const subRequired = (property.required as string[]) || [];
    const objValue = (value as Record<string, unknown>) || {};
    return (
      <div className="space-y-2">
        <h4 className="text-sm font-semibold text-gray-800">{label}</h4>
        {description && (
          <p className="text-xs text-gray-500">{description}</p>
        )}
        <div className="rounded-lg border border-gray-200 p-4 space-y-3">
          {Object.entries(subProps).map(([subName, subProp]) => (
            <SchemaField
              key={subName}
              name={subName}
              property={subProp}
              value={objValue[subName]}
              onChange={(v) => {
                onChange({ ...objValue, [subName]: v });
              }}
              required={subRequired.includes(subName)}
              valuesContext={valuesContext}
            />
          ))}
        </div>
      </div>
    );
  }

  // string with format "dataset" → DatasetSelector
  if (
    property.type === "string" &&
    (property.format as string) === "dataset"
  ) {
    return (
      <label className="block">
        <span className="block text-sm font-medium text-gray-700 mb-1">
          {label}
          {description && (
            <span className="ml-2 text-xs font-normal text-gray-500">
              — {description}
            </span>
          )}
          {required ? <span className="text-red-500 ml-1">*</span> : null}
        </span>
        <DatasetSelector
          value={(value as string) || ""}
          onChange={(v) => onChange(v)}
        />
      </label>
    );
  }

  // enum → select
  if (property.enum) {
    return (
      <label className="block">
        <span className="block text-sm font-medium text-gray-700 mb-1">
          {label}
          {description && (
            <span className="ml-2 text-xs font-normal text-gray-500">
              — {description}
            </span>
          )}
          {required ? <span className="text-red-500 ml-1">*</span> : null}
        </span>
        <select
          value={(value as string) || ""}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        >
          {!required && <option value="">Select...</option>}
          {(property.enum as string[]).map((opt: string) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
      </label>
    );
  }

  // array-of-enums → checkbox group
  if (
    property.type === "array" &&
    (property.items as Record<string, unknown>)?.enum
  ) {
    const items = property.items as { enum: string[] };
    const selected = (Array.isArray(value) ? value : []) as string[];
    return (
      <div>
        <span className="block text-sm font-medium text-gray-700 mb-2">
          {label}
          {description && (
            <span className="ml-2 text-xs font-normal text-gray-500">
              — {description}
            </span>
          )}
          {required ? <span className="text-red-500 ml-1">*</span> : null}
        </span>
        <div className="flex flex-wrap gap-3">
          {items.enum.map((opt: string) => (
            <label
              key={opt}
              className="flex items-center gap-1.5 text-sm text-gray-700"
            >
              <input
                type="checkbox"
                checked={selected.includes(opt)}
                onChange={(e) => {
                  if (e.target.checked) {
                    onChange([...selected, opt]);
                  } else {
                    onChange(selected.filter((m) => m !== opt));
                  }
                }}
                className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              {opt}
            </label>
          ))}
        </div>
      </div>
    );
  }

  // array-of-objects → GrowingTable
  if (
    property.type === "array" &&
    (property.items as Record<string, unknown>)?.type === "object" &&
    (property.items as Record<string, unknown>)?.properties
  ) {
    const items = property.items as {
      properties: Record<string, Record<string, unknown>>;
      required?: string[];
    };
    const arr = (Array.isArray(value) ? value : []) as Record<
      string,
      unknown
    >[];
    return (
      <GrowingTable
        items={items}
        value={arr}
        onChange={(v) => onChange(v)}
        label={label}
        required={required}
        description={description}
      />
    );
  }

  // boolean → checkbox
  if (property.type === "boolean") {
    return (
      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input
          type="checkbox"
          checked={!!value}
          onChange={(e) => onChange(e.target.checked)}
          className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
        />
        {label}
        {description && (
          <span className="ml-2 text-xs font-normal text-gray-500">
            — {description}
          </span>
        )}
        {required ? <span className="text-red-500 ml-1">*</span> : null}
      </label>
    );
  }

  // number / integer → number input
  if (property.type === "number" || property.type === "integer") {
    return (
      <label className="block">
        <span className="block text-sm font-medium text-gray-700 mb-1">
          {label}
          {description && (
            <span className="ml-2 text-xs font-normal text-gray-500">
              — {description}
            </span>
          )}
          {required ? <span className="text-red-500 ml-1">*</span> : null}
        </span>
        <input
          type="number"
          value={(value as number | undefined) ?? ""}
          onChange={(e) =>
            onChange(e.target.value ? Number(e.target.value) : null)
          }
          placeholder={description}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
      </label>
    );
  }

  // string (long) → textarea
  const isLong =
    (property.format as string) === "long" ||
    ((property.maxLength as number) || 0) > 100;
  if (isLong) {
    return (
      <label className="block">
        <span className="block text-sm font-medium text-gray-700 mb-1">
          {label}
          {description && (
            <span className="ml-2 text-xs font-normal text-gray-500">
              — {description}
            </span>
          )}
          {required ? <span className="text-red-500 ml-1">*</span> : null}
        </span>
        <textarea
          value={(value as string) || ""}
          onChange={(e) => onChange(e.target.value)}
          rows={3}
          placeholder={description}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
      </label>
    );
  }

  // default: string (short) → text input
  return (
    <label className="block">
      <span className="block text-sm font-medium text-gray-700 mb-1">
        {label}
        {description && (
          <span className="ml-2 text-xs font-normal text-gray-500">
            — {description}
          </span>
        )}
        {required ? <span className="text-red-500 ml-1">*</span> : null}
      </span>
      <input
        type="text"
        value={(value as string) || ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder={description}
        className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
      />
    </label>
  );
}
