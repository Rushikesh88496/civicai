"use client";

import * as React from "react";
import { motion } from "framer-motion";
import {
  Camera,
  RefreshCw,
  X,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  UploadCloud,
  Video,
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
  const [dragging, setDragging] = React.useState(false);

  const images = items.filter((i) => i.file.type.startsWith("image/")).length;
  const videos = items.filter((i) => i.file.type.startsWith("video/")).length;

  // Shared validation + upload pipeline for both the file picker and drag-drop.
  const processFiles = (fileList: FileList | File[]) => {
    const files = Array.from(fileList);
    const pickedImages = files.filter((f) => f.type.startsWith("image/"));
    const pickedVideo = files.find((f) => f.type.startsWith("video/"));

    if (fileTooBig(pickedVideo)) {
      alert(`Short videos up to ${MAX_VIDEO_MB} MB are allowed.`);
      return;
    }
    if (pickedImages.length + images > MAX_IMAGES) {
      alert(`You can attach up to ${MAX_IMAGES} images.`);
      return;
    }
    for (const image of pickedImages) {
      if (fileTooBig(image)) {
        alert(`Images up to ${MAX_IMAGE_MB} MB are allowed.`);
        return;
      }
      void startUpload(image);
    }
    if (pickedVideo) {
      if (videos >= 1) {
        alert("You can attach one short video.");
        return;
      }
      void startUpload(pickedVideo);
    }
  };

  const handleSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    // Reset the input so re-selecting the same file is allowed.
    event.target.value = "";
    processFiles(files);
  };

  const onDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.files && event.dataTransfer.files.length > 0) {
      processFiles(event.dataTransfer.files);
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
        role="button"
        tabIndex={0}
        aria-label="Upload photos or a short video"
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          "group flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-4 py-10 text-center transition-all duration-200 sm:py-12",
          dragging
            ? "border-primary-500 bg-primary-50/60 ring-2 ring-primary-200"
            : "border-border-strong bg-slate-50/60 hover:border-primary-400 hover:bg-primary-50/40"
        )}
      >
        <div className="flex gap-2">
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary-50 text-primary-600 ring-1 ring-inset ring-primary-100">
            <Camera className="h-6 w-6" />
          </span>
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100 text-slate-500 ring-1 ring-inset ring-slate-200">
            <Video className="h-6 w-6" />
          </span>
        </div>
        <div>
          <p className="text-sm font-semibold text-slate-800">
            {dragging ? "Drop to add your evidence" : "Add photos or a short video"}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {MAX_IMAGES} images ({MAX_IMAGE_MB} MB each) and one short video ({MAX_VIDEO_MB} MB)
          </p>
          <p className="mt-2 inline-flex items-center gap-1.5 text-xs font-medium text-primary-600">
            <UploadCloud className="h-3.5 w-3.5" />
            Drag &amp; drop or click to browse
          </p>
        </div>
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
        <>
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {items.map((item, index) => (
              <MediaThumbnail
                key={item.key}
                item={item}
                index={index}
                onRemove={() => removeItem(item.key)}
                onRetry={() => retryItem(item.key)}
              />
            ))}
          </ul>
          <p className="text-xs text-slate-400">
            {images} of {MAX_IMAGES} images {videos > 0 && "· 1 video"} — uploads happen
            automatically as files are added.
          </p>
        </>
      )}
    </div>
  );
}

function MediaThumbnail({
  item,
  index,
  onRemove,
  onRetry,
}: {
  item: UploadItem;
  index: number;
  onRemove: () => void;
  onRetry: () => void;
}) {
  const isVideo = item.file.type.startsWith("video/");
  return (
    <motion.li
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay: index * 0.04, duration: 0.18 }}
      className="group relative overflow-hidden rounded-xl border border-border-soft bg-white shadow-sm"
    >
      <div className="relative">
        {isVideo ? (
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
          aria-label={`Remove ${item.file.name}`}
          className="absolute right-1.5 top-1.5 rounded-full bg-black/60 p-1 text-white opacity-100 transition-opacity hover:bg-black/80 sm:opacity-0 sm:group-hover:opacity-100"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="flex items-center gap-2 px-2 py-1.5">
        {item.status === "uploading" && (
          <>
            <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-primary-600" />
            <Progress value={item.progress} className="flex-1" />
            <span className="w-9 shrink-0 text-right text-[10px] tabular-nums text-slate-500">
              {item.progress}%
            </span>
          </>
        )}
        {item.status === "done" && (
          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-success-700">
            <CheckCircle2 className="h-3.5 w-3.5" /> Uploaded
          </span>
        )}
        {item.status === "error" && (
          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-danger-700">
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
        <p className="px-2 pb-1.5 text-[10px] text-danger-600">{item.error}</p>
      )}
    </motion.li>
  );
}