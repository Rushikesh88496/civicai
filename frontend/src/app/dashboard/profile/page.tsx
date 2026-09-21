"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { Loader2, MapPin, Save, ShieldCheck } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/components/auth/auth-provider";
import { initials } from "@/components/dashboard/format";
import { roleLabel } from "@/components/layout/nav-config";
import { updateMyProfile } from "@/lib/auth-api";

export default function ProfilePage() {
  const { user, refreshUser } = useAuth();
  const [phone, setPhone] = React.useState(user?.profile?.phone ?? "");
  const [address, setAddress] = React.useState(user?.profile?.address ?? "");
  const [city, setCity] = React.useState(user?.profile?.city ?? "");
  const [timezone, setTimezone] = React.useState(user?.profile?.timezone ?? "");
  const [saving, setSaving] = React.useState(false);
  const [message, setMessage] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      await updateMyProfile({
        phone: phone || null,
        address: address || null,
        city: city || null,
        timezone: timezone || null,
      });
      await refreshUser();
      setMessage("Profile updated successfully.");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to update profile.";
      setError(message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="lg:col-span-1"
        >
          <Card className="h-full">
            <CardContent className="flex h-full flex-col items-center p-6">
              <div className="relative">
                <Avatar size="lg" alt={user?.full_name} fallback={initials(user?.full_name)} />
                <span className="absolute -bottom-1 -right-1 flex h-6 w-6 items-center justify-center rounded-full border-2 border-surface bg-success-500 text-white">
                  <ShieldCheck className="h-3.5 w-3.5" />
                </span>
              </div>
              <p className="mt-3 text-lg font-medium text-slate-900">{user?.full_name}</p>
              <p className="text-sm text-slate-500">{user?.email}</p>
              <span className="mt-2 rounded-full bg-primary-50 px-3 py-1 text-xs font-medium text-primary-700">
                {roleLabel(user?.role.name)}
              </span>

              {user?.ward ? (
                <div className="mt-5 w-full rounded-2xl border border-border-soft bg-gradient-to-br from-slate-50 to-white p-3.5">
                  <div className="flex items-start gap-2.5">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary-50 text-primary-600">
                      <MapPin className="h-5 w-5" />
                    </span>
                    <div className="min-w-0">
                      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                        Registered ward
                      </p>
                      <p className="truncate text-sm font-semibold text-slate-900">
                        {user.ward.name || user.ward.code}
                      </p>
                      <p className="text-xs text-slate-500">{user.ward.code}</p>
                    </div>
                  </div>
                </div>
              ) : null}

              <p className="mt-auto pt-5 text-center text-xs leading-5 text-slate-400">
                Your registered ward was chosen when you created your account and
                determines which civic area you belong to.
              </p>
            </CardContent>
          </Card>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="lg:col-span-2"
        >
          <Card className="h-full">
            <CardHeader>
              <CardTitle>Contact Information</CardTitle>
              <CardDescription>
                These details help your municipality reach you about your complaints.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="phone">Phone</Label>
                    <Input
                      id="phone"
                      value={phone}
                      onChange={(e) => setPhone(e.target.value)}
                      placeholder="+91 00000 00000"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="city">City</Label>
                    <Input
                      id="city"
                      value={city}
                      onChange={(e) => setCity(e.target.value)}
                      placeholder="Pune"
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="address">Address</Label>
                  <Input
                    id="address"
                    value={address}
                    onChange={(e) => setAddress(e.target.value)}
                    placeholder="Street address"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="timezone">Timezone</Label>
                  <Input
                    id="timezone"
                    value={timezone}
                    onChange={(e) => setTimezone(e.target.value)}
                    placeholder="e.g. Asia/Kolkata"
                  />
                </div>

                {message && (
                  <p className="rounded-xl bg-success-50 px-3 py-2 text-sm text-success-700">
                    {message}
                  </p>
                )}
                {error && (
                  <p className="rounded-xl bg-danger-50 px-3 py-2 text-sm text-danger-700">
                    {error}
                  </p>
                )}

                <Button type="submit" disabled={saving} className="gap-2 rounded-xl">
                  {saving ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Save className="h-4 w-4" />
                  )}
                  Save Changes
                </Button>
              </form>
            </CardContent>
          </Card>
        </motion.div>
      </div>
    </div>
  );
}