# JobRobo.py
import tkinter as tk
import os
from tkinter import ttk, messagebox
from modules.ai.resume_optimizer import run_resume_optimization
from modules.config_loader import save_runtime_config, load_runtime_config
from modules.ai.openai_key_loader import load_openai_key

class LinkedInApp:
    def __init__(self, root):
        self.root = root
        self.root.title("LinkedIn Bot Dashboard")
        self.root.geometry("600x500")

        self.notebook = ttk.Notebook(self.root)

        self.bot_tab = ttk.Frame(self.notebook)
        self.optimizer_tab = ttk.Frame(self.notebook)

        self.notebook.add(self.bot_tab, text="Run LinkedIn Bot")
        self.notebook.add(self.optimizer_tab, text="Resume Optimizer")

        self.notebook.pack(expand=1, fill="both")

        self.init_bot_tab()
        self.init_optimizer_tab()

    def init_bot_tab(self):
        label = tk.Label(self.bot_tab, text="Click to start LinkedIn automation")
        label.pack(pady=20)

        button = tk.Button(self.bot_tab, text="Run Bot", command=self.run_bot_from_ui)
        button.pack(pady=10)

    def run_bot_from_ui(self):
        try:
            # Importing the bot initializes Chrome. Delay until the user starts it.
            from runAiBot import run_bot
            run_bot()
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {str(e)}")

    def init_optimizer_tab(self):
        config = load_runtime_config()

        self.fields = {}
        field_config = {
            "first_name": "First Name",
            "last_name": "Last Name",
            "resume_path": "Resume Path",
            "job_id": "Job ID",
            "job_title": "Job Title",
            "job_description": "Job Description"
        }

        for i, (key, label_text) in enumerate(field_config.items()):
            label = tk.Label(self.optimizer_tab, text=label_text)
            label.grid(row=i, column=0, sticky="e", pady=5, padx=10)
            entry = tk.Entry(self.optimizer_tab, width=60)
            entry.insert(0, config.get(key, ""))
            entry.grid(row=i, column=1, pady=5)
            self.fields[key] = entry

        self.replace_job_title_var = tk.BooleanVar(value=config.get("replace_job_title", True))
        self.rewrite_bullets_var = tk.BooleanVar(value=config.get("rewrite_bullets", True))

        mode_row = len(field_config)
        tk.Label(self.optimizer_tab, text="Optimization Mode").grid(row=mode_row, column=0, sticky="e", pady=5, padx=10)
        self.optimization_mode_var = tk.StringVar(value=config.get("optimization_mode", "full"))
        mode_selector = ttk.Combobox(
            self.optimizer_tab,
            textvariable=self.optimization_mode_var,
            values=("skills", "bullets", "full"),
            state="readonly",
            width=57,
        )
        mode_selector.grid(row=mode_row, column=1, pady=5)

        tk.Checkbutton(self.optimizer_tab, text="Replace Job Title (legacy)", variable=self.replace_job_title_var).grid(row=mode_row+1, column=1, sticky="w")
        tk.Checkbutton(self.optimizer_tab, text="Rewrite Resume Bullets (legacy)", variable=self.rewrite_bullets_var).grid(row=mode_row+2, column=1, sticky="w")

        run_button = tk.Button(self.optimizer_tab, text="Run Resume Optimizer", command=self.run_resume_optimizer_from_ui)
        run_button.grid(row=mode_row+4, column=1, pady=20)

    def run_resume_optimizer_from_ui(self):
        try:
            # Save form values only; the loader merges the latest bank rules and
            # settings under its file lock, preserving edits from other sessions.
            new_config = {key: field.get() for key, field in self.fields.items()}
            new_config["replace_job_title"] = self.replace_job_title_var.get()
            new_config["rewrite_bullets"] = self.rewrite_bullets_var.get()
            new_config["optimization_mode"] = self.optimization_mode_var.get()

            save_runtime_config(new_config)

            # Re-load to ensure consistent values
            config = load_runtime_config()

            if not os.getenv("OPENAI_API_KEY"):
                load_openai_key()

            optimized_pdf = run_resume_optimization(
                config["job_description"],
                config["resume_path"],
                config["job_id"],
                config["job_title"],
                config["first_name"],
                config["last_name"],
                config.get("optimization_mode", "full")
            )

            if not optimized_pdf:
                messagebox.showerror(
                    "Optimization Failed",
                    "Resume optimization did not produce a verified PDF. Check the logs for details."
                )
                return
            messagebox.showinfo("Success", "Resume optimization completed successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {str(e)}")

if __name__ == "__main__":
    root = tk.Tk()
    app = LinkedInApp(root)
    root.mainloop()
