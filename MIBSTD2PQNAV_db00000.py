# ----------------------------------------------------------------------------------
# Description:
# Ce script est conçu pour extraire les données d'une base de données SQLite
# provenant d'un système d'infodivertissement automobile MIB STD2 PQ +nav.
# Le fichier de la base de données est généralement situé dans le chemin :
# Partition3\organizer\database\db0000057, mais le nom du fichier peut varier.
#
# Auteur:   [Votre Nom Ici]
# Contact:  [Votre Email Ici]
# Date:     30/08/2025
#
# Le script extrait les contacts, l'historique de navigation, les dernières
# destinations et la table des graphemes, puis les affiche dans une interface
# graphique avec des onglets. Il permet également d'effectuer des recherches,
# de trier les colonnes et d'exporter toutes ces données dans des fichiers CSV séparés.
# ----------------------------------------------------------------------------------

import sqlite3
from pathlib import Path
import sys
import json
import csv
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# -----------------------------
# Processeur de Base de Données
# -----------------------------
class DBProcessor:
    """Lit les informations depuis les fichiers de base de données SQLite MIB2."""
    
    QUERIES = {
        "contacts": """
            SELECT p.persID, prof.profileName, prof.macAddress, fn.graphem AS firstName, 
                   ln.graphem AS lastName, org.graphem AS organization
            FROM personalTable AS p
            LEFT JOIN profileTable AS prof ON p.profileID = prof.profileID
            LEFT JOIN graphemTable AS fn ON p.firstNameGraphem = fn.graphemID
            LEFT JOIN graphemTable AS ln ON p.lastNameGraphem = ln.graphemID
            LEFT JOIN graphemTable AS org ON p.organizationGraphem = org.graphemID
            WHERE firstName IS NOT NULL OR lastName IS NOT NULL OR organization IS NOT NULL
        """,
        "nav_history": """
            SELECT h.ID, h.name, h.countryAbbreviation, h.hash, h.flags, h.status, hex(l.navData) as navDataHex
            FROM navHistoryTable AS h
            LEFT JOIN navLocationTable AS l ON h.navLocID = l.navID
        """,
        "last_destinations": """
            SELECT d.lastDestinationID, d.name, d.hashCode, d.status, hex(l.navData) as navDataHex
            FROM lastDestinationTable AS d
            LEFT JOIN navLocationTable AS l ON d.navLocID = l.navID
        """,
        "graphems": "SELECT graphemID, graphemHash, graphem, graphemSound, profileID FROM graphemTable"
    }
    PHONE_Q = "SELECT persID, phoneNumber FROM phoneNumberTable"
    ADDRESS_Q = "SELECT persID, road, houseNumber, zipCode, locality, region, country FROM addressTable"

    def __init__(self, file_paths):
        self.files = [Path(p) for p in file_paths]
        self.processed_data = {}

    def _safe_fetchall(self, conn, query):
        try:
            cur = conn.cursor()
            cur.execute(query)
            return cur.fetchall()
        except sqlite3.Error:
            return []

    def process(self):
        """Traite tous les fichiers DB et stocke les données par fichier."""
        self.processed_data.clear()
        for db_path in self.files:
            db_key = str(db_path)
            self.processed_data[db_key] = {}
            try:
                with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                    conn.row_factory = sqlite3.Row

                    # --- Contacts ---
                    phones = {}
                    for row in self._safe_fetchall(conn, self.PHONE_Q):
                        phones.setdefault(row['persID'], []).append(str(row['phoneNumber']))

                    addresses = {}
                    for row in self._safe_fetchall(conn, self.ADDRESS_Q):
                        parts = [row['road'], row['houseNumber'], row['zipCode'], row['locality'], row['region'], row['country']]
                        full_address = " ".join([str(p) for p in parts if p]).strip()
                        if full_address: addresses.setdefault(row['persID'], []).append(full_address)
                    
                    main_rows = self._safe_fetchall(conn, self.QUERIES["contacts"])
                    contacts_list = []
                    for row in main_rows:
                        pers_id = row['persID']
                        contact_dict = {
                            "profile_name": row['profileName'] or "", "mac_address": row['macAddress'] or "",
                            "pers_id": pers_id, "first_name": row['firstName'] or "",
                            "last_name": row['lastName'] or "", "organization": row['organization'] or "",
                            "phones": " | ".join(phones.get(pers_id, [])),
                            "addresses": " || ".join(addresses.get(pers_id, []))
                        }
                        contacts_list.append(contact_dict)
                    self.processed_data[db_key]['contacts'] = sorted(contacts_list, key=lambda x: (x["profile_name"], x["last_name"], x["first_name"]))
                    
                    # --- Autres Tables ---
                    for table_name in ["nav_history", "last_destinations", "graphems"]:
                        rows = self._safe_fetchall(conn, self.QUERIES[table_name])
                        self.processed_data[db_key][table_name] = [dict(row) for row in rows]
            except Exception as e:
                print(f"Erreur lors du traitement de {db_path.name}: {e}", file=sys.stderr)

# -----------------------------
# Application GUI Tkinter
# -----------------------------
class App(tk.Tk):
    """Fenêtre principale de l'application graphique."""
    def __init__(self):
        super().__init__()
        self.title("Extracteur de Base de Données MIB STD2 PQ")
        self.geometry("1400x800")

        self.selected_files = []
        self.status_var = tk.StringVar(value="Prêt. Veuillez ajouter des fichiers de base de données.")
        self.search_var = tk.StringVar()
        self.proc = None
        self.sort_state = {}

        self._build_ui()

    def _build_ui(self):
        top_frame = ttk.Frame(self, padding=8)
        top_frame.pack(side=tk.TOP, fill=tk.X)
        ttk.Button(top_frame, text="Ajouter Fichier(s) DB", command=self.add_files).pack(side=tk.LEFT, padx=4)
        ttk.Button(top_frame, text="Vider la Liste", command=self.clear_files).pack(side=tk.LEFT, padx=4)
        ttk.Button(top_frame, text="Extraire les Données", command=self.run_analysis, style="Accent.TButton").pack(side=tk.LEFT, padx=12)
        ttk.Button(top_frame, text="Exporter Tout en CSVs", command=self.export_all_csvs).pack(side=tk.LEFT, padx=4)
        ttk.Style(self).configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
        
        files_frame = ttk.LabelFrame(self, text="Fichiers Sélectionnés", padding=8)
        files_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=4)
        sb_files = ttk.Scrollbar(files_frame, orient="vertical")
        sb_files.pack(side=tk.RIGHT, fill=tk.Y)
        self.files_list = tk.Listbox(files_frame, height=4, yscrollcommand=sb_files.set)
        self.files_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_files.config(command=self.files_list.yview)

        search_frame = ttk.Frame(self, padding=(8, 0, 8, 4))
        search_frame.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(search_frame, text="Rechercher:").pack(side=tk.LEFT, padx=(0, 4))
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        search_entry.bind("<KeyRelease>", self._perform_search)
        ttk.Button(search_frame, text="Effacer", command=self._clear_search).pack(side=tk.LEFT, padx=4)

        self.notebook = ttk.Notebook(self, padding=(8, 0, 8, 8))
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.tabs = {
            "contacts": self._create_tab("Contacts"),
            "nav_history": self._create_tab("Historique Navigation"),
            "last_destinations": self._create_tab("Dernières Destinations"),
            "graphems": self._create_tab("Graphem Table")
        }
        
        status_bar = ttk.Frame(self, padding=6)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(status_bar, textvariable=self.status_var).pack(side=tk.LEFT)

    def _create_tab(self, text):
        """Crée un onglet avec un Treeview et des barres de défilement."""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=text)
        tree = ttk.Treeview(frame, show="headings")
        sb_y = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        sb_x = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)
        sb_y.pack(side=tk.RIGHT, fill=tk.Y)
        sb_x.pack(side=tk.BOTTOM, fill=tk.X)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        return tree

    def add_files(self, *args):
        paths = filedialog.askopenfilenames(title="Sélectionner les fichiers", filetypes=[("DB Files", "*.db *.sqlite *.sql"), ("All files", "*.*")])
        if not paths: return
        new_files = [p for p in paths if p not in self.selected_files]
        self.selected_files.extend(new_files)
        self._refresh_files_list()

    def clear_files(self):
        self.selected_files.clear()
        self._refresh_files_list()
        self.proc = None
        self._refresh_all_trees()

    def _refresh_files_list(self):
        self.files_list.delete(0, tk.END)
        for p in self.selected_files: self.files_list.insert(tk.END, p)

    def run_analysis(self):
        if not self.selected_files:
            messagebox.showwarning("Aucun Fichier", "Veuillez ajouter au moins un fichier à analyser.")
            return
        self.status_var.set("Traitement en cours...")
        self.update_idletasks()
        try:
            self.proc = DBProcessor(self.selected_files)
            self.proc.process()
            self._refresh_all_trees()
            self.status_var.set("Analyse terminée.")
        except Exception as e:
            self.status_var.set("Erreur durant l'analyse.")
            messagebox.showerror("Erreur", f"{e}\n\n{traceback.format_exc()}")

    def _setup_tree_columns(self, tree, columns):
        """Configure les colonnes pour un Treeview."""
        tree.configure(columns=columns)
        col_widths = {"source_file": 200, "addresses": 350, "phones": 250, "name": 250, "navDataHex": 300}
        for c in columns:
            tree.heading(c, text=c.replace("_", " ").title(), command=lambda t=tree, col=c: self._on_header_click(t, col))
            tree.column(c, width=col_widths.get(c, 120), anchor="w")

    def _refresh_all_trees(self):
        """Rafraîchit tous les Treeviews en se basant sur les données complètes."""
        if not self.proc:
            for tree in self.tabs.values():
                for item in tree.get_children(): tree.delete(item)
            return

        all_data = self.proc.processed_data
        for table_key, tree in self.tabs.items():
            for item in tree.get_children(): tree.delete(item)
            all_records_for_tab = []
            for db_path, tables in all_data.items():
                source_file_name = Path(db_path).name
                records = tables.get(table_key, [])
                for record in records:
                    all_records_for_tab.append([source_file_name] + list(record.values()))
            
            if all_records_for_tab:
                if not tree['columns']:
                    columns = ["source_file"] + list(records[0].keys())
                    self._setup_tree_columns(tree, columns)
                for values in all_records_for_tab:
                    tree.insert("", tk.END, values=values)

    def _on_header_click(self, tree, col):
        """Gère le clic sur un en-tête de colonne pour le tri."""
        tree_id = str(tree)
        current_state = self.sort_state.get(tree_id, {})
        current_order = current_state.get('order', 'asc')
        current_col = current_state.get('col')
        reverse = (col == current_col and current_order == 'asc')
        self.sort_state[tree_id] = {'col': col, 'order': 'desc' if reverse else 'asc'}
        
        col_index = tree["columns"].index(col)
        items = [(tree.item(k)["values"][col_index], k) for k in tree.get_children('')]
        
        try:
            items.sort(key=lambda item: float(item[0]), reverse=reverse)
        except (ValueError, IndexError):
            items.sort(key=lambda item: str(item[0]).lower(), reverse=reverse)

        for index, (val, k) in enumerate(items):
            tree.move(k, '', index)

    def _perform_search(self, event=None):
        """Filtre les données de l'onglet actif en fonction du terme de recherche."""
        search_term = self.search_var.get().lower().strip()
        try:
            active_tab_index = self.notebook.index(self.notebook.select())
            active_tab_key = list(self.tabs.keys())[active_tab_index]
        except tk.TclError: return
            
        tree = self.tabs[active_tab_key]
        for item in tree.get_children(): tree.delete(item)
        
        if not self.proc: return

        for db_path, data_tables in self.proc.processed_data.items():
            source_file_name = Path(db_path).name
            records = data_tables.get(active_tab_key, [])
            for record in records:
                if not search_term or any(search_term in str(val).lower() for val in record.values()):
                    tree.insert("", tk.END, values=[source_file_name] + list(record.values()))

    def _clear_search(self):
        self.search_var.set("")
        self._perform_search()

    def export_all_csvs(self):
        if not self.proc or not self.proc.processed_data:
            messagebox.showinfo("Pas de Données", "Aucune donnée à exporter. Lancez d'abord une analyse.")
            return

        output_dir = filedialog.askdirectory(title="Choisir un dossier pour sauvegarder les fichiers CSV")
        if not output_dir: return

        try:
            files_exported = 0
            for db_path, data_tables in self.proc.processed_data.items():
                db_stem = Path(db_path).stem.replace(" ", "_")
                for table_name, records in data_tables.items():
                    if not records: continue
                    output_path = Path(output_dir) / f"{db_stem}_{table_name}.csv"
                    with open(output_path, "w", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=records[0].keys())
                        writer.writeheader()
                        writer.writerows(records)
                    files_exported += 1
            messagebox.showinfo("Succès", f"{files_exported} fichier(s) CSV ont été exportés avec succès dans:\n{output_dir}")
        except Exception as e:
            messagebox.showerror("Erreur d'Exportation", f"Échec de l'exportation: {e}")

if __name__ == "__main__":
    app = App()
    app.mainloop()
