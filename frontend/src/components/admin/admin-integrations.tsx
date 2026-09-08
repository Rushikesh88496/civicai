"use client";

import * as React from "react";
import { Cpu, Loader2, TestTube2, Save, Trash2 } from "lucide-react";
import { ApiError } from "@/lib/auth-api";
import {
  fetchAdminConfig,
  updateAdminConfig,
  clearAdminConfig,
  testGroqConfig,
  type ConfigItem,
  type ConfigTest,
} from "@/lib/admin-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";

export function AdminIntegrations() {
  const [items, setItems] = React.useState<ConfigItem[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [mutating, setMutating] = React.useState<string | null>(null);
  const [testResult, setTestResult] = React.useState<ConfigTest | null>(null);
  const [testLoading, setTestLoading] = React.useState(false);
  const [draftValues, setDraftValues] = React.useState<Record<string, string>>({});
  const [tick, setTick] = React.useState(0);

  const reload = React.useCallback(() => {
    setLoading(true);
    setError(null);
    setTick((t) => t + 1);
  }, []);

  React.useEffect(() => {
    let active = true;
    fetchAdminConfig()
      .then((data) => {
        if (!active) return;
        setItems(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof ApiError ? err.message : "Unable to load configuration.");
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [tick]);

  const handleSave = async (item: ConfigItem) => {
    const raw = draftValues[item.key] ?? "";
    setMutating(item.key);
    try {
      await updateAdminConfig(item.key, raw);
      setDraftValues((d) => { const next = { ...d }; delete next[item.key]; return next; });
      reload();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Update failed.");
    } finally {
      setMutating(null);
    }
  };

  const handleClear = async (item: ConfigItem) => {
    if (!confirm(`Clear ${item.label}? This removes the override and reverts to .env.`)) return;
    setMutating(item.key);
    try {
      await clearAdminConfig(item.key);
      reload();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Clear failed.");
    } finally {
      setMutating(null);
    }
  };

  const handleTestGroq = async () => {
    setTestLoading(true);
    setTestResult(null);
    try {
      setTestResult(await testGroqConfig());
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Test failed.");
    } finally {
      setTestLoading(false);
    }
  };

  if (loading && items.length === 0 && !error) {
    return <LoadingState message="Loading integrations…" />;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">AI & Integrations</h1>
        <p className="text-sm text-slate-500">System configuration · Fernet-encrypted secret storage for all 12 settings</p>
      </div>

      {error && <ErrorState title="Failed to load configuration" description={error} />}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Cpu className="h-5 w-5 text-ai-600" /> System Settings ({items.length})
          </CardTitle>
          <CardDescription>Overrides are stored securely; values are masked in responses.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {items.map((item) => (
            <div key={item.key} className="flex flex-col gap-3 rounded-lg border border-border-soft p-4 sm:flex-row sm:items-center sm:gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-slate-900">{item.label}</span>
                  <Badge variant="outline" className="text-xs">{item.category}</Badge>
                  {item.is_secret && <Badge variant="warning" className="text-xs">Secret</Badge>}
                  {item.configured && <Badge variant="success" className="text-xs">Configured</Badge>}
                  {!item.configured && <Badge variant="secondary" className="text-xs">Using .env</Badge>}
                </div>
                <div className="mt-1 truncate font-mono text-xs text-slate-500">{item.masked || "—"}</div>
              </div>
              <div className="flex items-center gap-2 sm:ml-auto">
                <Input
                  className="w-48 text-sm"
                  type={item.value_type === "number" ? "number" : "text"}
                  placeholder={item.configured ? "New value…" : "Set override…"}
                  value={draftValues[item.key] ?? ""}
                  onChange={(e) => setDraftValues((d) => ({ ...d, [item.key]: e.target.value }))}
                  disabled={!item.is_editable}
                />
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => handleSave(item)}
                  disabled={!item.is_editable || !draftValues[item.key] || mutating === item.key}
                  aria-label={`Save ${item.label}`}
                >
                  {mutating === item.key ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                </Button>
                {item.configured && item.is_editable && (
                  <Button
                    size="icon"
                    variant="ghost"
                    onClick={() => handleClear(item)}
                    disabled={mutating === item.key}
                    aria-label={`Clear ${item.label}`}
                  >
                    <Trash2 className="h-4 w-4 text-danger-500" />
                  </Button>
                )}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TestTube2 className="h-5 w-5 text-ai-600" /> Groq LLM Connection Test
          </CardTitle>
          <CardDescription>Verifies the configured Groq key and base URL are reachable.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Button onClick={handleTestGroq} disabled={testLoading} variant="outline">
            {testLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <TestTube2 className="mr-2 h-4 w-4" />}
            Run Connection Test
          </Button>
          {testResult && (
            <div className={`rounded-lg border p-4 text-sm ${testResult.reachable ? "border-success-200 bg-success-50" : "border-danger-200 bg-danger-50"}`}>
              <div className="flex items-center gap-2">
                <Badge variant={testResult.reachable ? "success" : "destructive"}>
                  {testResult.reachable ? "Reachable" : "Unreachable"}
                </Badge>
                <span className="text-slate-700">{testResult.message}</span>
              </div>
              {testResult.latency_ms != null && (
                <p className="mt-1 text-xs text-slate-500">Latency: {testResult.latency_ms}ms</p>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}