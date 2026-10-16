"""Preview registered scratch files while preserving originals and user outputs."""
from pathlib import Path
from .storage import cleanup_preview, execute_cleanup


def show_cleanup(parent, folder, source=None):
    import tkinter as tk
    from tkinter import ttk, messagebox
    window=tk.Toplevel(parent)
    window.title('Preview — LIMPAR ARQUIVOS PESADOS')
    window.geometry('780x480')
    window.transient(parent)
    source_path=Path(source) if source and Path(source).is_file() else None
    summary=tk.StringVar()
    source_label=tk.StringVar(value=f'Fonte original preservada: {source_path}' if source_path else 'Fontes originais são sempre preservadas.')
    plan=None
    result=None
    ttk.Label(window,textvariable=summary,padding=12).pack(anchor='w')
    ttk.Label(window,textvariable=source_label,wraplength=740).pack(anchor='w',padx=12)
    text=tk.Text(window,height=14,wrap='word')
    text.pack(fill='both',expand=True,padx=12,pady=8)
    def refresh():
        nonlocal plan
        plan=cleanup_preview(folder,source_path)
        gb=lambda n:f'{n/1e9:.2f} GB'
        summary.set(f'Espaço atual: {gb(plan["current_bytes"])}\nPode liberar: {gb(plan["reclaimable_bytes"])}\nSerá preservado: {gb(plan["preserved_bytes"])}')
        text.configure(state='normal')
        text.delete('1.0','end')
        for row in plan['removable']:
            text.insert('end',f'{row["bytes"]/1e6:.1f} MB  {row["path"]}\n')
        text.insert('end','\nProtegidos: output, .cache, source_cache, .venv, originais, projetos, revisões, aprovações, manifests, backups e evidências do Analyzer.\nSomente temporários com registro de origem e SHA256 podem ser listados para limpeza. Arquivos existentes sem comprovação são preservados.\n')
        if plan['preserved_candidates']:
            text.insert('end',f'\n{len(plan["preserved_candidates"])} possíveis temporários preservados para auditoria futura.\n')
        if plan['skipped_links']:
            text.insert('end',f'{len(plan["skipped_links"])} links/junctions preservados sem percorrer o destino.\n')
        text.configure(state='disabled')
        clean.configure(state='normal' if plan['removable'] else 'disabled')
    def remove():
        nonlocal result
        if messagebox.askyesno('Confirmar limpeza',f'Remover somente os {len(plan["removable"])} arquivos listados no preview?',parent=window):
            result=execute_cleanup(plan,confirmed=True)
            messagebox.showinfo('Limpeza',f'Liberados {result["removed_bytes"]/1e9:.2f} GB. Arquivos alterados ou em uso foram preservados.',parent=window)
            window.destroy()
    controls=ttk.Frame(window)
    controls.pack(fill='x',padx=12,pady=8)
    clean=ttk.Button(controls,text='Limpar lista',command=remove)
    clean.pack(side='right')
    ttk.Button(controls,text='Cancelar',command=window.destroy).pack(side='right',padx=8)
    refresh()
    window.wait_window()
    return result
