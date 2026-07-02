import builtins
import json
import os
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import scrolledtext, ttk

import vidyarishi_login


class QueueWriter:
    def __init__(self, output_queue):
        self.output_queue = output_queue

    def write(self, text):
        if text:
            self.output_queue.put(("log", text))

    def flush(self):
        pass


class VidyarishiGui:
    def __init__(self, root):
        self.root = root
        self.root.title("Vidyarishi Blog Runner")
        self.root.geometry("1120x720")
        self.root.minsize(920, 620)

        self.output_queue = queue.Queue()
        self.input_queue = queue.Queue()
        self.worker = None
        self.run_started_at = None
        self.awaiting_action = False

        self.submitted = tk.IntVar(value=0)
        self.skipped = tk.IntVar(value=0)
        self.failed = tk.IntVar(value=0)
        self.elapsed = tk.StringVar(value="00:00")
        self.status = tk.StringVar(value="Ready")
        self.prompt = tk.StringVar(value="Start the runner, complete OTP in Chrome, then click Continue.")
        self.run_summary = tk.StringVar(value="No run has completed yet.")

        self._build_ui()
        self.load_run_history(select_tab=False)
        self.load_output_paths(select_tab=False)
        self.root.after(100, self._poll_output)

    def _build_ui(self):
        self.root.configure(bg="#eef3fb")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#eef3fb")
        style.configure("Header.TLabel", background="#eef3fb", foreground="#111827", font=("Segoe UI", 20, "bold"))
        style.configure("Sub.TLabel", background="#eef3fb", foreground="#536179", font=("Segoe UI", 10))
        style.configure("Card.TFrame", background="#ffffff", borderwidth=1, relief="solid")
        style.configure("Metric.TLabel", background="#ffffff", font=("Segoe UI", 20, "bold"))
        style.configure("MetricName.TLabel", background="#ffffff", foreground="#536179", font=("Segoe UI", 9))
        style.configure(
            "Accent.TButton",
            background="#334155",
            foreground="#ffffff",
            font=("Segoe UI", 10, "bold"),
            padding=(14, 8),
            bordercolor="#334155",
            lightcolor="#334155",
            darkcolor="#334155",
        )
        style.configure(
            "Soft.TButton",
            background="#f8fafc",
            foreground="#334155",
            font=("Segoe UI", 10),
            padding=(12, 8),
            bordercolor="#cbd5e1",
            lightcolor="#f8fafc",
            darkcolor="#cbd5e1",
        )
        style.configure(
            "Action.TButton",
            background="#f8fafc",
            foreground="#1f2937",
            font=("Segoe UI", 10, "bold"),
            padding=(12, 8),
            bordercolor="#cbd5e1",
            lightcolor="#f8fafc",
            darkcolor="#cbd5e1",
        )
        style.map(
            "Action.TButton",
            background=[("disabled", "#f1f5f9"), ("active", "#e2e8f0")],
            foreground=[("disabled", "#94a3b8"), ("active", "#111827")],
            bordercolor=[("disabled", "#e2e8f0"), ("active", "#94a3b8")],
        )
        style.map(
            "Accent.TButton",
            background=[("disabled", "#cbd5e1"), ("active", "#1f2937")],
            foreground=[("disabled", "#64748b"), ("active", "#ffffff")],
        )
        style.map(
            "Soft.TButton",
            background=[("disabled", "#f1f5f9"), ("active", "#e2e8f0")],
            foreground=[("disabled", "#94a3b8"), ("active", "#111827")],
        )

        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x")

        title_block = ttk.Frame(header)
        title_block.pack(side="left", fill="x", expand=True)
        ttk.Label(title_block, text="Vidyarishi Blog Runner", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            title_block,
            text="Run blog batches, pause for inspection, save places, and review analytics in one control panel.",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        ttk.Button(header, text="Edit Places", style="Soft.TButton", command=self.open_places_editor).pack(
            side="right", padx=(10, 0)
        )
        self.start_button = ttk.Button(header, text="Start Run", style="Accent.TButton", command=self.start)
        self.start_button.pack(side="right", padx=(10, 0))

        metrics = ttk.Frame(outer)
        metrics.pack(fill="x", pady=16)
        self._metric(metrics, "Submitted", self.submitted).pack(side="left", fill="x", expand=True, padx=(0, 10))
        self._metric(metrics, "Skipped", self.skipped).pack(side="left", fill="x", expand=True, padx=10)
        self._metric(metrics, "Failed", self.failed).pack(side="left", fill="x", expand=True, padx=10)
        self._metric(metrics, "Elapsed", self.elapsed).pack(side="left", fill="x", expand=True, padx=(10, 0))

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)

        log_card = ttk.Frame(body, style="Card.TFrame", padding=10)
        log_card.pack(side="left", fill="both", expand=True, padx=(0, 12))
        log_header = ttk.Frame(log_card, style="Card.TFrame")
        log_header.pack(fill="x")
        ttk.Label(log_header, text="Live Logs", background="#ffffff", font=("Segoe UI", 12, "bold")).pack(side="left")
        ttk.Label(
            log_header,
            text="success, warnings, prompts, and errors are color-coded",
            background="#ffffff",
            foreground="#64748b",
            font=("Segoe UI", 9),
        ).pack(side="right")
        self.log = scrolledtext.ScrolledText(
            log_card,
            wrap="word",
            height=25,
            font=("Consolas", 10),
            bg="#0f172a",
            fg="#e5e7eb",
            insertbackground="#e5e7eb",
            relief="flat",
        )
        self.log.pack(fill="both", expand=True, pady=(8, 0))
        self.log.tag_configure("success", foreground="#86efac")
        self.log.tag_configure("error", foreground="#fca5a5")
        self.log.tag_configure("warning", foreground="#fde68a")
        self.log.tag_configure("prompt", foreground="#93c5fd")
        self.log.tag_configure("section", foreground="#f8fafc", font=("Consolas", 10, "bold"))
        self.log.tag_configure("muted", foreground="#94a3b8")
        self.log.configure(state="disabled")

        side = ttk.Frame(body)
        side.pack(side="right", fill="y")

        prompt_card = ttk.Frame(side, style="Card.TFrame", padding=14)
        prompt_card.pack(fill="x")
        ttk.Label(prompt_card, text="Action Center", background="#ffffff", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(
            prompt_card,
            textvariable=self.prompt,
            background="#ffffff",
            foreground="#334155",
            wraplength=310,
            justify="left",
        ).pack(anchor="w", pady=(8, 14))

        buttons = ttk.Frame(prompt_card, style="Card.TFrame")
        buttons.pack(fill="x")
        self.continue_button = ttk.Button(buttons, text="Continue After OTP", style="Action.TButton", command=lambda: self.answer(""))
        self.continue_button.pack(fill="x", pady=3)
        self.pause_button = ttk.Button(buttons, text="Pause Before Next Submit", style="Action.TButton", command=self.pause_note)
        self.pause_button.pack(fill="x", pady=3)
        self.resume_button = ttk.Button(buttons, text="Resume: Submit This Blog", style="Action.TButton", command=lambda: self.answer(""))
        self.resume_button.pack(fill="x", pady=3)
        self.done_button = ttk.Button(buttons, text="Done: I Submitted Manually", style="Action.TButton", command=lambda: self.answer("done"))
        self.done_button.pack(fill="x", pady=3)
        self.skip_button = ttk.Button(buttons, text="Skip This Place", style="Action.TButton", command=lambda: self.answer("skip"))
        self.skip_button.pack(fill="x", pady=3)
        self.debug_button = ttk.Button(buttons, text="Debug Page Details", style="Action.TButton", command=lambda: self.answer("debug"))
        self.debug_button.pack(fill="x", pady=3)
        self.set_action_buttons(False)

        status_card = ttk.Frame(side, style="Card.TFrame", padding=14)
        status_card.pack(fill="both", expand=True, pady=(12, 0))
        ttk.Label(status_card, text="Run Summary", background="#ffffff", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(status_card, textvariable=self.status, background="#ffffff", foreground="#334155", wraplength=310).pack(
            anchor="w", pady=(8, 12)
        )
        ttk.Label(
            status_card,
            textvariable=self.run_summary,
            background="#ffffff",
            foreground="#0f172a",
            wraplength=310,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        self.notebook = ttk.Notebook(status_card)
        self.notebook.pack(fill="both", expand=True)
        self.outputs_tab = ttk.Frame(self.notebook)
        self.history_tab = ttk.Frame(self.notebook)
        self.outputs_text = self._summary_text(self.outputs_tab)
        self.history_text = self._summary_text(self.history_tab)
        self.outputs_text.pack(fill="both", expand=True)
        self.history_text.pack(fill="both", expand=True)
        self.notebook.add(self.outputs_tab, text="Outputs")
        self.notebook.add(self.history_tab, text="History")

    def _metric(self, parent, label, variable):
        frame = ttk.Frame(parent, style="Card.TFrame", padding=14)
        ttk.Label(frame, textvariable=variable, style="Metric.TLabel").pack(anchor="w")
        ttk.Label(frame, text=label, style="MetricName.TLabel").pack(anchor="w")
        return frame

    def _summary_text(self, parent):
        text = scrolledtext.ScrolledText(
            parent,
            wrap="word",
            height=10,
            font=("Consolas", 9),
            bg="#f8fafc",
            fg="#0f172a",
            relief="flat",
        )
        text.tag_configure("heading", foreground="#1d4ed8", font=("Consolas", 9, "bold"))
        text.tag_configure("success", foreground="#15803d")
        text.tag_configure("error", foreground="#b91c1c")
        text.tag_configure("warning", foreground="#b45309")
        text.configure(state="disabled")
        return text

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.start_button.configure(state="disabled")
        self.status.set("Running")
        self.prompt.set("Complete OTP/login in Chrome, then click Continue.")
        self.worker = threading.Thread(target=self._run_script, daemon=True)
        self.run_started_at = time.perf_counter()
        self.worker.start()

    def answer(self, value):
        self.input_queue.put(value)

    def pause_note(self):
        vidyarishi_login.PAUSE_BEFORE_NEXT_SUBMIT = True
        self.prompt.set("Pause requested. The runner will stop before the next submit so you can inspect the blog.")
        self._append_log("Pause requested before next submit.\n", "warning")

    def set_action_buttons(self, enabled):
        state = "normal" if enabled else "disabled"
        for button in (self.resume_button, self.done_button, self.skip_button, self.debug_button):
            button.configure(state=state)

    def gui_input(self, prompt=""):
        self.output_queue.put(("prompt", prompt))
        return self.input_queue.get()

    def _run_script(self):
        original_input = builtins.input
        original_stdout = vidyarishi_login.sys.stdout
        original_stderr = vidyarishi_login.sys.stderr
        builtins.input = self.gui_input
        writer = QueueWriter(self.output_queue)
        vidyarishi_login.sys.stdout = writer
        vidyarishi_login.sys.stderr = writer
        try:
            vidyarishi_login.main()
            self.output_queue.put(("done", "Run complete."))
        except Exception as error:
            self.output_queue.put(("error", str(error)))
        finally:
            builtins.input = original_input
            vidyarishi_login.sys.stdout = original_stdout
            vidyarishi_login.sys.stderr = original_stderr

    def _poll_output(self):
        while True:
            try:
                kind, payload = self.output_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "log":
                self._append_log(payload)
                self._update_metrics_from_log(payload)
            elif kind == "prompt":
                self.prompt.set(payload or "Click Continue to proceed.")
                action_prompt = any(
                    marker in payload
                    for marker in (
                        "Press Enter/Resume",
                        "After fixing the form",
                    )
                )
                self.awaiting_action = action_prompt
                self.set_action_buttons(action_prompt)
                self._append_log(payload + "\n", "prompt")
            elif kind == "done":
                self.status.set(payload)
                self.run_started_at = None
                self.awaiting_action = False
                self.set_action_buttons(False)
                self.start_button.configure(state="normal")
                self.load_run_history()
            elif kind == "error":
                self.failed.set(self.failed.get() + 1)
                self.run_started_at = None
                self.awaiting_action = False
                self.set_action_buttons(False)
                self.status.set(f"Stopped with error: {payload}")
                self.start_button.configure(state="normal")
                self._append_log(f"\nERROR: {payload}\n", "error")

        self._update_elapsed()
        self.root.after(100, self._poll_output)

    def _append_log(self, text, tag=None):
        tag = tag or self.log_tag_for(text)
        self.log.configure(state="normal")
        self.log.insert("end", text, tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def log_tag_for(self, text):
        lower = text.lower()
        if "==========" in text or "run summary" in lower:
            return "section"
        if "error" in lower or "failed" in lower or "problem while creating" in lower:
            return "error"
        if "warning" in lower or "pause requested" in lower or "skipped" in lower:
            return "warning"
        if "submitted for review" in lower or "blog created successfully" in lower or "batch complete" in lower:
            return "success"
        if "press enter" in lower or "click continue" in lower or "otp" in lower:
            return "prompt"
        if text.strip().startswith(("Output files:", "History:", "Confirmed:", "Skipped:", "Failed:")):
            return "muted"
        return None

    def _update_metrics_from_log(self, text):
        if "Batch complete." in text:
            self.status.set(text.strip())
            match = None
            try:
                match = re.search(r"Submitted: (\d+)\. Skipped: (\d+)\. Failed: (\d+)\.", text)
            except Exception:
                match = None
            if match:
                self.submitted.set(int(match.group(1)))
                self.skipped.set(int(match.group(2)))
                self.failed.set(int(match.group(3)))
        if "Run analytics:" in text:
            records = self.read_run_history()
            if records:
                latest = records[-1]
                self.status.set("Last run complete")
                self.run_summary.set(self.summary_card_text(latest))
            else:
                self.status.set(text.strip())

    def _update_elapsed(self):
        if not self.run_started_at:
            return
        seconds = int(time.perf_counter() - self.run_started_at)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            self.elapsed.set(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        else:
            self.elapsed.set(f"{minutes:02d}:{seconds:02d}")

    def load_output_paths(self, select_tab=True):
        sections = [
            ("Confirmed", vidyarishi_login.CONFIRMED_BLOGS_OUTPUT_PATH),
            ("Skipped", vidyarishi_login.SKIPPED_BLOGS_OUTPUT_PATH),
            ("Failed", vidyarishi_login.FAILED_BLOGS_OUTPUT_PATH),
        ]
        chunks = []
        for label, path in sections:
            content = ""
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as file:
                    content = file.read()
            count = len([line for line in content.splitlines() if line.strip()])
            chunks.append(f"{label} ({count})\n{content or '-'}")
        self.write_rich_text(self.outputs_text, "\n\n".join(chunks))
        if select_tab:
            self.notebook.select(self.outputs_tab)

    def read_run_history(self):
        path = vidyarishi_login.RUN_HISTORY_PATH
        records = []
        if not os.path.exists(path):
            return records
        with open(path, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def load_run_history(self, select_tab=True):
        records = self.read_run_history()
        if not records:
            content = "No run history yet."
        else:
            total_runs = len(records)
            total_places = sum(record.get("total", 0) for record in records)
            total_submitted = sum(record.get("submitted", 0) for record in records)
            total_skipped = sum(record.get("skipped", 0) for record in records)
            total_failed = sum(record.get("failed", 0) for record in records)
            total_elapsed = sum(record.get("elapsedSeconds", 0) for record in records)
            success_rate = (total_submitted / total_places * 100) if total_places else 0

            lines = [
                "All-Time Analytics",
                f"Runs:        {total_runs}",
                f"Places:      {total_places}",
                f"Submitted:   {total_submitted}",
                f"Skipped:     {total_skipped}",
                f"Failed:      {total_failed}",
                f"Success:     {success_rate:.1f}%",
                f"Elapsed:     {self.format_duration(total_elapsed)}",
                "",
                "Recent Runs",
            ]
            for record in records[-8:][::-1]:
                lines.extend(
                    [
                        f"- {record.get('startedAt', '-')}",
                        (
                            f"  total={record.get('total', 0)} "
                            f"submitted={record.get('submitted', 0)} "
                            f"skipped={record.get('skipped', 0)} "
                            f"failed={record.get('failed', 0)}"
                        ),
                        (
                            f"  elapsed={self.format_duration(record.get('elapsedSeconds', 0))} "
                            f"avg={record.get('averageSecondsPerBlog', 0):.1f}s/blog "
                            f"success={record.get('successRate', 0):.1f}%"
                        ),
                    ]
                )
            content = "\n".join(lines)

        self.write_rich_text(self.history_text, content)
        if records:
            self.run_summary.set(self.summary_card_text(records[-1]))
        if select_tab:
            self.notebook.select(self.history_tab)

    def write_rich_text(self, widget, content):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        for line in content.splitlines(True):
            stripped = line.strip()
            tag = None
            if stripped in {"All-Time Analytics", "Recent Runs"} or re.match(r"^(Confirmed|Skipped|Failed) \(\d+\)$", stripped):
                tag = "heading"
            elif stripped.startswith("Submitted") or stripped.startswith("Success") or stripped.startswith("Confirmed"):
                tag = "success"
            elif stripped.startswith("Failed") or "failed=" in stripped:
                tag = "error"
            elif stripped.startswith("Skipped") or "skipped=" in stripped:
                tag = "warning"
            widget.insert("end", line, tag)
        widget.configure(state="disabled")

    def summary_card_text(self, record):
        return (
            f"Submitted {record.get('submitted', 0)} of {record.get('total', 0)} places\n"
            f"Skipped {record.get('skipped', 0)} | Failed {record.get('failed', 0)}\n"
            f"Success {record.get('successRate', 0):.1f}% | "
            f"Avg {record.get('averageSecondsPerBlog', 0):.1f}s/blog\n"
            f"Elapsed {self.format_duration(record.get('elapsedSeconds', 0))}"
        )

    def format_duration(self, seconds):
        seconds = int(round(seconds))
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes}m {seconds}s"
        if minutes:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    def open_places_editor(self):
        window = tk.Toplevel(self.root)
        window.title("Edit Places")
        window.geometry("520x520")
        window.configure(bg="#eef3fb")
        window.transient(self.root)

        frame = ttk.Frame(window, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Edit Places", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text="Enter one place per line. Saving updates PLACES in your .env file.",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(4, 10))

        text = scrolledtext.ScrolledText(
            frame,
            wrap="word",
            font=("Segoe UI", 10),
            height=18,
            bg="#ffffff",
            fg="#111827",
            relief="flat",
            padx=10,
            pady=10,
        )
        text.pack(fill="both", expand=True)
        current_places = self.read_env_places()
        text.insert("1.0", "\n".join(current_places))

        def save():
            raw = text.get("1.0", "end").strip()
            places = [line.strip() for line in raw.splitlines() if line.strip()]
            self.write_env_places(places)
            self.status.set(f"Saved {len(places)} places to .env")
            self._append_log(f"Saved {len(places)} places to .env\n")
            window.destroy()

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Save Places", style="Accent.TButton", command=save).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=window.destroy).pack(side="right", padx=(0, 8))

    def read_env_places(self):
        env_path = os.path.abspath(".env")
        if not os.path.exists(env_path):
            return []
        with open(env_path, "r", encoding="utf-8") as file:
            for line in file:
                if line.startswith("PLACES="):
                    raw = line.split("=", 1)[1].strip()
                    return [place.strip() for place in raw.split(",") if place.strip()]
        return []

    def write_env_places(self, places):
        env_path = os.path.abspath(".env")
        lines = []
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as file:
                lines = file.readlines()

        new_places_line = f"PLACES={','.join(places)}\n"
        wrote = False
        for index, line in enumerate(lines):
            if line.startswith("PLACES="):
                lines[index] = new_places_line
                wrote = True
                break
        if not wrote:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            lines.append(new_places_line)

        with open(env_path, "w", encoding="utf-8") as file:
            file.writelines(lines)


def main():
    root = tk.Tk()
    VidyarishiGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
