import { useState, useCallback, useRef, useEffect } from "react";
import { batchJobsApi } from "@/api/endpoints";

export interface ChunkedUploadProgress {
  uploadId?: string;
  status: "idle" | "uploading" | "processing" | "completed" | "error";
  progress: number; // 0-100
  uploadedBytes: number;
  totalBytes: number;
  error?: string;
  jobId?: string;
  message?: string;
}

export interface ChunkedUploadOptions {
  chunkSize?: number;
  maxRetries?: number;
  retryDelay?: number;
  onProgress?: (progress: ChunkedUploadProgress) => void;
}

const DEFAULT_CHUNK_SIZE = 50 * 1024 * 1024; // 50MB
const DEFAULT_MAX_RETRIES = 3;
const DEFAULT_RETRY_DELAY = 1000; // 1 second

export function useChunkedUpload(projectId: string, options: ChunkedUploadOptions = {}) {
  const {
    chunkSize = DEFAULT_CHUNK_SIZE,
    maxRetries = DEFAULT_MAX_RETRIES,
    retryDelay = DEFAULT_RETRY_DELAY,
    onProgress,
  } = options;

  const [progress, setProgress] = useState<ChunkedUploadProgress>({
    status: "idle",
    progress: 0,
    uploadedBytes: 0,
    totalBytes: 0,
  });

  const abortControllerRef = useRef<AbortController | null>(null);
  const onProgressRef = useRef(onProgress);
  useEffect(() => {
    onProgressRef.current = onProgress;
  }, [onProgress]);

  /** Always merge into latest state — avoids stale closures wiping status/totalBytes during chunk loop. */
  const updateProgress = useCallback((update: Partial<ChunkedUploadProgress>) => {
    setProgress((prev) => {
      const newProgress = { ...prev, ...update };
      onProgressRef.current?.(newProgress);
      return newProgress;
    });
  }, []);

  const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

  const uploadFile = useCallback(async (file: File): Promise<string | null> => {
    try {
      abortControllerRef.current = new AbortController();

      updateProgress({
        status: "uploading",
        progress: 0,
        uploadedBytes: 0,
        totalBytes: file.size,
        error: undefined,
      });

      // Initialize upload session
      const initResponse = await batchJobsApi.initUpload(projectId, file.name, file.size);
      const uploadId = initResponse.data.upload_id;

      updateProgress({
        uploadId,
        message: "Upload initialized, starting chunks...",
      });

      // Calculate chunks
      const totalChunks = Math.ceil(file.size / chunkSize);
      let uploadedBytes = 0;

      // Upload chunks
      for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex++) {
        if (abortControllerRef.current?.signal.aborted) {
          throw new Error("Upload aborted");
        }

        const start = chunkIndex * chunkSize;
        const end = Math.min(start + chunkSize - 1, file.size - 1);
        const chunkData = file.slice(start, end + 1);

        let retries = 0;
        let chunkUploaded = false;

        while (!chunkUploaded && retries <= maxRetries) {
          try {
            if (abortControllerRef.current?.signal.aborted) {
              throw new Error("Upload aborted");
            }

            // Convert chunk to ArrayBuffer
            const arrayBuffer = await chunkData.arrayBuffer();

            // Upload chunk
            await batchJobsApi.uploadChunk(projectId, uploadId, arrayBuffer, start, end, file.size);

            uploadedBytes = end + 1;
            const progress = (uploadedBytes / file.size) * 100;

            updateProgress({
              progress: Math.round(progress),
              uploadedBytes,
              message: `Uploading chunk ${chunkIndex + 1}/${totalChunks}`,
            });

            chunkUploaded = true;
          } catch (error) {
            retries++;
            console.warn(`Chunk ${chunkIndex + 1} upload failed (attempt ${retries}/${maxRetries + 1}):`, error);

            if (retries > maxRetries) {
              throw new Error(`Chunk ${chunkIndex + 1} failed after ${maxRetries} retries: ${error}`);
            }

            // Wait before retrying
            await sleep(retryDelay * retries);
          }
        }
      }

      // Complete upload
      updateProgress({
        progress: 100,
        message: "Finalizing upload...",
      });

      await batchJobsApi.completeUpload(projectId, uploadId);

      updateProgress({
        status: "processing",
        message: "Upload completed, processing archive...",
      });

      // Poll for completion
      let processingComplete = false;
      while (!processingComplete) {
        if (abortControllerRef.current?.signal.aborted) {
          throw new Error("Upload aborted");
        }

        await sleep(2000); // Poll every 2 seconds

        try {
          const statusResponse = await batchJobsApi.getUploadStatus(projectId, uploadId);
          const status = statusResponse.data;

          updateProgress({
            status: status.status as "uploading" | "processing" | "completed" | "error",
            message: status.message || "Processing...",
            error: status.error,
            jobId: status.job_id,
          });

          if (status.status === "completed") {
            processingComplete = true;
            return status.job_id || null;
          } else if (status.status === "error") {
            throw new Error(status.error || "Processing failed");
          }
        } catch (error) {
          console.warn("Status polling failed:", error);
          // Continue polling on error
        }
      }

      return null;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Upload failed";
      updateProgress({
        status: "error",
        error: errorMessage,
      });
      throw error;
    }
  }, [projectId, chunkSize, maxRetries, retryDelay, updateProgress]);

  const cancel = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      updateProgress({
        status: "error",
        error: "Upload cancelled",
      });
    }
  }, [updateProgress]);

  const reset = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setProgress({
      status: "idle",
      progress: 0,
      uploadedBytes: 0,
      totalBytes: 0,
    });
  }, []);

  return {
    progress,
    uploadFile,
    cancel,
    reset,
    isUploading: progress.status === "uploading" || progress.status === "processing",
  };
}