"""M6.4 native collection manager. Offline-first with one planning set."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import queue
from dataclasses import replace
from threading import Event
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from tkinter.scrolledtext import ScrolledText
import webbrowser

from .desktop_model import DesktopBackend,filter_cards,uncertain_state
from .presentation import TOP_CATEGORIES,LOCAL_NAMES,category_labels,original_name,replacement_name,steam_name,metadata_discrepancies
from .security import PathPolicyError,ScopedWorkshopAccess
from .settings import AppSettings
from .storage import CatalogError
from .workshop_metadata import workshop_url
from .details import DetailsWindow
from .review import replacement_review,classification_help
from .planning import ReviewSession,selected_warning_ids,review_key
from .catalog_view import row_status,row_replacement,branches,matches_branch
from .conflict_explanations import explain_overlap,NO_OVERLAPS
from .catalog_filters import filter_options,matches_filter,filter_caption
from .filter_popup import CategoryChooser


class CellTooltip:
    def __init__(self,tree,text):
        self.tree=tree;self.text=text;self.timer=None;self.popup=None
        tree.bind('<Motion>',self.schedule,add='+');tree.bind('<Leave>',self.hide,add='+');tree.bind('<ButtonPress>',self.hide,add='+')

    def hide(self,*args):
        if self.timer:self.tree.after_cancel(self.timer);self.timer=None
        if self.popup:self.popup.destroy();self.popup=None

    def schedule(self,event):
        self.hide();row=self.tree.identify_row(event.y);column=self.tree.identify_column(event.x)
        if row:
            x,y=event.x_root,event.y_root
            self.timer=self.tree.after(650,lambda:self.show(row,column,x,y))

    def show(self,row,column,x,y):
        self.timer=None
        if not self.tree.exists(row):return
        text=self.text(row,column)
        if not text:return
        self.popup=tk.Toplevel(self.tree);self.popup.overrideredirect(True)
        self.popup.geometry(f'+{min(x+12,self.tree.winfo_screenwidth()-540)}+{min(y+18,self.tree.winfo_screenheight()-220)}')
        ttk.Label(self.popup,text=text,wraplength=510,padding=10,relief='solid').pack()


class DesktopApp:
    COLUMNS=(('selection','Planning',72),('category','Type / Category',140),('original','Original Name',135),
             ('replacement','Replacement / Change',180),('steam','Steam Name',330),('link','Workshop Link',110),('status','Status',105))

    def __init__(self,root,game_root='',*,backend_factory=DesktopBackend,autoload=True,settings=None,link_opener=webbrowser.open,auto_sync=None):
        self.root=root;self.backend_factory=backend_factory;self.backend=None;self.state=None;self.settings=settings
        self.busy=False;self.closing=False;self.destroyed=False;self.details=[];self.future=None;self.link_opener=link_opener
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='l4d2-collection');self.events=queue.Queue()
        self.network_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='l4d2-public-steam')
        self.network_future=None;self.network_cancel=Event();self.auto_timer=None;self.start_sync_timer=None
        self.images={};self.sorts={};self.tooltips=[];self.warning_rows={};self.warning_page=0
        self.review_session=ReviewSession();self.active_warning_tree=None
        initial_notice='Choose your L4D2 folder to open your collection.'
        if self.settings is None and backend_factory is DesktopBackend:
            try:self.settings=AppSettings()
            except CatalogError as error:initial_notice=str(error)
        if not game_root and self.settings:
            try:game_root=self.settings.load()
            except (CatalogError,OSError) as error:initial_notice=str(error)
        options=dict(auto_online=backend_factory is DesktopBackend,online_notice_seen=False)
        if self.settings:
            try:options.update(self.settings.options())
            except (CatalogError,OSError):pass
        self.sync_allowed=(backend_factory is DesktopBackend) if auto_sync is None else auto_sync
        self.auto_online=tk.BooleanVar(value=options['auto_online'] and self.sync_allowed);self.online_notice_seen=options['online_notice_seen']
        self.path=tk.StringVar(value=game_root);self.status=tk.StringVar(value=initial_notice)
        self.search=tk.StringVar();self.category=tk.StringVar(value='All');self.review=tk.StringVar(value='All');self.index=tk.StringVar(value='All')
        self.filter_path=();self.category_chooser=None;self.filter_caption=tk.StringVar(value='Category / Target: All Mods')
        root.title('L4D2 Workshop Collection Manager')
        root.geometry(f'{min(1240,root.winfo_screenwidth()-70)}x{min(790,root.winfo_screenheight()-100)}');root.minsize(860,480)
        root.protocol('WM_DELETE_WINDOW',self.close)
        style=ttk.Style(root);style.configure('Collection.Treeview',rowheight=78);style.configure('TButton',padding=(9,5))
        outer=ttk.Frame(root,padding=14);outer.pack(fill='both',expand=True)
        heading=ttk.Frame(outer);heading.pack(fill='x',pady=(0,12))
        ttk.Label(heading,text='Your Workshop collection',font=('Segoe UI',18,'bold')).pack(side='left')
        self.browse_button=ttk.Button(heading,text='Change Game Folder',command=self.browse);self.browse_button.pack(side='right')
        self.scan_button=ttk.Button(heading,text='Refresh Mods',command=lambda:self.open_root(scan=True));self.scan_button.pack(side='right',padx=8)
        ttk.Button(heading,text='Settings',command=self.show_settings).pack(side='right')
        self.steam_button=ttk.Button(heading,text='Retry Steam Info',command=self.fetch_steam)
        self.online_status=tk.StringVar();ttk.Label(outer,textvariable=self.online_status,wraplength=1100).pack(fill='x')
        if not self.online_notice_seen:
            ttk.Label(outer,text='Public Steam info sends this collection’s numeric IDs to api.steampowered.com only; no login or downloads. Disable automatic lookups in Settings.',wraplength=1100).pack(fill='x',pady=(0,6))
        ttk.Label(outer,textvariable=self.status,wraplength=1150).pack(fill='x',pady=(0,6))
        self.progress=ttk.Progressbar(outer,mode='determinate')
        self.notebook=ttk.Notebook(outer);self.notebook.pack(fill='both',expand=True)
        self.catalog_tab=ttk.Frame(self.notebook,padding=10);self.plan_tab=ttk.Frame(self.notebook,padding=10)
        self.notebook.add(self.catalog_tab,text='All Mods');self.notebook.add(self.plan_tab,text='Planning')
        filters=ttk.Frame(self.catalog_tab);filters.pack(fill='x',pady=(0,10))
        ttk.Label(filters,text='Search').pack(side='left');self.search_entry=ttk.Entry(filters,textvariable=self.search,width=35);self.search_entry.pack(side='left',padx=(6,16),fill='x',expand=True)
        hierarchy=ttk.Frame(self.catalog_tab);hierarchy.pack(fill='x',pady=(0,6))
        self.category_button=ttk.Button(hierarchy,textvariable=self.filter_caption,command=self.show_category_chooser);self.category_button.pack(side='left',fill='x',expand=True,padx=(0,12))
        self.review_combo=self._filter(hierarchy,'Status',self.review,('All','Confirmed','Suggested','Needs Review','Stale'))
        ttk.Button(filters,text='More filters',command=self.toggle_advanced).pack(side='left',padx=(10,0))
        self.advanced=ttk.Frame(self.catalog_tab)
        self.index_combo=self._filter(self.advanced,'Local files',self.index,('All','current','pending','error','unavailable','stale'))
        self.catalog_count=tk.StringVar();self.count_label=ttk.Label(self.catalog_tab,textvariable=self.catalog_count);self.count_label.pack(anchor='w',pady=(0,5))
        self.catalog_tree=self._collection_tree(self.catalog_tab,height=4)
        actions=ttk.Frame(self.catalog_tab);actions.pack(fill='x',pady=(8,0))
        ttk.Button(actions,text='Mod Details',command=self.open_details).pack(side='left')
        ttk.Label(actions,text='Planning checkboxes save your selection. Game enabled states are unchanged.').pack(side='left',padx=12)
        self.plan_counts=tk.StringVar();ttk.Label(self.plan_tab,textvariable=self.plan_counts,wraplength=1100).pack(fill='x',pady=(0,8))
        self.plan_panes=ttk.Panedwindow(self.plan_tab,orient='vertical');self.plan_panes.pack(fill='both',expand=True)
        selected_pane=ttk.Frame(self.plan_panes);review_pane=ttk.Frame(self.plan_panes)
        self.plan_panes.add(selected_pane,weight=1);self.plan_panes.add(review_pane,weight=1)
        self.plan_tree=self._collection_tree(selected_pane,height=2,planning=True)
        controls=ttk.Frame(review_pane);controls.pack(fill='x',pady=6)
        ttk.Button(controls,text='Mod Details',command=lambda:self.open_details(from_plan=True)).pack(side='left')
        self.include_info=tk.BooleanVar(value=False)
        ttk.Checkbutton(controls,text='Advanced: metadata overlaps',variable=self.include_info,command=self.render_plan).pack(side='right')
        self.show_candidates=tk.BooleanVar(value=False);self.candidate_label=tk.StringVar(value='Other mods that overlap your set')
        self.review_tabs=ttk.Notebook(review_pane)  # legacy optional candidate inspection only
        self.findings_tab=ttk.Frame(review_pane);self.findings_tab.pack(fill='both',expand=True)
        self.path_tab=ttk.Frame(review_pane);self.candidate_tab=ttk.Frame(self.review_tabs)
        ttk.Button(controls,text='Show / hide technical paths',command=self.toggle_paths).pack(side='left',padx=12)
        self.plan_help=tk.StringVar();ttk.Label(self.findings_tab,textvariable=self.plan_help,wraplength=1050).pack(fill='x',pady=(2,6))
        columns=(('mods','Mod',300),('paths','Conflicts with',300),('kind','Reason',530))
        self.warning_tree=self._tree(self.findings_tab,columns,height=3)
        ttk.Label(self.candidate_tab,text='These other mods are not selected. Their overlaps do not make your current set conflicted.',wraplength=1000).pack(fill='x',pady=6)
        self.candidate_tree=self._tree(self.candidate_tab,columns,height=3);self.candidate_tree.heading('mods',text='Mod outside your set → selected mod')
        for tree in (self.warning_tree,self.candidate_tree):
            tree.bind('<<TreeviewSelect>>',lambda event,tree=tree:self.show_warning(tree=tree))
            tree.bind('<Double-1>',lambda event:self.toggle_paths(show=True))
            tree.bind('<Return>',lambda event:self.toggle_paths(show=True))
        self.tooltips.append(CellTooltip(self.warning_tree,lambda row,column:self.warning_tree.set(row,self.warning_tree.column(column,'id'))))
        pager=ttk.Frame(self.path_tab);pager.pack(fill='x',pady=4)
        ttk.Button(pager,text='Previous paths',command=lambda:self.show_warning(-1)).pack(side='left')
        ttk.Button(pager,text='Next paths',command=lambda:self.show_warning(1)).pack(side='left',padx=6)
        self.mark_reviewed_button=ttk.Button(pager,text='Mark reviewed this session',command=self.mark_reviewed,state='disabled');self.mark_reviewed_button.pack(side='right')
        self.warning_text=ScrolledText(self.path_tab,height=4,wrap='word');self.warning_text.pack(fill='both',expand=True);self.warning_text.configure(state='disabled')
        self.placeholder=tk.PhotoImage(master=root,width=64,height=48);self.placeholder.put('#e7e9ec',to=(0,0,64,48));self.placeholder.put('#b7c1cc',to=(20,14,44,34))
        for variable in (self.search,self.review,self.index):variable.trace_add('write',lambda *args:self.render_catalog())
        self.category.trace_add('write',lambda *args:self.select_filter(() if self.category.get()=='All' else (LOCAL_NAMES.get(self.category.get(),self.category.get()),)))
        root.bind('<Control-f>',lambda event:self.search_entry.focus_set())
        self.timer=root.after(40,self._drain)
        if autoload:root.after(100,self.open_root if game_root else self.browse)

    def _filter(self,parent,label,variable,values):
        ttk.Label(parent,text=label).pack(side='left',padx=(8,5))
        combo=ttk.Combobox(parent,textvariable=variable,values=values,state='readonly',width=19);combo.pack(side='left');return combo

    def show_category_chooser(self):
        if not self.state:return
        if self.category_chooser and self.category_chooser.window.winfo_exists():self.category_chooser.window.lift();return
        self.category_chooser=CategoryChooser(self.root,filter_options(self.state.cards,self.state.metadata,self.state.targets),self.filter_path,self.select_filter)

    def select_filter(self,path):
        self.filter_path=tuple(path);self.filter_caption.set('Category / Target: '+filter_caption(self.filter_path));self.render_catalog()

    def toggle_advanced(self):
        if self.advanced.winfo_manager():self.advanced.pack_forget()
        else:self.advanced.pack(fill='x',before=self.count_label,pady=(0,8))

    def _tree(self,parent,columns,height=10,show='headings'):
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=True)
        tree=ttk.Treeview(frame,columns=tuple(column[0] for column in columns),show=show,height=height,selectmode='browse')
        for key,label,width in columns:tree.heading(key,text=label);tree.column(key,width=width,minwidth=65,stretch=True)
        vertical=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);horizontal=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview)
        tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        tree.grid(row=0,column=0,sticky='nsew');vertical.grid(row=0,column=1,sticky='ns');horizontal.grid(row=1,column=0,sticky='ew')
        frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        return tree

    def _collection_tree(self,parent,height=10,*,planning=False):
        columns=self.COLUMNS+((('warning','Within your set',180),) if planning else ())
        tree=self._tree(parent,columns,height=height,show='tree headings');tree.configure(style='Collection.Treeview')
        if planning:
            tree.configure(displaycolumns=('selection','warning','original','replacement','steam','status'))
            # Only current selected-selected resource overlaps receive this tag.
            # Review acknowledgement keeps the overlap; metadata/stale rows stay normal.
            tree.tag_configure('attention',background='#fde2e2',foreground='#8b1a1a')
        else:tree.configure(displaycolumns=('selection','status','category','original','replacement','steam','link'))
        tree.heading('#0',text='Preview');tree.column('#0',width=128,minwidth=128,stretch=False)
        tree.column('selection',anchor='center',stretch=False)
        for key,label,_ in columns:tree.heading(key,text=label,command=lambda key=key:self.sort_by(tree,key))
        tree.bind('<Button-1>',lambda event:self.cell_click(event,tree));tree.bind('<space>',lambda event:self.keyboard_toggle(tree))
        tree.bind('<Return>',lambda event:self.open_details(from_plan=tree is self.plan_tree))
        tree.bind('<Double-1>',lambda event:self.double_click(event,tree))
        self.tooltips.append(CellTooltip(tree,lambda row,column:self.cell_text(tree,row,column)))
        return tree

    def sort_by(self,tree,key):
        reverse=self.sorts.get((str(tree),key),False)
        for position,item in enumerate(sorted(tree.get_children(),key=lambda item:tree.set(item,key).casefold(),reverse=reverse)):tree.move(item,'',position)
        self.sorts[(str(tree),key)]=not reverse

    def cell_text(self,tree,row,column):
        if not self.state:return ''
        card=next((card for card in self.state.cards if card.package_id==row),None)
        if not card:return ''
        metadata=self.state.metadata.get(card.workshop_id,{})
        if column=='#0':return card.display_name
        key=tree.column(column,'id');value=tree.set(row,key)
        if key=='steam':return f"{value}\n{'Official Steam title' if metadata.get('title') else 'No verified Steam title; readable fallback'}\nRetrieval: {metadata.get('retrieval_status','not fetched')} · {card.review_status}"+'\n'+'\n'.join(metadata_discrepancies(card,metadata,self.state.targets))
        if key=='category':return f"{value}\nSteam tags: {', '.join(metadata.get('tags',())) or 'Not fetched'}\nLocal evidence: {', '.join(card.categories)}\nUser category correction: {'yes' if card.user_edit and card.user_edit['category_mode']=='replace' else 'no'}"
        if key=='replacement':
            review=replacement_review(card,metadata)
            return review.text+'\n'+review.freshness+'\n'+review.explanation+'\n'+classification_help(card)
        if key=='status':return row_status(card,metadata)+'\n'+replacement_review(card,metadata).explanation+'\nFile state: '+card.presence_status+' / '+card.index_status+'\nConfirmation does not establish gameplay compatibility.'
        if key=='original':return str(value)+'\n'+card.summary
        if key=='warning':return str(value)+'\nOnly overlaps between currently selected mods flag this list. Other mods are shown separately. A path match is not proof of incompatibility.'
        return str(value)

    def cell_click(self,event,tree):
        row=tree.identify_row(event.y);column=tree.identify_column(event.x)
        if not row or tree.identify_region(event.x,event.y)!='cell':return
        tree.selection_set(row);tree.focus(row)
        key=tree.column(column,'id')
        if key=='selection':self._toggle(tree);return 'break'
        if key=='link':self.open_link(row);return 'break'

    def double_click(self,event,tree):
        column=tree.identify_column(event.x)
        if column=='#0' or (column and tree.column(column,'id') not in ('selection','link')):self.open_details(from_plan=tree is self.plan_tree)
        return 'break'

    def keyboard_toggle(self,tree):self._toggle(tree);return 'break'

    def open_link(self,package_id):
        if not self.state:return
        card=next((card for card in self.state.cards if card.package_id==package_id),None)
        url=workshop_url(card.workshop_id) if card else None
        if url:self.link_opener(url)

    def _allow_navigation(self):return all(window.allow_close() for window in self.details if window.window.winfo_exists())

    def browse(self):
        if self.busy or not self._allow_navigation():return
        chosen=filedialog.askdirectory(parent=self.root,title='Choose Left 4 Dead 2 (the game folder)',mustexist=True)
        if chosen:self.path.set(chosen);self.open_root(navigation_confirmed=True)

    def open_root(self,scan=False,*,navigation_confirmed=False):
        if self.busy:return
        if not self.path.get().strip():self.status.set('Choose your L4D2 game folder.');return
        changed=self.backend is not None and self.backend.root!=self.path.get()
        if changed and not navigation_confirmed and not self._allow_navigation():return
        if changed:
            self.network_cancel.set()
            for window in self.details:
                if window.window.winfo_exists():window.window.destroy()
            self.details=[];self.state=None
            for tree in (self.catalog_tree,self.plan_tree,self.warning_tree):tree.delete(*tree.get_children())
        if self.backend is None or changed:self.backend=self.backend_factory(self.path.get())
        self.submit(scan=scan)

    def fetch_steam(self):
        if self.state:self.start_metadata_sync(manual=True)
        else:self.status.set('Open your local collection before fetching Steam information.')

    def show_settings(self):
        window=tk.Toplevel(self.root);window.title('Collection settings')
        ttk.Label(window,text='Public Steam info sends only validated IDs from this local collection to api.steampowered.com.\nNo login, subscription access or VPK downloads. Cached information works offline.',padding=16).pack()
        ttk.Checkbutton(window,text='Automatically update missing / expired public Steam information',variable=self.auto_online,command=self.save_online_setting).pack(padx=16,pady=10,anchor='w')
        ttk.Button(window,text='Retry Steam Info (respects cache / retry delay)',command=self.fetch_steam).pack(pady=10)
        ttk.Button(window,text='Close',command=window.destroy).pack(pady=10)

    def save_online_setting(self):
        if not self.auto_online.get():self.network_cancel.set()
        if self.settings and self.backend:
            try:self.settings.save(ScopedWorkshopAccess(self.backend.root),auto_online=self.auto_online.get(),online_notice_seen=True)
            except (CatalogError,OSError,ValueError):self.online_status.set('Online setting could not be saved; retry when the game folder is accessible.')
        if self.auto_online.get():self.start_metadata_sync()

    def start_metadata_sync(self,manual=False):
        if self.destroyed or self.closing or not self.state or not self.backend or (not manual and not self.auto_online.get()):return
        if self.network_future and not self.network_future.done():return
        if not hasattr(self.backend,'sync_metadata'):return
        self.network_cancel=Event();cancel=self.network_cancel;backend=self.backend
        self.online_status.set('Updating Workshop information in the background… Cached information and editing remain available.')
        self.network_future=self.network_executor.submit(backend.sync_metadata,cancelled=cancel.is_set)
        self.network_future.add_done_callback(lambda future:self.events.put(('metadata',future,backend)))

    def metadata_tick(self):
        self.auto_timer=None;self.start_metadata_sync()
        if not self.destroyed:self.auto_timer=self.root.after(900000,self.metadata_tick)

    def toggle_paths(self,show=False):
        if self.path_tab.winfo_manager() and not show:
            self.path_tab.pack_forget();self.findings_tab.pack(fill='both',expand=True)
        else:
            self.findings_tab.pack_forget();self.path_tab.pack(fill='both',expand=True)

    def submit(self,*,scan=False,action=None,callback=None,on_error=None):
        if self.busy:self.status.set('A task is running. Your unsaved edits are kept; try again when it finishes.');return False
        if self.backend is None:return False
        self.busy=True;self.progress.pack(fill='x',pady=(0,8),before=self.notebook);self.progress.configure(mode='indeterminate');self.progress.start(20)
        for button in (self.scan_button,self.browse_button,self.steam_button):button.configure(state='disabled')
        self.status.set('Checking your collection…');backend=self.backend
        def work():
            try:return backend.load(scan=scan,action=action,progress=lambda text:self.events.put(('progress',text)))
            except CatalogError as error:
                if not scan and action is None and 'No saved catalog' in str(error):return backend.load(scan=True,progress=lambda text:self.events.put(('progress',text)))
                raise
        self.future=self.executor.submit(work);self.future.add_done_callback(lambda future:self.events.put(('done',future,callback,on_error)));return True

    def _drain(self):
        try:
            while True:
                event=self.events.get_nowait()
                if event[0]=='metadata':
                    _,future,backend=event
                    if backend is not self.backend:continue
                    try:
                        metadata,counts=future.result()
                        if self.state:
                            self.state=replace(self.state,metadata=metadata);self.render_catalog();self.render_plan()
                            for window in self.details:
                                if window.window.winfo_exists():window.refresh(next(c for c in self.state.cards if c.package_id==window.card.package_id))
                        self.online_status.set(f"Workshop info: {counts['ok']} updated, {counts['cached']} cached, {counts['failed']} unavailable. Saved names are kept.")
                    except Exception:self.online_status.set('Steam information could not be updated. Cached information and your corrections are kept; retry later in Settings.')
                    continue
                if event[0]=='progress':self.status.set(event[1]);continue
                _,future,callback,on_error=event;self.busy=False;self.progress.stop();self.progress.configure(mode='determinate',value=0);self.progress.pack_forget()
                for button in (self.scan_button,self.browse_button,self.steam_button):button.configure(state='normal')
                try:
                    self.state=future.result();self._render_state()
                    if self.settings:
                        try:self.settings.save(ScopedWorkshopAccess(self.backend.root))
                        except (OSError,CatalogError,ValueError):self.status.set(self.status.get()+' Folder preference could not be saved; choose it again next launch.')
                    for window in self.details:
                        if window.window.winfo_exists():
                            card=next((card for card in self.state.cards if card.package_id==window.card.package_id),None)
                            if card:window.refresh(card)
                            else:window.notice.set('This mod is no longer present. Your draft is kept; saving is unavailable.')
                    if callback:callback(self.state)
                    if not self.online_notice_seen:
                        self.online_status.set('Public Steam info uses this collection’s numeric IDs only; no login or downloads. Disable automatic lookups in Settings.')
                        self.online_notice_seen=True
                        if self.settings:self.settings.save(ScopedWorkshopAccess(self.backend.root),online_notice_seen=True)
                    if self.auto_timer is None:self.auto_timer=self.root.after(900000,self.metadata_tick)
                    if self.auto_online.get() and self.start_sync_timer is None:
                        def scheduled_sync():
                            self.start_sync_timer=None;self.start_metadata_sync()
                        self.start_sync_timer=self.root.after(1500,scheduled_sync)
                except Exception as error:
                    message=str(error) if isinstance(error,(CatalogError,ValueError)) else 'The collection could not be updated. Saved information is kept; please retry.'
                    if self.state and (not isinstance(error,ValueError) or isinstance(error,PathPolicyError)):
                        self.state=uncertain_state(self.state);self._render_state();message+=' Last-known information is shown; some files need checking.'
                    if not self.state:message+=' Use Change Game Folder if the installation moved or is unavailable.'
                    self.status.set(message)
                    if self.state:
                        for window in self.details:
                            if window.window.winfo_exists():
                                card=next((card for card in self.state.cards if card.package_id==window.card.package_id),None)
                                if card:window.refresh(card)
                                window.notice.set(message)
                    if on_error:on_error(message)
                if self.closing:
                    self.closing=False;self.close()
                    if self.destroyed:return
        except queue.Empty:pass
        self.timer=self.root.after(40,self._drain)

    def _render_state(self):
        self.images={}
        for package_id,data in self.state.previews.items():
            if data:
                try:self.images[package_id]=tk.PhotoImage(master=self.root,data=data,format='PPM')
                except tk.TclError:pass
        self.status.set(f"{len(self.state.cards)} local mods · Last checked {self.state.checked_at[11:19]} UTC"+('' if self.state.overlaps.coverage.complete else ' · Some files need checking — Refresh Mods')+((' · '+self.state.operation_notice) if self.state.operation_notice else ''))
        self.render_catalog();self.render_plan()

    def values(self,card):
        metadata=self.state.metadata.get(card.workshop_id,{})
        return ('☑' if card.package_id in self.state.planning.selected_ids else '☐',', '.join(category_labels(card,metadata)),original_name(card),row_replacement(card,metadata),steam_name(card,metadata),'Open Workshop' if workshop_url(card.workshop_id) else 'Unavailable',row_status(card,metadata))

    def render_catalog(self):
        if not self.state:return
        # A temporarily empty filter stays selected so refresh never broadens it silently.
        previous=self.catalog_tree.selection();self.catalog_tree.delete(*self.catalog_tree.get_children());needle=self.search.get().casefold().strip();cards=[]
        for card in filter_cards(self.state.cards,index=self.index.get()):
            metadata=self.state.metadata.get(card.workshop_id,{})
            if self.review.get()!='All' and row_status(card,metadata)!=self.review.get():continue
            if not matches_filter(card,metadata,self.state.targets,self.filter_path):continue
            haystack=' '.join((card.display_name,card.summary,card.description,card.filename,card.workshop_id or '',metadata.get('title') or '',*metadata.get('tags',()))).casefold()
            if needle and needle not in haystack:continue
            cards.append(card);self.catalog_tree.insert('','end',iid=card.package_id,image=self.images.get(card.package_id,self.placeholder),values=self.values(card))
        self.catalog_count.set(f'{len(cards)} of {len(self.state.cards)} mods · Space toggles Planning; Enter opens details')
        if previous and self.catalog_tree.exists(previous[0]):self.catalog_tree.selection_set(previous[0])

    def render_plan(self):
        if not self.state:return
        report=self.state.planning;selected=report.selected_ids;counts=report.counts;self.review_session.reconcile(report)
        reviewed=sum(finding.context=='selected' and finding.presentation=='attention' and self.review_session.reviewed(finding) for finding in report.findings)
        self.plan_counts.set(f"{len(selected)} selected · {counts['selected_attention']} pairs share resources within your set · {reviewed} reviewed this session · {counts['selected_retained']} pairs need fresh evidence"+
            ('' if report.coverage_complete else ' · Some selected files need checking; no all-clear is implied.' if report.uncertain_selected_ids else ' · Overall collection coverage is incomplete.'))
        self.candidate_label.set(f"Other mods that overlap your set ({counts['candidate_attention']} resource pairs)")
        self.plan_help.set('Your set is empty. Choose mods using the Planning checkboxes in All Mods.' if not selected else
            'Review the selected pairs below. Shared paths alone do not prove incompatibility.' if counts['selected_attention'] else
            NO_OVERLAPS if report.coverage_complete else 'Coverage is incomplete. Inspect diagnostics before drawing conclusions.')
        previous=self.plan_tree.selection();self.plan_tree.delete(*self.plan_tree.get_children())
        for tree in (self.warning_tree,self.candidate_tree):tree.delete(*tree.get_children())
        self.warning_rows={};self.active_warning_tree=None;self.mark_reviewed_button.configure(state='disabled')
        attention=selected_warning_ids(report)
        pending={package.package_id for finding in report.findings if finding.context=='selected' and finding.presentation=='attention' and not self.review_session.reviewed(finding) for package in (finding.pair.package_a,finding.pair.package_b)}
        retained={package.package_id for finding in report.findings if finding.context=='selected' and finding.presentation=='retained' for package in (finding.pair.package_a,finding.pair.package_b)}
        names={card.package_id:steam_name(card,self.state.metadata.get(card.workshop_id)) for card in self.state.cards}
        for number,finding in enumerate(self.state.planning.findings):
            pair=finding.pair;ids={pair.package_a.package_id,pair.package_b.package_id}
            if finding.presentation=='informational' and not self.include_info.get():continue
            key=finding.context+':'+str(number);self.warning_rows[key]=finding
            tree=self.warning_tree if finding.context=='selected' else self.candidate_tree
            ordered=(pair.package_a,pair.package_b) if finding.context=='selected' else sorted((pair.package_a,pair.package_b),key=lambda package:package.package_id in selected)
            explanation=explain_overlap(finding)
            reason=explanation.reason+(' Reviewed this session; overlap retained.' if self.review_session.reviewed(finding) else '')
            tree.insert('','end',iid=key,values=(names[ordered[0].package_id],names[ordered[1].package_id],reason))
        for card in self.state.cards:
            if card.package_id not in selected:continue
            tag='attention' if card.package_id in attention else 'retained' if card.package_id in retained else ''
            warning='Review shared paths' if card.package_id in pending else 'Reviewed shared paths' if tag=='attention' else 'Refresh stale evidence' if tag or card.package_id in report.uncertain_selected_ids else 'No selected-pair flag'
            self.plan_tree.insert('','end',iid=card.package_id,tags=(tag,) if tag else (),image=self.images.get(card.package_id,self.placeholder),values=(*self.values(card),warning))
        if previous and self.plan_tree.exists(previous[0]):self.plan_tree.selection_set(previous[0])
        self._set_text(self.warning_text,'Select a pair, then expand technical paths for optional evidence. '
            'A shared material or shader can affect different original targets; equality alone does not establish a gameplay problem. '
            'Review marks last only this session and are cleared when relevant evidence changes.')

    def toggle_candidates(self):
        present=str(self.candidate_tab) in self.review_tabs.tabs()
        if self.show_candidates.get() and not present:self.review_tabs.add(self.candidate_tab,text='Other mods (optional)')
        elif not self.show_candidates.get() and present:
            self.review_tabs.forget(self.candidate_tab);self.review_tabs.select(self.findings_tab)
        self.render_plan()

    @staticmethod
    def _set_text(widget,text):widget.configure(state='normal');widget.delete('1.0','end');widget.insert('1.0',text);widget.configure(state='disabled')

    def show_warning(self,delta=None,*,tree=None):
        tree=tree or self.active_warning_tree or self.warning_tree
        selected=tree.selection()
        if not selected or selected[0] not in self.warning_rows:return
        self.active_warning_tree=tree
        finding=self.warning_rows[selected[0]];pair=finding.pair
        explanation=explain_overlap(finding)
        self.warning_page=0 if delta is None else max(0,min(self.warning_page+delta,max(0,(len(pair.canonical_paths)-1)//50)))
        can_review=review_key(finding) is not None
        self.mark_reviewed_button.configure(state='normal' if can_review else 'disabled',text='Reopen review' if self.review_session.reviewed(finding) else 'Mark reviewed this session')
        text=('Both mods are selected.' if finding.context=='selected' else 'One mod is outside your set. This pair does not flag your selected list.')
        text+=' A shared path confirms resource overlap, not gameplay incompatibility. Different survivor/weapon targets can still share material or shader paths.\n'
        text+=('Reviewed this session; evidence and counts remain unchanged.\n' if self.review_session.reviewed(finding) else '')
        text+=('Evidence is retained/outdated. Refresh before acknowledging it.\n' if pair.evidence_freshness!='current' else '')
        text+=f'{pair.package_a.filename} ↔ {pair.package_b.filename}\nPage {self.warning_page+1}/{max(1,(len(pair.canonical_paths)+49)//50)}; {pair.overlapping_path_count} raw shared paths.\n'
        text+=explanation.category+': '+explanation.reason+'\nCrash evidence: '+explanation.crash_evidence+'\n'+explanation.limits+'\n'
        for path in pair.canonical_paths[self.warning_page*50:(self.warning_page+1)*50]:text+=f"\n{'Informational metadata' if path in finding.informational_paths else 'Resource evidence'}: {path.decode('utf8','backslashreplace')}\nHex: {path.hex()}\n"
        self._set_text(self.warning_text,text)

    def mark_reviewed(self):
        if self.busy:return
        tree=self.active_warning_tree or self.warning_tree;selection=tree.selection()
        if not selection:return
        finding=self.warning_rows.get(selection[0])
        if not finding or review_key(finding) is None:return
        self.review_session.toggle(finding);self.render_plan()
        if tree.exists(selection[0]):tree.selection_set(selection[0]);self.show_warning(tree=tree)

    def _toggle(self,tree):
        if not self.state or not tree.selection():return
        package_id=tree.selection()[0];self.submit(action=('selection',dict(package_id=package_id,selected=package_id not in self.state.planning.selected_ids)))

    def toggle_catalog(self):self._toggle(self.catalog_tree)
    def toggle_plan(self):self._toggle(self.plan_tree)

    def open_details(self,from_plan=False):
        if not self.state:return
        selected=(self.plan_tree if from_plan else self.catalog_tree).selection()
        if not selected:return
        for window in self.details:
            if window.window.winfo_exists() and window.card.package_id==selected[0]:window.window.lift();return
        card=next((card for card in self.state.cards if card.package_id==selected[0]),None)
        if card:self.details.append(DetailsWindow(self,card))

    def close(self):
        if self.busy:self.closing=True;self.status.set('Finishing the current safe operation before closing…');return
        if not self._allow_navigation():return
        self._destroy()

    def _destroy(self):
        self.destroyed=True
        self.network_cancel.set()
        if self.auto_timer:self.root.after_cancel(self.auto_timer)
        if self.start_sync_timer:self.root.after_cancel(self.start_sync_timer)
        self.network_executor.shutdown(wait=False,cancel_futures=True)
        for tooltip in self.tooltips:tooltip.hide()
        self.root.after_cancel(self.timer);self.executor.shutdown(wait=False,cancel_futures=True);self.root.destroy()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--game-root',help='Explicit root; otherwise reopen the saved folder')
    parser.add_argument('--qa-smoke',metavar='SYNTHETIC_ROOT',help=argparse.SUPPRESS)
    parser.add_argument('--qa-unavailable',metavar='MISSING_SYNTHETIC_ROOT',help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    if args.qa_smoke or args.qa_unavailable:
        from .portable_qa import run
        return run(args.qa_smoke or args.qa_unavailable,unavailable=bool(args.qa_unavailable))
    root=tk.Tk();DesktopApp(root,args.game_root or '');root.mainloop();return 0


if __name__=='__main__':raise SystemExit(main())
