"use client";

import { useCallback, useEffect, useState } from "react";
import {
  apiGet,
  apiPost,
  apiPut,
  type ObjectStoreBucket,
  type Org,
  type PaginatedResponse,
} from "@/lib/api";

function autoSlug(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

interface BucketsPanelProps {
  apiBasePath?: string;
  showOrg?: boolean;
  hideHeader?: boolean;
  showCreateForm?: boolean;
  onToggleCreateForm?: () => void;
  onCountChange?: (count: number) => void;
}

export default function BucketsPanel({
  apiBasePath = "/api/v1/admin/buckets",
  showOrg = false,
  hideHeader = false,
  showCreateForm: controlledShowForm,
  onToggleCreateForm,
  onCountChange,
}: BucketsPanelProps) {
  const [buckets, setBuckets] = useState<ObjectStoreBucket[]>([]);
  const [loading, setLoading] = useState(true);

  const [orgs, setOrgs] = useState<Org[]>([]);

  const [internalShowForm, setInternalShowForm] = useState(false);
  const showForm = controlledShowForm !== undefined ? controlledShowForm : internalShowForm;
  const toggleForm = onToggleCreateForm || (() => setInternalShowForm((v) => !v));

  const [form, setForm] = useState({
    name: "",
    slug: "",
    description: "",
    bucket_name: "",
    endpoint_url: "",
    region: "",
    access_key: "",
    secret_key: "",
    secure: true,
    is_default: false,
    org_id: "",
  });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const [editItem, setEditItem] = useState<ObjectStoreBucket | null>(null);
  const [editForm, setEditForm] = useState({
    name: "",
    description: "",
    endpoint_url: "",
    region: "",
    access_key: "",
    secret_key: "",
    secure: true,
    is_default: false,
    is_active: true,
  });
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState("");

  const fetchBuckets = useCallback(async () => {
    try {
      const data = await apiGet<PaginatedResponse<ObjectStoreBucket>>(apiBasePath);
      setBuckets(data.items);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [apiBasePath]);

  useEffect(() => {
    fetchBuckets();
    if (showOrg) {
      apiGet<PaginatedResponse<Org>>("/api/v1/admin/orgs", { limit: "200" })
        .then((d) => setOrgs(d.items))
        .catch(console.error);
    }
  }, [fetchBuckets, showOrg]);

  useEffect(() => {
    onCountChange?.(buckets.length);
  }, [buckets.length, onCountChange]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        name: form.name,
        slug: form.slug,
        description: form.description || null,
        bucket_name: form.bucket_name,
        endpoint_url: form.endpoint_url || null,
        region: form.region || null,
        access_key: form.access_key || null,
        secret_key: form.secret_key || null,
        secure: form.secure,
        is_default: form.is_default,
      };
      if (showOrg && form.org_id) {
        payload.org_id = form.org_id;
      }
      await apiPost(apiBasePath, payload);
      setForm({
        name: "", slug: "", description: "", bucket_name: "",
        endpoint_url: "", region: "", access_key: "", secret_key: "",
        secure: true, is_default: false, org_id: "",
      });
      toggleForm();
      await fetchBuckets();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to create bucket";
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  const openEdit = (b: ObjectStoreBucket) => {
    setEditItem(b);
    setEditForm({
      name: b.name,
      description: b.description || "",
      endpoint_url: b.endpoint_url || "",
      region: b.region || "",
      access_key: "",
      secret_key: "",
      secure: b.secure,
      is_default: b.is_default,
      is_active: b.is_active,
    });
    setEditError("");
  };

  const saveEdit = async () => {
    if (!editItem) return;
    setEditSaving(true);
    setEditError("");
    try {
      const payload: Record<string, unknown> = {
        name: editForm.name,
        description: editForm.description || null,
        endpoint_url: editForm.endpoint_url || null,
        region: editForm.region || null,
        secure: editForm.secure,
        is_default: editForm.is_default,
        is_active: editForm.is_active,
      };
      if (editForm.access_key) payload.access_key = editForm.access_key;
      if (editForm.secret_key) payload.secret_key = editForm.secret_key;
      await apiPut(`${apiBasePath}/${editItem.id}`, payload);
      setEditItem(null);
      await fetchBuckets();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to update bucket";
      setEditError(msg);
    } finally {
      setEditSaving(false);
    }
  };

  const toggleActive = async (b: ObjectStoreBucket) => {
    try {
      await apiPut(`${apiBasePath}/${b.id}`, { is_active: !b.is_active });
      await fetchBuckets();
    } catch (e) {
      console.error("Failed to toggle bucket status", e);
    }
  };

  const handleNameChange = (name: string) => {
    setForm((prev) => ({
      ...prev,
      name,
      slug: prev.slug === autoSlug(prev.name) ? autoSlug(name) : prev.slug,
    }));
  };

  return (
    <div className="space-y-6">
      <section>
        {!hideHeader && (
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Object Store Buckets</h2>
              <p className="text-sm text-gray-500">
                Registered S3-compatible storage buckets for dataset transfer
              </p>
            </div>
            <button
              onClick={() => { toggleForm(); setError(""); }}
              title={showForm ? "Cancel" : "Add bucket"}
              className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            >
              {showForm ? (
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              ) : (
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
              )}
            </button>
          </div>
        )}

        {showForm && (
          <form
            onSubmit={handleCreate}
            className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4"
          >
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {showOrg && (
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-700">
                    Organization <span className="text-red-500">*</span>
                  </label>
                  <select
                    required
                    value={form.org_id}
                    onChange={(e) => setForm({ ...form, org_id: e.target.value })}
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                  >
                    <option value="">-- Select organization --</option>
                    {orgs.map((o) => (
                      <option key={o.id} value={o.id}>{o.name}</option>
                    ))}
                  </select>
                </div>
              )}
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  Name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text" required
                  placeholder="e.g. Local MinIO"
                  value={form.name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  Slug <span className="text-red-500">*</span>
                </label>
                <input
                  type="text" required
                  placeholder="local-minio"
                  pattern="^[a-z0-9][a-z0-9._\-]*$"
                  title="Lowercase letters, numbers, dots, hyphens, underscores"
                  value={form.slug}
                  onChange={(e) => setForm({ ...form, slug: e.target.value })}
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  Bucket Name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text" required
                  placeholder="my-bucket"
                  value={form.bucket_name}
                  onChange={(e) => setForm({ ...form, bucket_name: e.target.value })}
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  Endpoint URL
                </label>
                <input
                  type="text"
                  placeholder="https://s3.amazonaws.com (default: platform MinIO)"
                  value={form.endpoint_url}
                  onChange={(e) => setForm({ ...form, endpoint_url: e.target.value })}
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  Region
                </label>
                <input
                  type="text"
                  placeholder="us-east-1"
                  value={form.region}
                  onChange={(e) => setForm({ ...form, region: e.target.value })}
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  Access Key
                </label>
                <input
                  type="password"
                  placeholder="Optional (default: platform credentials)"
                  value={form.access_key}
                  onChange={(e) => setForm({ ...form, access_key: e.target.value })}
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  Secret Key
                </label>
                <input
                  type="password"
                  placeholder="Optional (default: platform credentials)"
                  value={form.secret_key}
                  onChange={(e) => setForm({ ...form, secret_key: e.target.value })}
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  Description
                </label>
                <input
                  type="text"
                  placeholder="Optional description"
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div className="flex items-end gap-4 pb-2">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={form.secure}
                    onChange={(e) => setForm({ ...form, secure: e.target.checked })}
                    className="rounded"
                  />
                  TLS (HTTPS)
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={form.is_default}
                    onChange={(e) => setForm({ ...form, is_default: e.target.checked })}
                    className="rounded"
                  />
                  Default bucket
                </label>
              </div>
            </div>
            {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
            <div className="mt-3">
              <button
                type="submit"
                disabled={saving}
                className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {saving ? "Creating..." : "Create Bucket"}
              </button>
            </div>
          </form>
        )}

        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs font-medium uppercase text-gray-500">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Bucket</th>
                <th className="px-4 py-3">Endpoint</th>
                {showOrg && <th className="px-4 py-3">Organization</th>}
                <th className="px-4 py-3">Credentials</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {loading ? (
                <tr>
                  <td colSpan={showOrg ? 8 : 7} className="px-4 py-8 text-center text-gray-400">
                    Loading buckets...
                  </td>
                </tr>
              ) : buckets.length === 0 ? (
                <tr>
                  <td colSpan={showOrg ? 8 : 7} className="px-4 py-8 text-center text-gray-400">
                    No buckets registered
                  </td>
                </tr>
              ) : (
                buckets.map((b) => (
                  <tr key={b.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium text-gray-900">
                      <div>{b.name}</div>
                      <div className="font-mono text-xs text-gray-400">{b.slug}</div>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-700">
                      {b.bucket_name}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500 max-w-48 truncate">
                      {b.endpoint_url || "(platform default)"}
                    </td>
                    {showOrg && (
                      <td className="px-4 py-3 text-xs text-gray-600">
                        {b.org_name || "\u2014"}
                      </td>
                    )}
                    <td className="px-4 py-3 text-xs text-gray-600">
                      {b.has_access_key ? "✓ Keys stored" : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => toggleActive(b)}
                          className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none ${
                            b.is_active ? "bg-green-500" : "bg-gray-300"
                          }`}
                          title={b.is_active ? "Deactivate" : "Activate"}
                        >
                          <span
                            className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                              b.is_active ? "translate-x-4" : "translate-x-0"
                            }`}
                          />
                        </button>
                        {b.is_default && (
                          <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800">
                            default
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
                      {new Date(b.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => openEdit(b)}
                        title="Edit"
                        className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-blue-600"
                      >
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                        </svg>
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {editItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-lg rounded-lg bg-white p-6 shadow-xl">
            <h3 className="mb-4 text-lg font-semibold text-gray-900">
              Edit Bucket: <span className="font-mono">{editItem.slug}</span>
            </h3>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">Name</label>
                <input
                  type="text" value={editForm.name}
                  onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">Description</label>
                <input
                  type="text" value={editForm.description}
                  onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-600">Endpoint URL</label>
                  <input
                    type="text" value={editForm.endpoint_url}
                    onChange={(e) => setEditForm({ ...editForm, endpoint_url: e.target.value })}
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-600">Region</label>
                  <input
                    type="text" value={editForm.region}
                    onChange={(e) => setEditForm({ ...editForm, region: e.target.value })}
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-600">
                    Access Key (leave blank to keep existing)
                  </label>
                  <input
                    type="password" placeholder="New access key (stored encrypted)"
                    value={editForm.access_key}
                    onChange={(e) => setEditForm({ ...editForm, access_key: e.target.value })}
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-600">
                    Secret Key (leave blank to keep existing)
                  </label>
                  <input
                    type="password" placeholder="New secret key (stored encrypted)"
                    value={editForm.secret_key}
                    onChange={(e) => setEditForm({ ...editForm, secret_key: e.target.value })}
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                  />
                </div>
              </div>
              <div className="flex items-center gap-4">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox" checked={editForm.secure}
                    onChange={(e) => setEditForm({ ...editForm, secure: e.target.checked })}
                    className="rounded"
                  />
                  TLS (HTTPS)
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox" checked={editForm.is_default}
                    onChange={(e) => setEditForm({ ...editForm, is_default: e.target.checked })}
                    className="rounded"
                  />
                  Default bucket
                </label>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <button
                  type="button"
                  onClick={() => setEditForm({ ...editForm, is_active: !editForm.is_active })}
                  className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none ${
                    editForm.is_active ? "bg-green-500" : "bg-gray-300"
                  }`}
                >
                  <span
                    className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                      editForm.is_active ? "translate-x-4" : "translate-x-0"
                    }`}
                  />
                </button>
                Active
              </label>
            </div>
            {editError && <p className="mt-2 text-sm text-red-600">{editError}</p>}
            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => setEditItem(null)}
                className="rounded border border-gray-300 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={saveEdit}
                disabled={editSaving}
                className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {editSaving ? "Saving..." : "Save Changes"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
