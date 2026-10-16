"""Concrete cleanup preview with optional original source selection and confirmation."""
from pathlib import Path
from .storage import cleanup_preview, execute_cleanup


def show_cleanup(parent, folder, source=None):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    window=tk.Toplevel(parent)
    window.title('Preview — LIMPAR ARQUIVOS PESADOS')
    window.geometry('780x480')
    window.transient(parent)
    include=tk.BooleanVar(value=False)
    source_path=Path(source) if source and Path(source).is_file() else None
    summary=tk.StringVar()
    source_label=tk.StringVar(value=str(source_path) if source_path else 'Fonte original: não selecionada')
    plan=None
    result=None
    ttk.Label(window,textvariable=summary,padding=12).pack(anchor='w')
    ttk.Label(window,textvariable=source_label,wraplength=740).pack(anchor='w',padx=12)
    text=tk.Text(window,height=14,wrap='word')
    text.pack(fill='both',expand=True,padx=12,pady=8)
    def refresh():
        nonlocal plan
        plan=cleanup_preview(folder,source_path,include_source=include.get())
        gb=lambda n:f'{n/1e9:.2f} GB'
        summary.set(f'Espaço atual: {gb(plan["current_bytes"])}\nPode liberar: {gb(plan["reclaimable_bytes"])}\nSerá preservado: {gb(plan["preserved_bytes"])}')
        text.configure(state='normal')
        text.delete('1.0','end')
        for row in plan['removable']:
            text.insert('end',f'{row["bytes"]/1e6:.1f} MB  {row["path"]}\n')
        text.insert('end','\nProtegidos: transcrição, JSONs, SRT, candidatos, câmera, pacotes, contact sheets, relatórios e renders finais. Arquivos em uso não são removidos.')
        text.configure(state='disabled')
        clean.configure(state='normal' if plan['removable'] else 'disabled')
    def select_source():
        nonlocal source_path
        value=filedialog.askopenfilename(parent=window,title='Fonte original opcional para limpeza',filetypes=[('Vídeo original','*.mp4 *.mkv *.webm *.mov')])
        if value:
            source_path=Path(value)
            source_label.set(value)
            refresh()
    def remove():
        nonlocal result
        if messagebox.askyesno('Confirmar limpeza',f'Remover somente os {len(plan["removable"])} arquivos listados no preview?',parent=window):
            result=execute_cleanup(plan,confirmed=True)
            messagebox.showinfo('Limpeza',f'Liberados {result["removed_bytes"]/1e9:.2f} GB. Arquivos alterados ou em uso foram preservados.',parent=window)
            window.destroy()
    controls=ttk.Frame(window)
    controls.pack(fill='x',padx=12,pady=8)
    ttk.Button(controls,text='Selecionar fonte opcional',command=select_source).pack(side='left')
    ttk.Checkbutton(controls,text='Incluir fonte original selecionada',variable=include,command=refresh).pack(side='left',padx=8)
    clean=ttk.Button(controls,text='Limpar lista',command=remove)
    clean.pack(side='right')
    ttk.Button(controls,text='Cancelar',command=window.destroy).pack(side='right',padx=8)
    refresh()
    window.wait_window()
    return result
