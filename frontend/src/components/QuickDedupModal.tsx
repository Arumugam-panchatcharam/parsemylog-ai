import React, { useState, useEffect } from "react";
import { useProject } from "@/hooks/useProject";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";
import { filesApi } from "@/api/endpoints";

interface QuickDedupModalProps {
  isOpen: boolean;
  onClose: () => void;
  originalLine: string;
  onConfirm: (pattern: string) => Promise<void>;
}

export const QuickDedupModal: React.FC<QuickDedupModalProps> = ({
  isOpen,
  onClose,
  originalLine,
  onConfirm,
}) => {
  const { projectId } = useProject();
  const [editedPattern, setEditedPattern] = useState("");
  const [previewLines, setPreviewLines] = useState<string[]>([]);
  const [previewCount, setPreviewCount] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [patternValid, setPatternValid] = useState(true);
  const [patternError, setPatternError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!isOpen || !originalLine) {
      reset();
      return;
    }

    generatePattern();
  }, [isOpen, originalLine]);

  // Handle ESC key to close modal
  useEffect(() => {
    const handleEscKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };

    if (isOpen) {
      document.addEventListener("keydown", handleEscKey);
      return () => document.removeEventListener("keydown", handleEscKey);
    }
  }, [isOpen, onClose]);

  const reset = () => {
    setEditedPattern("");
    setPreviewLines([]);
    setPreviewCount(0);
    setError(null);
    setIsLoading(false);
    setPatternValid(true);
    setPatternError(null);
  };

  const generatePattern = async () => {
    setIsLoading(true);
    setError(null);

    try {
      if (!projectId) {
        throw new Error("Project ID not found");
      }

      // Call the backend to generate pattern
      const response = await filesApi.dedupFromLine(projectId, originalLine);

      if (!response.data.success) {
        throw new Error(response.data.error || "Failed to generate pattern");
      }

      setEditedPattern(response.data.generated_pattern);
      setPatternValid(response.data.pattern_valid);
      setPatternError(response.data.pattern_error);
      setPreviewCount(response.data.preview_count);
      setPreviewLines(response.data.preview_lines || []);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to generate pattern";
      setError(message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleConfirm = async () => {
    if (!editedPattern.trim()) {
      setError("Pattern cannot be empty");
      return;
    }

    setIsSubmitting(true);
    try {
      await onConfirm(editedPattern);
      onClose();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to confirm";
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
      <div className="bg-card border border-border rounded-lg shadow-2xl max-w-2xl w-full max-h-[85vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border bg-card shrink-0">
          <h2 className="text-sm font-semibold">Remove duplicate lines like this</h2>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground transition-colors p-1"
            title="Close (ESC)"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Original Line */}
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-2">
              Original Log Line
            </label>
            <textarea
              value={originalLine}
              readOnly
              className="w-full p-2 bg-muted text-foreground font-mono text-xs border border-border rounded resize-none"
              rows={2}
            />
          </div>

          {/* Generated Pattern */}
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-2">
              Regex Pattern
            </label>
            <textarea
              value={editedPattern}
              onChange={(e) => setEditedPattern(e.target.value)}
              className="w-full p-2 bg-muted text-foreground font-mono text-xs border border-border rounded resize-none"
              rows={2}
              disabled={isLoading}
            />
            {!patternValid && patternError && (
              <div className="mt-2 p-2 bg-destructive/10 border border-destructive/30 text-destructive text-xs rounded">
                Invalid regex: {patternError}
              </div>
            )}
          </div>

          {/* Preview */}
          {previewLines.length > 0 && (
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-2">
                Preview - {previewCount} line{previewCount !== 1 ? "s" : ""} match
              </label>
              <div className="bg-muted border border-border rounded p-2 max-h-40 overflow-y-auto space-y-1">
                {previewLines.map((line, idx) => (
                  <div
                    key={idx}
                    className="font-mono text-xs text-muted-foreground break-words line-clamp-1"
                  >
                    {line}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Error Alert */}
          {error && (
            <Alert variant="destructive">
              <div className="text-xs">{error}</div>
            </Alert>
          )}

          {/* Loading State */}
          {isLoading && (
            <Alert>
              <div className="text-xs">Generating pattern...</div>
            </Alert>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-border bg-card px-6 py-3 flex gap-2 justify-end shrink-0">
          <Button
            variant="outline"
            onClick={onClose}
            disabled={isLoading || isSubmitting}
            className="text-xs"
          >
            Cancel
          </Button>
          <Button
            onClick={handleConfirm}
            disabled={
              isLoading || isSubmitting || !patternValid || !editedPattern.trim()
            }
            className="text-xs"
          >
            {isSubmitting ? "Adding..." : "Add Rule"}
          </Button>
        </div>
      </div>
    </div>
  );
};
