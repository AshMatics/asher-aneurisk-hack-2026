import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { findSample } from "./fixtures";

function jsonFile(content: string, name = "result.json"): File {
  return new File([content], name, { type: "application/json" });
}

const hospitalB = JSON.stringify(findSample("hospital_b")?.data);

async function upload(file: File) {
  const user = userEvent.setup();
  await user.upload(screen.getByTestId("file-input"), file);
  return user;
}

describe("App", () => {
  it("starts with the file picker, drop zone and samples, and makes no request", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<App />);
    expect(screen.getByRole("button", { name: "Open result.json" })).toBeInTheDocument();
    expect(screen.getByTestId("drop-zone")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Try a sample" })).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("opens a valid result.json and shows the verdict first", async () => {
    render(<App />);
    await upload(jsonFile(hospitalB));
    expect(await screen.findByRole("heading", { name: "SlicePoint fit check: Hospital B" })).toBeInTheDocument();
    expect(screen.getByTestId("final-verdict")).toHaveTextContent("NO-GO");
    const card = document.getElementById("check-repeats") as HTMLElement;
    expect(within(card).getByText("Problem")).toBeInTheDocument();
    expect(within(card).getByText(/effective n 32\./)).toBeInTheDocument();
    expect(screen.queryByText(/Show provisional scores/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("self-comparison")).not.toBeInTheDocument();
  });

  it("drills into a check's evidence", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /^Hospital C with provisional scores/ }));
    const card = document.getElementById("check-scanning") as HTMLElement;
    const toggle = within(card).getByRole("button", { name: "Show the numbers" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(within(card).getByRole("button", { name: "Hide the numbers" })).toHaveAttribute("aria-expanded", "true");
    expect(within(card).getByText("Sub-factors")).toBeInTheDocument();
    expect(within(card).getAllByText("Failing").length).toBe(4);
  });

  it("shows a clear error for a file that is not JSON", async () => {
    render(<App />);
    await upload(jsonFile("hello", "notes.json"));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not open notes.json");
    expect(alert).toHaveTextContent("This file is not valid JSON");
  });

  it("names an unsupported schema version", async () => {
    render(<App />);
    await upload(jsonFile(hospitalB.replace('"schema_version":"0.1.0"', '"schema_version":"9.0.0"')));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent('Unsupported schema version "9.0.0"');
  });

  it("lists contract violations for an invalid file", async () => {
    render(<App />);
    const bad = JSON.parse(hospitalB) as Record<string, unknown>;
    bad.checks = [];
    await upload(jsonFile(JSON.stringify(bad)));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This result does not match the SlicePoint contract");
    expect(within(alert).getByRole("list", { name: "Problems found" })).toHaveTextContent("checks: must NOT have fewer than 1 items");
  });

  it("opens a dropped file", async () => {
    render(<App />);
    fireEvent.drop(screen.getByTestId("drop-zone"), { dataTransfer: { files: [jsonFile(hospitalB)] } });
    expect(await screen.findByTestId("final-verdict")).toHaveTextContent("NO-GO");
  });

  it("offers the provisional-score toggle only when the file has scores, off by default", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /Hospital C with provisional scores/ }));
    const toggle = screen.getByRole("checkbox", { name: /Show provisional scores \(unratified, method provisional-v0\)/ });
    expect(toggle).not.toBeChecked();
    expect(screen.queryByTestId("score-scanning")).not.toBeInTheDocument();
    await user.click(toggle);
    expect(screen.getByTestId("score-scanning")).toHaveTextContent("Provisional score: 11 / 100 (target 70)");
  });

  it("shows a human override prominently", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /committee override/ }));
    expect(screen.getByTestId("final-verdict")).toHaveTextContent("GO");
    expect(screen.getByTestId("override")).toHaveTextContent("changed from BORDERLINE to GO");
    expect(screen.getByTestId("override")).toHaveTextContent("AI governance committee (example)");
    // The example is hospital_a against a reference built from hospital_a: flagged next to the verdict.
    expect(screen.getByTestId("self-comparison")).toHaveTextContent("compared against its own reference data");
  });

  it("moves between tabs with the keyboard and sorts cases", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /^Hospital B NO-GO/ }));
    const overview = screen.getByRole("tab", { name: "Overview" });
    overview.focus();
    await user.keyboard("{ArrowRight}{ArrowRight}{ArrowRight}");
    const casesTab = screen.getByRole("tab", { name: /Cases to review/ });
    expect(casesTab).toHaveAttribute("aria-selected", "true");
    expect(casesTab).toHaveFocus();
    expect(screen.getByRole("heading", { name: "Cases to review" })).toBeInTheDocument();
    const before = screen.getAllByTestId("case-row").map((r) => r.textContent);
    await user.click(screen.getByRole("button", { name: /Difference/ }));
    const after = screen.getAllByTestId("case-row").map((r) => r.textContent);
    expect(after).toHaveLength(before.length);
    expect(after).not.toEqual(before);
  });
});
