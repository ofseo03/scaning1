"""간단한 창 인터페이스 (tkinter).

명령줄이 익숙하지 않은 사용자를 위한 최소한의 화면이다.
파일을 고르고, 형식을 선택하고, 변환 단추를 누르면 된다.
"""

from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path

from .config import ConvertOptions, PreprocessOptions

WINDOW_TITLE = "scan2doc — 사진·PDF를 Word/한글 문서로"
FILE_TYPES = [
    ("지원하는 모든 파일", "*.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp *.pdf"),
    ("이미지", "*.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp"),
    ("PDF", "*.pdf"),
    ("모든 파일", "*.*"),
]
OUTPUT_FORMATS = [
    ("docx", "Word 문서 (.docx)", True),
    ("hwpx", "한글 문서 (.hwpx)", True),
    ("txt", "일반 텍스트 (.txt)", False),
    ("md", "마크다운 (.md)", False),
]


def main() -> int:
    """GUI를 띄운다. tkinter가 없으면 안내하고 종료한다."""
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print(
            "GUI를 쓰려면 tkinter가 필요합니다.\n"
            "  · Ubuntu/Debian: sudo apt install python3-tk\n"
            "  · Fedora       : sudo dnf install python3-tkinter\n"
            "  · macOS/Windows: 공식 파이썬 설치본에는 기본 포함돼 있습니다.\n"
            "\n대신 명령줄을 쓰실 수 있습니다:  scan2doc 사진.jpg",
            file=sys.stderr,
        )
        return 1

    app = Scan2DocApp()
    app.run()
    return 0


class Scan2DocApp:
    """변환 창."""

    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.messages: queue.Queue[tuple[str, str]] = queue.Queue()
        self.worker: threading.Thread | None = None

        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.root.geometry("760x620")
        self.root.minsize(680, 560)

        self.output_dir = tk.StringVar(value="")
        self.language = tk.StringVar(value="kor+eng")
        self.merge = tk.BooleanVar(value=False)
        self.binarize = tk.BooleanVar(value=False)
        self.embed_image = tk.BooleanVar(value=False)
        self.format_vars = {
            name: tk.BooleanVar(value=default) for name, _, default in OUTPUT_FORMATS
        }
        self.progress_value = tk.DoubleVar(value=0.0)
        self.status = tk.StringVar(value="변환할 사진이나 PDF를 추가해 주세요.")

        self._build_ui()
        self.root.after(120, self._drain_messages)

    # --- 화면 구성 --------------------------------------------------------

    def _build_ui(self) -> None:
        tk, ttk = self.tk, self.ttk
        pad = {"padx": 10, "pady": 6}

        files = ttk.LabelFrame(self.root, text="1. 변환할 파일")
        files.pack(fill="both", expand=True, **pad)

        self.file_list = tk.Listbox(files, selectmode="extended", height=8)
        self.file_list.pack(side="left", fill="both", expand=True, padx=(10, 4), pady=10)
        scroll = ttk.Scrollbar(files, orient="vertical", command=self.file_list.yview)
        scroll.pack(side="left", fill="y", pady=10)
        self.file_list.configure(yscrollcommand=scroll.set)

        buttons = ttk.Frame(files)
        buttons.pack(side="left", fill="y", padx=10, pady=10)
        ttk.Button(buttons, text="파일 추가", command=self._add_files).pack(fill="x", pady=2)
        ttk.Button(buttons, text="폴더 추가", command=self._add_folder).pack(fill="x", pady=2)
        ttk.Button(buttons, text="선택 삭제", command=self._remove_selected).pack(fill="x", pady=2)
        ttk.Button(buttons, text="모두 비우기", command=self._clear_files).pack(fill="x", pady=2)

        settings = ttk.LabelFrame(self.root, text="2. 설정")
        settings.pack(fill="x", **pad)

        row = ttk.Frame(settings)
        row.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(row, text="저장 위치").pack(side="left")
        ttk.Entry(row, textvariable=self.output_dir).pack(
            side="left", fill="x", expand=True, padx=8
        )
        ttk.Button(row, text="찾아보기", command=self._choose_output).pack(side="left")

        row = ttk.Frame(settings)
        row.pack(fill="x", padx=10, pady=4)
        ttk.Label(row, text="출력 형식").pack(side="left")
        for name, label, _ in OUTPUT_FORMATS:
            ttk.Checkbutton(row, text=label, variable=self.format_vars[name]).pack(
                side="left", padx=(8, 0)
            )

        row = ttk.Frame(settings)
        row.pack(fill="x", padx=10, pady=(4, 10))
        ttk.Label(row, text="인식 언어").pack(side="left")
        ttk.Combobox(
            row,
            textvariable=self.language,
            values=["kor+eng", "kor", "eng", "kor+eng+jpn", "kor+eng+chi_sim"],
            width=16,
        ).pack(side="left", padx=8)
        ttk.Checkbutton(row, text="하나로 합치기", variable=self.merge).pack(side="left", padx=8)
        ttk.Checkbutton(row, text="흑백 이진화", variable=self.binarize).pack(side="left", padx=8)
        ttk.Checkbutton(row, text="원본 이미지 포함", variable=self.embed_image).pack(
            side="left", padx=8
        )

        run = ttk.Frame(self.root)
        run.pack(fill="x", **pad)
        self.convert_button = ttk.Button(run, text="변환 시작", command=self._start)
        self.convert_button.pack(side="left")
        ttk.Button(run, text="환경 점검", command=self._run_doctor).pack(side="left", padx=8)
        ttk.Progressbar(
            run, variable=self.progress_value, maximum=1.0, mode="determinate"
        ).pack(side="left", fill="x", expand=True, padx=10)

        ttk.Label(self.root, textvariable=self.status).pack(anchor="w", padx=20)

        log_frame = ttk.LabelFrame(self.root, text="진행 상황")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(log_frame, height=8, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, padx=10, pady=10)

    # --- 파일 목록 --------------------------------------------------------

    def _add_files(self) -> None:
        from tkinter import filedialog

        paths = filedialog.askopenfilenames(title="변환할 파일 선택", filetypes=FILE_TYPES)
        for path in paths:
            self._append_path(path)

    def _add_folder(self) -> None:
        from tkinter import filedialog

        folder = filedialog.askdirectory(title="폴더 선택")
        if folder:
            self._append_path(folder)

    def _append_path(self, path: str) -> None:
        if path not in self.file_list.get(0, "end"):
            self.file_list.insert("end", path)

    def _remove_selected(self) -> None:
        for index in reversed(self.file_list.curselection()):
            self.file_list.delete(index)

    def _clear_files(self) -> None:
        self.file_list.delete(0, "end")

    def _choose_output(self) -> None:
        from tkinter import filedialog

        folder = filedialog.askdirectory(title="저장할 폴더 선택")
        if folder:
            self.output_dir.set(folder)

    # --- 실행 -------------------------------------------------------------

    def _collect_options(self) -> ConvertOptions:
        formats = [name for name in self.format_vars if self.format_vars[name].get()]
        return ConvertOptions(
            output=Path(self.output_dir.get()) if self.output_dir.get() else None,
            formats=formats or ["docx"],
            merge=self.merge.get(),
            language=self.language.get().strip() or "kor+eng",
            embed_image=self.embed_image.get(),
            preprocess=PreprocessOptions(binarize=self.binarize.get()),
        )

    def _start(self) -> None:
        from tkinter import messagebox

        if self.worker is not None and self.worker.is_alive():
            return
        inputs = list(self.file_list.get(0, "end"))
        if not inputs:
            messagebox.showinfo("scan2doc", "변환할 파일을 먼저 추가해 주세요.")
            return
        if not any(var.get() for var in self.format_vars.values()):
            messagebox.showinfo("scan2doc", "출력 형식을 하나 이상 선택해 주세요.")
            return

        self.convert_button.state(["disabled"])
        self.progress_value.set(0.0)
        self._clear_log()
        self.status.set("변환 중…")

        options = self._collect_options()
        self.worker = threading.Thread(
            target=self._convert_worker, args=(inputs, options), daemon=True
        )
        self.worker.start()

    def _convert_worker(self, inputs: list[str], options: ConvertOptions) -> None:
        from .errors import Scan2DocError
        from .pipeline import convert

        def progress(stage: str, message: str, ratio: float) -> None:
            self.messages.put(("progress", f"{ratio}|{message}"))

        try:
            results = convert(inputs, options, progress=progress)
        except Scan2DocError as exc:
            self.messages.put(("error", str(exc)))
            return
        except Exception as exc:  # 예상 못 한 오류도 창에 보여 준다
            self.messages.put(("error", f"예상하지 못한 오류: {exc}"))
            return

        lines = []
        for result in results:
            conf = result.confidence
            conf_text = f"{conf:.0f}%" if conf >= 0 else "-"
            lines.append(f"{result.page_count}쪽 · 신뢰도 {conf_text} · {result.elapsed:.1f}초")
            lines += [f"    → {path}" for path in result.outputs]
            if 0 <= conf < 70:
                lines.append("    ⚠️  인식률이 낮습니다. '흑백 이진화'를 켜고 다시 해 보세요.")
        self.messages.put(("done", "\n".join(lines)))

    def _run_doctor(self) -> None:
        from .doctor import run_doctor

        self._clear_log()
        result = run_doctor()
        self._write_log("\n".join(result.lines))
        self.status.set("점검을 마쳤습니다." if result.ok else "빠진 구성 요소가 있습니다.")

    # --- 메시지 펌프 ------------------------------------------------------

    def _drain_messages(self) -> None:
        from tkinter import messagebox

        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "progress":
                    ratio, _, message = payload.partition("|")
                    self.progress_value.set(float(ratio))
                    self.status.set(message)
                    self._write_log(f"… {message}")
                elif kind == "done":
                    self.progress_value.set(1.0)
                    self.status.set("변환이 끝났습니다.")
                    self._write_log("\n변환 완료\n" + payload)
                    self.convert_button.state(["!disabled"])
                elif kind == "error":
                    self.progress_value.set(0.0)
                    self.status.set("오류가 났습니다.")
                    self._write_log("오류: " + payload)
                    self.convert_button.state(["!disabled"])
                    messagebox.showerror("scan2doc", payload)
        except queue.Empty:
            pass
        self.root.after(120, self._drain_messages)

    def _write_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
