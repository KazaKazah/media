#!/usr/bin/env python3
"""Small desktop launcher for hentaidad_sync.py using only Python stdlib."""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


class DownloaderWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Hentaidad Album Sync")
        self.root.geometry("760x560")
        self.process: subprocess.Popen | None = None
        self.messages: queue.Queue[str | None] = queue.Queue()

        container = ttk.Frame(root, padding=18)
        container.pack(fill="both", expand=True)
        ttk.Label(container, text="Синхронизация альбомов", font=("", 18, "bold")).pack(anchor="w")
        ttk.Label(
            container,
            text="Выберите папку. Повторные запуски сохраняют только новые изображения.",
        ).pack(anchor="w", pady=(4, 16))

        destination_row = ttk.Frame(container)
        destination_row.pack(fill="x")
        self.destination = tk.StringVar()
        ttk.Entry(destination_row, textvariable=self.destination).pack(side="left", fill="x", expand=True)
        ttk.Button(destination_row, text="Выбрать папку", command=self.choose_destination).pack(side="left", padx=(8, 0))

        settings = ttk.LabelFrame(container, text="Настройки", padding=12)
        settings.pack(fill="x", pady=14)
        self.delay = tk.StringVar(value="2")
        self.max_albums = tk.StringVar(value="0")
        self.dry_run = tk.BooleanVar(value=False)
        ttk.Label(settings, text="Пауза между запросами, сек.").grid(row=0, column=0, sticky="w")
        ttk.Entry(settings, textvariable=self.delay, width=10).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(settings, text="Максимум альбомов (0 — все)").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(settings, textvariable=self.max_albums, width=10).grid(row=1, column=1, sticky="w", padx=8, pady=(8, 0))
        ttk.Checkbutton(settings, text="Только проверить, ничего не скачивать", variable=self.dry_run).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

        self.start_button = ttk.Button(container, text="Начать синхронизацию", command=self.start)
        self.start_button.pack(anchor="w")
        self.stop_button = ttk.Button(container, text="Остановить", command=self.stop, state="disabled")
        self.stop_button.pack(anchor="w", pady=(8, 12))

        self.log = tk.Text(container, height=18, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True)
        self.root.after(100, self.read_messages)

    def choose_destination(self):
        selected = filedialog.askdirectory(title="Куда сохранять альбомы")
        if selected:
            self.destination.set(selected)

    def start(self):
        destination = Path(self.destination.get()).expanduser()
        if not self.destination.get():
            messagebox.showwarning("Папка не выбрана", "Сначала выберите папку для альбомов.")
            return
        try:
            delay = float(self.delay.get())
            max_albums = int(self.max_albums.get())
        except ValueError:
            messagebox.showerror("Ошибка", "Пауза и количество альбомов должны быть числами.")
            return
        script = Path(__file__).with_name("hentaidad_sync.py")
        state = destination / ".hentaidad-sync.sqlite3"
        command = [
            sys.executable, str(script),
            "--output", str(destination),
            "--state-file", str(state),
            "--delay", str(delay),
            "--max-albums", str(max_albums),
            "--confirm-adult-and-rights",
        ]
        if self.dry_run.get():
            command.append("--dry-run")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.append_log(f"Запуск: {' '.join(command)}\n")
        threading.Thread(target=self.run_process, args=(command,), daemon=True).start()

    def run_process(self, command: list[str]):
        try:
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert self.process.stdout
            for line in self.process.stdout:
                self.messages.put(line)
            code = self.process.wait()
            self.messages.put(f"\nЗавершено с кодом {code}.\n")
        except Exception as error:
            self.messages.put(f"\nОшибка запуска: {error}\n")
        finally:
            self.process = None
            self.messages.put(None)

    def stop(self):
        if self.process:
            self.process.terminate()
            self.append_log("Остановка… данные прогресса будут сохранены.\n")

    def read_messages(self):
        try:
            while True:
                message = self.messages.get_nowait()
                if message is None:
                    self.start_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                else:
                    self.append_log(message)
        except queue.Empty:
            pass
        self.root.after(100, self.read_messages)

    def append_log(self, message: str):
        self.log.configure(state="normal")
        self.log.insert("end", message)
        self.log.see("end")
        self.log.configure(state="disabled")


def main():
    root = tk.Tk()
    DownloaderWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
