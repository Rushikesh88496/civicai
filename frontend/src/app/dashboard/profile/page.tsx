"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { Loader2, Save } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/components/auth/auth-provider";
import { initials } from "@/components/dashboard/format";
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
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">Profile</h1>
        <p className="mt-1 text-slate-500">Manage your personal and contact information.</p>
      </motion.div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card>
          <CardContent className="flex flex-col items-center p-6 pt-6">
            <Avatar size="lg" alt={user?.full_name} fallback={initials(user?.full_name)} />
            <p className="mt-3 text-lg font-medium text-slate-900">{user?.full_name}</p>
            <p className="text-sm text-slate-500">{user?.email}</p>
            <span className="mt-2 rounded-full bg-primary-50 px-3 py-1 text-xs font-medium text-primary-600">
              {user?.role.name}
            </span>
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
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
                    placeholder="+1 (555) 000-0000"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="city">City</Label>
                  <Input
                    id="city"
                    value={city}
                    onChange={(e) => setCity(e.target.value)}
                    placeholder="Your city"
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

              {message && <p className="text-sm text-success-600">{message}</p>}
              {error && <p className="text-sm text-danger-600">{error}</p>}

              <Button type="submit" disabled={saving}>
                {saving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Save className="h-4 w-4" />
                )}
                <span className="ml-2">Save Changes</span>
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}