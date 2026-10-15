import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { PrivacyNotice, SERVER_PROCESSING_NOTICE } from "@/components/privacy-notice";
import { UploadStage } from "@/components/upload-stage";
import { MetadataTable } from "@/components/metadata-table";
import type { TagEntry } from "@/lib/api";

const ENTRY = (overrides: Partial<TagEntry>): TagEntry => ({
  key: "IFD0:Artist",
  group: "IFD0",
  tag: "Artist",
  value: "Alice Test",
  sensitivity: "high",
  ...overrides,
});

describe("server-processing notice", () => {
  it("shows the exact required wording", () => {
    render(<PrivacyNotice acknowledged={false} onAcknowledged={() => undefined} />);
    expect(screen.getByText(SERVER_PROCESSING_NOTICE)).toBeInTheDocument();
    expect(SERVER_PROCESSING_NOTICE).toContain(
      "Do not upload highly sensitive files unless you trust the hosting provider and understand its infrastructure access.",
    );
  });

  it("states that processing is not local-only", () => {
    render(<PrivacyNotice acknowledged={false} onAcknowledged={() => undefined} />);
    expect(screen.getByText(/not local-only processing/i)).toBeInTheDocument();
  });

  it("reports acknowledgement changes", async () => {
    const onAcknowledged = vi.fn();
    render(<PrivacyNotice acknowledged={false} onAcknowledged={onAcknowledged} />);
    await userEvent.click(screen.getByTestId("privacy-acknowledgement"));
    expect(onAcknowledged).toHaveBeenCalledWith(true);
  });
});

describe("upload stage gating", () => {
  const baseProps = {
    file: new File(["content"], "photo.jpg", { type: "image/jpeg" }),
    onFile: () => undefined,
    maxBytes: 1024 * 1024,
    acceptedExtensions: [".jpg"],
    status: "idle" as const,
    progress: 0,
    error: null,
    onStart: vi.fn(),
    onReset: vi.fn(),
    startLabel: "Inspect metadata",
    processingLabel: "Inspecting…",
    rejectionMessage: null,
    onRejection: () => undefined,
  };

  it("keeps the action disabled until the notice is acknowledged", () => {
    render(<UploadStage {...baseProps} acknowledged={false} onAcknowledged={() => undefined} />);
    expect(screen.getByTestId("start-job")).toBeDisabled();
    expect(screen.getByText(/Acknowledge the server-processing notice/i)).toBeInTheDocument();
  });

  it("enables the action once acknowledged", () => {
    render(<UploadStage {...baseProps} acknowledged onAcknowledged={() => undefined} />);
    expect(screen.getByTestId("start-job")).toBeEnabled();
  });

  it("shows real progress text while a job is running", () => {
    render(
      <UploadStage {...baseProps} acknowledged status="uploading" progress={42} onAcknowledged={() => undefined} />,
    );
    expect(screen.getByTestId("upload-progress")).toBeInTheDocument();
    expect(screen.getByText(/Uploading 42%/)).toBeInTheDocument();
    expect(screen.getByTestId("start-job")).toBeDisabled();
  });

  it("reports processing (not uploading) once the body is sent", () => {
    render(
      <UploadStage {...baseProps} acknowledged status="processing" progress={100} onAcknowledged={() => undefined} />,
    );
    expect(screen.getByText(/Upload complete/)).toBeInTheDocument();
  });

  it("surfaces errors with an actionable message", () => {
    render(
      <UploadStage
        {...baseProps}
        acknowledged
        error={new Error("The metadata engine is temporarily unavailable on this instance.")}
        onAcknowledged={() => undefined}
      />,
    );
    expect(screen.getByTestId("error-block")).toBeInTheDocument();
    expect(screen.getByText(/temporarily unavailable/)).toBeInTheDocument();
  });
});

describe("metadata table", () => {
  const entries = [
    ENTRY({ key: "GPS:GPSLatitude", group: "GPS", tag: "GPSLatitude", value: "51.5 N" }),
    ENTRY({ key: "IFD0:Artist", group: "IFD0", tag: "Artist", value: "Alice Test" }),
    ENTRY({ key: "IFD0:Software", group: "IFD0", tag: "Software", value: "Writer 1.0", sensitivity: "low" }),
  ];

  it("renders every entry and filters by risk", async () => {
    render(<MetadataTable entries={entries} />);
    expect(screen.getByText("GPSLatitude")).toBeInTheDocument();
    expect(screen.getByText("Software")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Low/ }));
    expect(screen.queryByText("GPSLatitude")).not.toBeInTheDocument();
    expect(screen.getByText("Software")).toBeInTheDocument();
  });

  it("filters by free text", async () => {
    render(<MetadataTable entries={entries} />);
    await userEvent.type(screen.getByTestId("metadata-filter"), "artist");
    expect(screen.getByText("Artist")).toBeInTheDocument();
    expect(screen.queryByText("GPSLatitude")).not.toBeInTheDocument();
  });

  it("shows an empty state instead of a blank table", () => {
    render(<MetadataTable entries={[]} emptyMessage="Nothing here." />);
    expect(screen.getByText("Nothing here.")).toBeInTheDocument();
  });
});
