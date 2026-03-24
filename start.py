import os
import re
import shutil
import time
import uuid
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
import xml.etree.ElementTree as ET
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from smartfix_config import (
    EXCHANGE_BASE,
    USERNAME,
    PASSWORD,
    SOAP_ADDRESS,
    SOAP_ENDPOINT,
    WSDL_PATH,
    PRIORITY,
    EXPORT_VERIFIER_DOCUMENTS,
    EXPORT_SUPERVISOR_DOCUMENTS,
)
from smartfix_soap import SmartFixSoapClient

SUBSYSTEM_OPTIONS = [
    "RuV_Ersterkennung",
    "RuV_Ersterkennung_Dev",
    "RuV_Luxemburg",
]

CATEGORY_BY_SUBSYSTEM = {
    "RuV_Ersterkennung": ["Ersterkennung", "KFZ"],
    "RuV_Ersterkennung_Dev": ["Ersterkennung"],
    "RuV_Luxemburg": ["Leben"],
}

PRIORITY_OPTIONS = [str(i) for i in range(1, 10)]


def center(win, w=1180, h=880):
    win.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    x, y = (sw - w) // 2, (sh - h) // 3
    win.geometry(f"{w}x{h}+{x}+{y}")


def make_safe(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^A-Za-z0-9_-]", "", text)
    return text or "Dokument"


def build_import_xml(
    stack_id: str,
    pdf_name: str,
    subsystem: str,
    category: str,
    priority: str,
    dpi: str,
    export_verifier_documents: str,
    export_supervisor_documents: str,
) -> str:
    return f'''<STACK Category="{category}" LocationType="FILE" StackID="{stack_id}" SubSystem="{subsystem}" Priority="{priority}" ExportVerifierDocuments="{export_verifier_documents}" ExportSupervisorDocuments="{export_supervisor_documents}">
\t<ATTRIBUTES>
\t\t<KeyValuePair Key="$Dpi" Value="{dpi}"/>
\t</ATTRIBUTES>
\t<IMAGE ImageID="image0" LocationID="Dokument00001/{pdf_name}:0" DocID="Dokument00001" ProcessID=""/>
</STACK>
'''


def wait_for_export_xml(stack_dir: Path, timeout_seconds: int = 60, poll_seconds: float = 1.0) -> Path | None:
    export_path = stack_dir / "export.xml"
    end_time = time.time() + timeout_seconds
    while time.time() < end_time:
        if export_path.exists():
            return export_path
        time.sleep(poll_seconds)
    return None


def parse_export_xml(export_path: Path) -> dict:
    tree = ET.parse(export_path)
    root = tree.getroot()
    result = {
        "stack_id": root.attrib.get("StackID", ""),
        "category": root.attrib.get("Category", ""),
        "subsystem": root.attrib.get("SubSystem", ""),
        "document_status": "",
        "document_class": "",
        "fields": [],
    }
    document = root.find(".//DOCUMENT")
    if document is not None:
        result["document_status"] = document.attrib.get("Status", "")
        result["document_class"] = document.attrib.get("DocClass", "")
    for field in root.findall(".//FIELD"):
        name = field.attrib.get("Name", "")
        value = field.attrib.get("Value", "")
        status = field.attrib.get("Status", "")
        rating = field.attrib.get("Rating", "")
        if name and value:
            result["fields"].append({
                "name": name,
                "value": value,
                "status": status,
                "rating": rating,
            })
    return result


class SmartFixController(tb.Window):
    def __init__(self):
        super().__init__(themename="minty")
        self.title("SmartFix Controller | RuV Ersterkennung")
        center(self)
        self.style_obj = tb.Style()
        self.colors = self.style_obj.colors
        self.path_var = tk.StringVar()
        self.file_var = tk.StringVar(value="Keine Datei ausgewählt")
        self.status = tk.StringVar(value="Bereit")
        self.subsystem_var = tk.StringVar(value="RuV_Ersterkennung")
        self.category_var = tk.StringVar(value="Ersterkennung")
        self.priority_var = tk.StringVar(value=str(PRIORITY))
        self.dpi_var = tk.StringVar(value="300")
        self.export_verifier_var = tk.BooleanVar(
            value=str(EXPORT_VERIFIER_DOCUMENTS).upper() == "TRUE"
        )
        self.export_supervisor_var = tk.BooleanVar(
            value=str(EXPORT_SUPERVISOR_DOCUMENTS).upper() == "TRUE"
        )
        self.result_docclass_var = tk.StringVar(value="-")
        self.result_status_var = tk.StringVar(value="-")
        self.result_stackid_var = tk.StringVar(value="-")
        self.last_created_folder = None
        self.last_stack_id = None
        self.category_combobox = None
        self._build_ui()
        self.update_category_options()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        main = tb.Frame(self, padding=18)
        main.grid(row=0, column=0, sticky=NSEW)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)

        hero = tb.Frame(main, bootstyle="light", padding=20)
        hero.grid(row=0, column=0, sticky=EW, pady=(0, 14))
        hero.columnconfigure(0, weight=1)
        tb.Label(
            hero,
            text="SmartFix Import Tool",
            font=("Segoe UI", 24, "bold")
        ).grid(row=0, column=0, sticky=W)
        tb.Label(
            hero,
            text="PDF auswählen, Stack erzeugen, SOAP Import starten und Verarbeitungsergebnis anzeigen.",
            bootstyle="secondary",
            font=("Segoe UI", 10)
        ).grid(row=1, column=0, sticky=W, pady=(6, 0))

        top = tb.Frame(main)
        top.grid(row=1, column=0, sticky=EW, pady=(0, 14))
        top.columnconfigure(0, weight=3)
        top.columnconfigure(1, weight=2)

        left = tb.Frame(top)
        left.grid(row=0, column=0, sticky=NSEW, padx=(0, 10))
        right = tb.Frame(top)
        right.grid(row=0, column=1, sticky=NSEW)

        file_card = tb.Labelframe(left, text="Datei", padding=16, bootstyle="secondary")
        file_card.pack(fill=X)
        file_card.columnconfigure(1, weight=1)
        tb.Label(file_card, text="PDF auswählen", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky=W, pady=(0, 8))
        tb.Button(
            file_card,
            text="Datei öffnen",
            bootstyle="primary",
            command=self.choose_file
        ).grid(row=0, column=1, sticky=W, pady=(0, 8))
        tb.Entry(
            file_card,
            textvariable=self.file_var,
            state="readonly"
        ).grid(row=1, column=0, columnspan=2, sticky=EW)

        settings_card = tb.Labelframe(left, text="Import-Einstellungen", padding=16, bootstyle="secondary")
        settings_card.pack(fill=X, pady=(12, 0))
        settings_card.columnconfigure(1, weight=1)
        settings_card.columnconfigure(3, weight=1)

        tb.Label(settings_card, text="Mandant", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky=W, pady=6, padx=(0, 10))
        subsystem_cb = tb.Combobox(
            settings_card,
            textvariable=self.subsystem_var,
            state="readonly",
            values=SUBSYSTEM_OPTIONS
        )
        subsystem_cb.grid(row=0, column=1, sticky=EW, pady=6)
        subsystem_cb.bind("<<ComboboxSelected>>", self.on_subsystem_changed)

        tb.Label(settings_card, text="Kategorie", font=("Segoe UI", 10, "bold")).grid(row=0, column=2, sticky=W, pady=6, padx=(20, 10))
        self.category_combobox = tb.Combobox(
            settings_card,
            textvariable=self.category_var,
            state="readonly",
            values=[]
        )
        self.category_combobox.grid(row=0, column=3, sticky=EW, pady=6)

        tb.Label(settings_card, text="Priorität", font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky=W, pady=6, padx=(0, 10))
        tb.Combobox(
            settings_card,
            textvariable=self.priority_var,
            state="readonly",
            values=PRIORITY_OPTIONS
        ).grid(row=1, column=1, sticky=EW, pady=6)

        tb.Label(settings_card, text="DPI", font=("Segoe UI", 10, "bold")).grid(row=1, column=2, sticky=W, pady=6, padx=(20, 10))
        tb.Entry(
            settings_card,
            textvariable=self.dpi_var
        ).grid(row=1, column=3, sticky=EW, pady=6)

        tb.Checkbutton(
            settings_card,
            text="ExportVerifierDocuments",
            variable=self.export_verifier_var,
            bootstyle="round-toggle"
        ).grid(row=2, column=0, columnspan=2, sticky=W, pady=(12, 0))
        tb.Checkbutton(
            settings_card,
            text="ExportSupervisorDocuments",
            variable=self.export_supervisor_var,
            bootstyle="round-toggle"
        ).grid(row=2, column=2, columnspan=2, sticky=W, pady=(12, 0))

        action_card = tb.Labelframe(left, text="Aktionen", padding=16, bootstyle="secondary")
        action_card.pack(fill=X, pady=(12, 0))
        action_card.columnconfigure(0, weight=1)
        action_card.columnconfigure(1, weight=1)
        action_card.columnconfigure(2, weight=1)
        tb.Button(
            action_card,
            text="Import starten",
            bootstyle="success",
            command=self.drop_into_exchange
        ).grid(row=0, column=0, sticky=EW, padx=(0, 8))
        tb.Button(
            action_card,
            text="Ordner öffnen",
            bootstyle="secondary",
            command=self.open_last_folder
        ).grid(row=0, column=1, sticky=EW, padx=4)
        tb.Button(
            action_card,
            text="StackID kopieren",
            bootstyle="info-outline",
            command=self.copy_stack_id
        ).grid(row=0, column=2, sticky=EW, padx=(8, 0))

        result_card = tb.Labelframe(right, text="Letztes Ergebnis", padding=16, bootstyle="success")
        result_card.grid(row=0, column=0, sticky=NSEW)
        result_card.columnconfigure(1, weight=1)
        self._add_result_row(result_card, 0, "StackID", self.result_stackid_var)
        self._add_result_row(result_card, 1, "Dokumentklasse", self.result_docclass_var)
        self._add_result_row(result_card, 2, "Status", self.result_status_var)
        info = tb.Label(
            result_card,
            text="Nach erfolgreicher Verarbeitung werden hier die wichtigsten Ergebnisse angezeigt.",
            bootstyle="secondary",
            wraplength=280,
            justify="left"
        )
        info.grid(row=3, column=0, columnspan=2, sticky=W, pady=(14, 0))

        bottom = tb.Frame(main)
        bottom.grid(row=2, column=0, sticky=NSEW)
        bottom.columnconfigure(0, weight=3)
        bottom.columnconfigure(1, weight=2)
        bottom.rowconfigure(0, weight=1)

        log_card = tb.Labelframe(bottom, text="Protokoll", padding=12, bootstyle="secondary")
        log_card.grid(row=0, column=0, sticky=NSEW, padx=(0, 10))
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(0, weight=1)
        self.out = tk.Text(
            log_card,
            wrap="word",
            height=18,
            borderwidth=0,
            font=("Consolas", 10),
            padx=10,
            pady=10
        )
        self.out.grid(row=0, column=0, sticky=NSEW)
        yscroll1 = tb.Scrollbar(log_card, command=self.out.yview, orient="vertical")
        yscroll1.grid(row=0, column=1, sticky=NS)
        self.out.configure(yscrollcommand=yscroll1.set)

        result_log_card = tb.Labelframe(bottom, text="Erkannte Felder", padding=12, bootstyle="secondary")
        result_log_card.grid(row=0, column=1, sticky=NSEW)
        result_log_card.columnconfigure(0, weight=1)
        result_log_card.rowconfigure(0, weight=1)
        self.result_box = tk.Text(
            result_log_card,
            wrap="word",
            height=18,
            borderwidth=0,
            font=("Consolas", 10),
            padx=10,
            pady=10
        )
        self.result_box.grid(row=0, column=0, sticky=NSEW)
        yscroll2 = tb.Scrollbar(result_log_card, command=self.result_box.yview, orient="vertical")
        yscroll2.grid(row=0, column=1, sticky=NS)
        self.result_box.configure(yscrollcommand=yscroll2.set)

        bg = getattr(self.colors, "inputbg", "#f8f9fa")
        fg = getattr(self.colors, "fg", "#212529")
        caret = getattr(self.colors, "info", "#0dcaf0")
        self.out.configure(bg=bg, fg=fg, insertbackground=caret)
        self.result_box.configure(bg=bg, fg=fg, insertbackground=caret)

        footer = tb.Frame(main, padding=(4, 10, 4, 0))
        footer.grid(row=3, column=0, sticky=EW)
        footer.columnconfigure(1, weight=1)
        tb.Label(
            footer,
            text="Status",
            font=("Segoe UI", 10, "bold")
        ).grid(row=0, column=0, sticky=W)
        self.status_label = tb.Label(
            footer,
            textvariable=self.status,
            bootstyle="secondary",
            font=("Segoe UI", 10)
        )
        self.status_label.grid(row=0, column=1, sticky=W, padx=(10, 0))

    def _add_result_row(self, parent, row, label_text, variable):
        tb.Label(
            parent,
            text=label_text,
            font=("Segoe UI", 10, "bold")
        ).grid(row=row, column=0, sticky=NW, pady=4)
        tb.Label(
            parent,
            textvariable=variable,
            bootstyle="dark",
            wraplength=220,
            justify="left"
        ).grid(row=row, column=1, sticky=W, pady=4, padx=(10, 0))

    def on_subsystem_changed(self, event=None):
        self.update_category_options()

    def update_category_options(self):
        subsystem = self.subsystem_var.get().strip()
        categories = CATEGORY_BY_SUBSYSTEM.get(subsystem, [])
        if self.category_combobox is not None:
            self.category_combobox["values"] = categories
        if categories:
            current_category = self.category_var.get().strip()
            if current_category not in categories:
                self.category_var.set(categories[0])
        else:
            self.category_var.set("")

    def set_status(self, text: str, style: str = "secondary"):
        self.status.set(text)
        self.status_label.configure(bootstyle=style)
        self.update_idletasks()

    def log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.out.insert(END, f"[{ts}] {msg}\n")
        self.out.see(END)
        self.update_idletasks()

    def clear_result_box(self):
        self.result_box.delete("1.0", END)

    def write_result_line(self, text: str):
        self.result_box.insert(END, text + "\n")
        self.result_box.see(END)
        self.update_idletasks()

    def choose_file(self):
        p = filedialog.askopenfilename(
            title="Datei auswählen",
            filetypes=[("PDF", "*.pdf"), ("Alle Dateien", "*.*")],
        )
        if p:
            self.path_var.set(p)
            self.file_var.set(os.path.basename(p))
            self.set_status("Datei gewählt", "info")
            self.log(f"Datei gewählt: {p}")

    def show_export_result(self, parsed: dict):
        self.result_stackid_var.set(parsed["stack_id"] or "-")
        self.result_docclass_var.set(parsed["document_class"] or "-")
        self.result_status_var.set(parsed["document_status"] or "-")
        self.clear_result_box()
        self.write_result_line("VERARBEITUNGSERGEBNIS")
        self.write_result_line("")
        self.write_result_line(f"StackID: {parsed['stack_id']}")
        self.write_result_line(f"Kategorie: {parsed['category']}")
        self.write_result_line(f"Subsystem: {parsed['subsystem']}")
        self.write_result_line(f"Dokumentklasse: {parsed['document_class']}")
        self.write_result_line(f"Status: {parsed['document_status']}")
        self.write_result_line("")
        if parsed["fields"]:
            self.write_result_line("Erkannte Felder:")
            self.write_result_line("")
            for field in parsed["fields"][:15]:
                self.write_result_line(f"{field['name']} = {field['value']}")
                self.write_result_line(f"   Status: {field['status']} | Rating: {field['rating']}")
                self.write_result_line("")
        else:
            self.write_result_line("Keine Felder gefunden.")
        self.log("Verarbeitungsergebnis erfolgreich eingelesen.")

    def drop_into_exchange(self):
        src = self.path_var.get()
        if not src or not os.path.isfile(src):
            messagebox.showwarning("Hinweis", "Bitte zuerst eine Datei auswählen.")
            return

        subsystem = self.subsystem_var.get().strip()
        category = self.category_var.get().strip()
        priority = self.priority_var.get().strip()
        dpi = self.dpi_var.get().strip()

        if subsystem not in SUBSYSTEM_OPTIONS:
            messagebox.showwarning("Hinweis", "Bitte einen gültigen Mandanten auswählen.")
            return
        valid_categories = CATEGORY_BY_SUBSYSTEM.get(subsystem, [])
        if category not in valid_categories:
            messagebox.showwarning("Hinweis", "Bitte eine gültige Kategorie für den gewählten Mandanten auswählen.")
            return
        if priority not in PRIORITY_OPTIONS:
            messagebox.showwarning("Hinweis", "Bitte eine Priorität von 1 bis 9 wählen.")
            return
        if not dpi.isdigit() or int(dpi) <= 0:
            messagebox.showwarning("Hinweis", "Bitte einen gültigen DPI-Wert eingeben, z. B. 300.")
            return

        export_verifier_documents = "TRUE" if self.export_verifier_var.get() else "FALSE"
        export_supervisor_documents = "TRUE" if self.export_supervisor_var.get() else "FALSE"

        self.clear_result_box()
        self.result_stackid_var.set("-")
        self.result_docclass_var.set("-")
        self.result_status_var.set("-")

        src_path = Path(src)
        stack_guid = str(uuid.uuid4())
        safe_stem = make_safe(src_path.stem)
        stack_id = f"{stack_guid}_{safe_stem}"

        # Zielordner unter dem jeweiligen Mandanten-Ordner ablegen
        dest_dir = Path(EXCHANGE_BASE) / subsystem / stack_id
        doc_dir = dest_dir / "Dokument00001"

        try:
            dest_dir.mkdir(parents=True, exist_ok=False)
            doc_dir.mkdir(parents=True, exist_ok=False)
        except Exception as e:
            messagebox.showerror("Fehler", f"Konnte Zielordner nicht erstellen:\n{dest_dir}\n\n{e}")
            return

        pdf_name = f"{stack_id}.pdf"
        dest_pdf = doc_dir / pdf_name
        try:
            shutil.copy2(src_path, dest_pdf)
        except Exception as e:
            messagebox.showerror("Fehler", f"Konnte PDF nicht kopieren:\n{e}")
            return

        import_xml = build_import_xml(
            stack_id=stack_id,
            pdf_name=pdf_name,
            subsystem=subsystem,
            category=category,
            priority=priority,
            dpi=dpi,
            export_verifier_documents=export_verifier_documents,
            export_supervisor_documents=export_supervisor_documents,
        )
        import_path = dest_dir / "import.xml"
        try:
            import_path.write_text(import_xml, encoding="utf-8")
        except Exception as e:
            messagebox.showerror("Fehler", f"Konnte import.xml nicht schreiben:\n{e}")
            return

        self.last_created_folder = str(dest_dir)
        self.last_stack_id = stack_id
        self.set_status("Datei abgelegt, SOAP startet", "warning")
        self.log(f"Ordner erstellt: {dest_dir}")
        self.log(f"Dokumentordner erstellt: {doc_dir}")
        self.log(f"PDF kopiert nach: {dest_pdf}")
        self.log(f"import.xml erstellt: {import_path}")
        self.log(f"Mandant (SubSystem): {subsystem}")
        self.log(f"Kategorie: {category}")
        self.log(f"Priorität: {priority}")
        self.log(f"DPI: {dpi}")
        self.log(f"ExportVerifierDocuments: {export_verifier_documents}")
        self.log(f"ExportSupervisorDocuments: {export_supervisor_documents}")
        self.log(f"StackID: {stack_id}")
        self.log(f"WSDL: {WSDL_PATH}")

        try:
            endpoint = SOAP_ADDRESS + SOAP_ENDPOINT
            self.log(f"SOAP Endpoint: {endpoint}")
            self.log("SOAP Login wird gestartet...")
            soap_client = SmartFixSoapClient(
                wsdl_path=WSDL_PATH,
                endpoint=endpoint,
                username=USERNAME,
                password=PASSWORD,
                subsystem=subsystem,
            )
            self.log("SOAP Login erfolgreich.")
            self.log("execSpl wird aufgerufen...")
            response = soap_client.import_stack(stack_id)
            self.log(f"SOAP Antwort: {response}")
            self.set_status("Import angestoßen, warte auf export.xml", "info")
            self.log("Warte auf export.xml...")
            export_path = wait_for_export_xml(dest_dir, timeout_seconds=60, poll_seconds=1.0)
            if export_path is None:
                self.set_status("Keine export.xml gefunden", "danger")
                self.log("Keine export.xml innerhalb von 60 Sekunden gefunden.")
                messagebox.showwarning(
                    "Hinweis",
                    "Import wurde angestoßen, aber es wurde noch keine export.xml gefunden."
                )
                return
            self.log(f"export.xml gefunden: {export_path}")
            parsed = parse_export_xml(export_path)
            self.show_export_result(parsed)
            if parsed["document_status"].lower() == "sicher":
                self.set_status("Verarbeitung erfolgreich abgeschlossen", "success")
            elif parsed["document_status"]:
                self.set_status(f"Verarbeitung abgeschlossen, Status: {parsed['document_status']}", "warning")
            else:
                self.set_status("Verarbeitung abgeschlossen", "success")
            messagebox.showinfo(
                "Erfolg",
                f"Verarbeitung abgeschlossen.\n\n"
                f"Dokumentklasse: {parsed['document_class']}\n"
                f"Status: {parsed['document_status']}"
            )
        except Exception as e:
            self.set_status("SOAP oder Verarbeitungsfehler", "danger")
            self.log(f"Fehler: {e}")
            messagebox.showerror("Fehler", f"Der Import ist fehlgeschlagen:\n\n{e}")

    def open_last_folder(self):
        if not self.last_created_folder:
            messagebox.showinfo("Info", "Noch kein Ordner erstellt.")
            return
        try:
            os.startfile(self.last_created_folder)
        except Exception as e:
            messagebox.showerror("Fehler", f"Konnte Ordner nicht öffnen:\n{e}")

    def copy_stack_id(self):
        if not self.last_stack_id:
            messagebox.showinfo("Info", "Noch keine StackID vorhanden.")
            return
        self.clipboard_clear()
        self.clipboard_append(self.last_stack_id)
        self.set_status("StackID in Zwischenablage kopiert", "secondary")
        self.log("StackID kopiert.")


if __name__ == "__main__":
    SmartFixController().mainloop()
