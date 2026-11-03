"""Single keyboard-accessible Category / Target tree picker."""
import tkinter as tk
from tkinter import ttk
from .catalog_filters import filter_caption,path_sort_key


class CategoryChooser:
    def __init__(self,parent,options,selected,on_select):
        self.window=tk.Toplevel(parent);self.window.title('Category / Target');self.window.transient(parent)
        self.window.geometry(f'500x{min(580,parent.winfo_screenheight()-100)}');self.window.minsize(360,330)
        self.options=options;self.on_select=on_select;self.paths={};self.nodes={}
        frame=ttk.Frame(self.window,padding=12);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Choose a category for all related mods, or expand it for a target.',wraplength=450).pack(fill='x',pady=(0,8))
        holder=ttk.Frame(frame);holder.pack(fill='both',expand=True)
        self.tree=ttk.Treeview(holder,show='tree',selectmode='browse',height=16)
        scroll=ttk.Scrollbar(holder,orient='vertical',command=self.tree.yview);self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
        def insert(path,parent_id=''):
            node=self.tree.insert(parent_id,'end',text=path[-1] if path else 'All Mods',open=not path or selected[:len(path)]==path)
            self.paths[node]=path;self.nodes[path]=node
            children=sorted((p for p in options if len(p)==len(path)+1 and p[:-1]==path),key=path_sort_key)
            if children and path:
                all_node=self.tree.insert(node,'end',text='All '+path[-1]);self.paths[all_node]=path
            for child in children:insert(child,node)
        insert(())
        self.provenance=tk.StringVar();ttk.Label(frame,textvariable=self.provenance,wraplength=460).pack(fill='x',pady=8)
        buttons=ttk.Frame(frame);buttons.pack(fill='x')
        self.cancel_button=ttk.Button(buttons,text='Cancel',command=self.window.destroy);self.cancel_button.pack(side='left')
        self.apply_button=ttk.Button(buttons,text='Use filter',command=self.apply);self.apply_button.pack(side='right')
        self.tree.bind('<<TreeviewSelect>>',lambda event:self.describe())
        self.tree.bind('<Return>',lambda event:self.apply());self.tree.bind('<Double-1>',self.double_click)
        self.window.bind('<Escape>',lambda event:self.window.destroy())
        node=self.nodes.get(selected,self.nodes[()]);self.tree.selection_set(node);self.tree.focus(node);self.tree.see(node);self.tree.focus_set();self.describe()

    def describe(self):
        selection=self.tree.selection();path=self.paths.get(selection[0],()) if selection else ()
        self.provenance.set(filter_caption(path)+'\nMatches: '+', '.join(self.options.get(path,()))+'. Tags and detected/user targets remain separate evidence in Mod Details.')

    def double_click(self,event):
        # Let the normal tree expander work without accidentally applying a filter.
        if self.tree.identify('element',event.x,event.y) not in ('Treeitem.indicator','indicator'):self.apply()

    def apply(self):
        selection=self.tree.selection()
        if selection:self.on_select(self.paths[selection[0]]);self.window.destroy()
