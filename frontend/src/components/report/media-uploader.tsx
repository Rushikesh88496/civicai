"use client";

import * as React from "react";
import {
  ImagePlus,
  Video,
  X,
  RefreshCw,
  Loader2,
  CheckCircle2,
  AlertTriangle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { uploadMedia, type ComplaintMedia } from "@/lib/complaint-api";

const MAX_IMAGE_MB = 10;
const MAX_VIDEO_MB = 50;
const MAX_IMAGES = 6;

type UploadStatus = "uploading" | "done" | "error";

interface UploadItem {
  key: string;
  file: File;
  previewUrl: string;
  status: UploadStatus;
  progress: number;
  media?: ComplaintMedia;
  error?: string;
}

interface MediaUploaderProps {
  onMediaChange: (mediaId: string) => void;
  onMediaRemove: (mediaId: string) => void;
}

// Simple sequential id counter avoids the React-hooks set-state-in-effect lint.
let counter = 0;
function nextKey(): string {
  counter += 1;
  return `media-${Date.now()}-${counter}`;
}

function fileToObjectUrl(file: File): string {
  if (typeof URL !== "undefined" && URL.createObjectURL) {
    return URL.createObjectURL(file);
  }
  return "";
}

export function MediaUploader({ onMediaChange, onMediaRemove }: MediaUploaderProps) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [items, setItems] = React.useState<UploadItem[]>([]);

  const videos = items.filter((i) => i.file.type.startsWith("video/")).length;

  const handleSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    // Reset the input so re-selecting the same file is allowed.
    event.target.value = "";
    const images = files.filter((f) => f.type.startsWith("image/"));
    const video = files.find((f) => f.type.startsWith("video/"));

    if (fileTooBig(video)) {
      alert(`Short videos up to ${MAX_VIDEO_MB} MB are allowed.`);
      return;
    }
    const alreadyUploadedImages = items.length;
    if (images.length + alreadyUploadedImages > MAX_IMAGES) {
      alert(`You can attach up to ${MAX_IMAGES} images.`);
      return;
    }
    for (const image of images) {
      if (fileTooBig(image)) {
        alert(`Images up to ${MAX_IMAGE_MB} MB are allowed.`);
        return;
      }
      void startUpload(image);
    }
    if (video) {
      if (videos >= 1) {
        alert("You can attach one short video.");
        return;
      }
      void startUpload(video);
    }
  };

  const fileTooBig = (file: File | undefined): boolean => {
    if (!file) return false;
    const limit = file.type.startsWith("video/") ? MAX_VIDEO_MB : MAX_IMAGE_MB;
    return file.size > limit * 1024 * 1024;
  };

  const startUpload = async (file: File) => {
    const key = nextKey();
    const previewUrl = fileToObjectUrl(file);
    const entry: UploadItem = { key, file, previewUrl, status: "uploading", progress: 0 };

    setItems((prev) => {
      const withoutVideo = prev.filter(
        (it) => !(file.type.startsWith("video/") && it.file.type.startsWith("video/"))
      );
      return [...withoutVideo, entry];
    });

    try {
      const media = await uploadMedia(file, {
        onProgress: (percent) => updateItem(key, { progress: percent }),
      });
      updateItem(key, { status: "done", progress: 100, media });
      onMediaChange(media.id);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Upload failed.";
      updateItem(key, { status: "error", error: message });
    }
  };

  const updateItem = (key: string, patch: Partial<UploadItem>) => {
    setItems((prev) => prev.map((it) => (it.key === key ? { ...it, ...patch } : it)));
  };

  const removeItem = (key: string) => {
    setItems((prev) => {
      const target = prev.find((it) => it.key === key);
      if (target?.media) {
        const id = target.media.id;
        // Defer so React handles removal of the DOM element first.
        window.setTimeout(() => onMediaRemove(id), 0);
      }
      return prev.filter((it) => it.key !== key);
    });
  };

  const retryItem = (key: string) => {
    const target = items.find((it) => it.key === key);
    if (target) {
      void startUpload(target.file);
    }
  };

  return (
    <div className="space-y-4">
      <div
        className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-gray-300 bg-gray-50 px-4 py-8 text-center transition-colors hover:border-blue-400 hover:bg-blue-50/40"
        onClick={() => inputRef.current?.click()}
      >
        <div className="flex gap-2">
          <span className="rounded-lg bg-blue-100 p-2 text-blue-600">
            <ImagePlus className="h-5 w-5" />
          </span>
          <span className="rounded-lg bg-indigo-100 p-2 text-indigo-600">
            <Video className="h-5 w-5" />
          </span>
        </div>
        <p className="text-sm font-medium text-gray-700">
          Click to upload evidence (photos / short video)
        </p>
        <p className="text-xs text-gray-500">
          Up to {MAX_IMAGES} images ({MAX_IMAGE_MB} MB each) and one short video ({MAX_VIDEO_MB} MB)
        </p>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/webm,video/quicktime"
        multiple
        className="hidden"
        onChange={handleSelect}
      />

      {items.length > 0 && (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {items.map((item) => (
            <MediaThumbnail
              key={item.key}
              item={item}
              onRemove={() => removeItem(item.key)}
              onRetry={() => retryItem(item.key)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function MediaThumbnail({
  item,
  onRemove,
  onRetry,
}: {
  item: UploadItem;
  onRemove: () => void;
  onRetry: () => void;
}) {
  return (
    <li className="group relative overflow-hidden rounded-xl border border-gray-200 bg-white">
      {item.file.type.startsWith("video/") ? (
        <video src={item.previewUrl} className="h-28 w-full object-cover" muted playsInline />
      ) : (
        // Client-side blob URL preview; next/image can't load unoptimized blob: URLs.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={item.previewUrl} alt={item.file.name} className="h-28 w-full object-cover" />
      )}

      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/60 to-transparent p-2">
        <p className="truncate text-[11px] font-medium text-white">{item.file.name}</p>
      </div>

      <button
        type="button"
        onClick={onRemove}
        aria-label="Remove file"
        className="absolute right-1.5 top-1.5 rounded-full bg-black/50 p-1 text-white opacity-0 transition-opacity hover:bg-black/70 group-hover:opacity-100"
      >
        <X className="h-3.5 w-3.5" />
      </button>

      <div className="flex items-center gap-2 px-2 py-1.5">
        {item.status === "uploading" && (
          <>
            <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-600" />
            <Progress value={item.progress} className="flex-1" />
            <span className="w-9 text-right text-[10px] text-gray-500">{item.progress}%</span>
          </>
        )}
        {item.status === "done" && (
          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-green-700">
            <CheckCircle2 className="h-3.5 w-3.5" /> Uploaded
          </span>
        )}
        {item.status === "error" && (
          <span className={cn("inline-flex items-center gap-1 text-[11px] font-medium text-red-700")}>
            <AlertTriangle className="h-3.5 w-3.5" /> Failed
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-6 px-1.5 text-[11px]"
              onClick={onRetry}
            >
              <RefreshCw className="h-3 w-3" /> Retry
            </Button>
          </span>
        )}
      </div>
      {item.status === "error" && item.error && (
        <p className="px-2 pb-1.5 text-[10px] text-red-600">{item.error}</p>
      )}
    </li>
  );
}