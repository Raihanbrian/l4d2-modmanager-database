"""Replacement-first editor and one atomic Save with per-effect draft preservation."""

import copy
import tkinter as tk
from tkinter import ttk,messagebox
from tkinter.scrolledtext import ScrolledText
from .presentation import LOCAL_NAMES,category_labels,steam_name,metadata_discrepancies,original_name,replacement_name
from .workshop_metadata import workshop_url,readable_description
from .suggestions import suggest_replacement
from .review import replacement_review,classification_help


class DetailsWindow:
    TARGET_MODES={'Use evidence':'inherit','Assign selected targets':'replace','Unknown':'unknown'}
    REPLACEMENT_MODES={'Use evidence':'inherit','Named replacement':'value','Unknown':'unknown'}

    def __init__(self,app,card):
        self.app=app;self.card=card;self.effect_drafts={};self.effect_baselines={};self.loaded_effect_id=None;self.loading=False
        self.window=tk.Toplevel(app.root);self.window.title('Mod Details')
        self.window.geometry(f'{min(930,self.window.winfo_screenwidth()-70)}x{min(670,self.window.winfo_screenheight()-100)}');self.window.minsize(700,460)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        frame=ttk.Frame(self.window,padding=16);frame.pack(fill='both',expand=True)
        header=ttk.Frame(frame);header.pack(fill='x',pady=(0,10))
        self.thumbnail=ttk.Label(header,image=app.images.get(card.package_id,app.placeholder));self.thumbnail.pack(side='left',padx=(0,14))
        self.title=ttk.Label(header,text=card.display_name,font=('Segoe UI',16,'bold'),wraplength=700);self.title.pack(side='left')
        header.bind('<Configure>',lambda event:self.title.configure(wraplength=max(350,event.width-145)))
        self.tabs=ttk.Notebook(frame);self.tabs.pack(fill='both',expand=True)
        self.overview=ttk.Frame(self.tabs,padding=12);self.edit_host=ttk.Frame(self.tabs);self.evidence_tab=ttk.Frame(self.tabs,padding=10)
        self.tabs.add(self.edit_host,text='Mod information')
        self.summary=ttk.Label(self.overview,wraplength=810,font=('Segoe UI',12));self.summary.pack(fill='x',pady=8)
        self.overview.bind('<Configure>',lambda event:self.summary.configure(wraplength=max(350,event.width-24)))
        self.info=tk.StringVar();self.info_text=ScrolledText(self.overview,wrap='word',height=10,font=('Segoe UI',10));self.info_text.pack(fill='both',expand=True,pady=8)
        controls=ttk.Frame(self.overview);controls.pack(fill='x',pady=10)
        ttk.Button(controls,text='Edit Info',command=lambda:self.tabs.select(self.edit_host)).pack(side='left')
        self.link_button=ttk.Button(controls,text='Open Workshop',command=lambda:app.open_link(self.card.package_id));self.link_button.pack(side='left',padx=8)
        ttk.Button(controls,text='Technical Details',command=self.show_technical).pack(side='left')
        self.edit_canvas=tk.Canvas(self.edit_host,highlightthickness=0);scroll=ttk.Scrollbar(self.edit_host,orient='vertical',command=self.edit_canvas.yview)
        self.edit_canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');self.edit_canvas.pack(side='left',fill='both',expand=True)
        self.edit_tab=ttk.Frame(self.edit_canvas,padding=12);item=self.edit_canvas.create_window((0,0),window=self.edit_tab,anchor='nw')
        self.edit_tab.bind('<Configure>',lambda event:self.edit_canvas.configure(scrollregion=self.edit_canvas.bbox('all')))
        self.edit_canvas.bind('<Configure>',lambda event:self.edit_canvas.itemconfigure(item,width=event.width))
        self.edit_canvas.bind('<MouseWheel>',lambda event:self.edit_canvas.yview_scroll(-int(event.delta/120),'units'))
        self.name=tk.StringVar();self.category_mode=tk.StringVar(value='Use evidence')
        self.primary=ttk.LabelFrame(self.edit_tab,text='Original L4D2 Target → Replacement / Change',padding=10);self.primary.pack(fill='x',pady=(0,8))
        self.more_options=ttk.Frame(self.edit_tab,padding=8)
        top=ttk.Frame(self.more_options);top.pack(fill='x')
        ttk.Label(top,text='Custom catalog name (optional)').grid(row=0,column=0,sticky='w')
        self.name_entry=ttk.Entry(top,textvariable=self.name);self.name_entry.grid(row=1,column=0,sticky='ew',padx=(0,14))
        ttk.Label(top,text='Category source').grid(row=0,column=1,sticky='w')
        ttk.Combobox(top,textvariable=self.category_mode,values=('Use evidence','Assign selected categories'),state='readonly',width=25).grid(row=1,column=1)
        top.columnconfigure(0,weight=1)
        ttk.Label(self.more_options,text='This changes how the mod is named in your catalog. It does not change what the mod replaces.',wraplength=760).pack(fill='x',pady=(5,10))
        self.category_label=ttk.Label(self.edit_tab,wraplength=790);self.category_label.pack(fill='x',pady=(6,0))
        description_host=ttk.Frame(self.edit_tab);description_host.pack(fill='x',pady=8)
        links=ttk.Frame(self.edit_tab);links.pack(fill='x',pady=6)
        ttk.Button(links,text='Open Workshop',command=lambda:app.open_link(self.card.package_id)).pack(side='left')
        self.more_button=ttk.Button(links,text='More options',command=self.toggle_more);self.more_button.pack(side='left',padx=8)
        ttk.Button(links,text='Technical Details',command=self.show_technical).pack(side='left',padx=8)
        ttk.Button(links,text='Advanced editing',command=self.toggle_advanced).pack(side='left')
        ttk.Label(description_host,text='Your description').pack(anchor='w',pady=(0,3))
        self.description=ScrolledText(description_host,height=3,wrap='word');self.description.pack(fill='x')
        ttk.Label(self.more_options,text='Optional category correction').pack(anchor='w')
        category_frame=ttk.Frame(self.more_options);category_frame.pack(fill='x',pady=6)
        self.category_list=tk.Listbox(category_frame,height=3,selectmode='multiple',exportselection=False)
        for category in app.state.categories:self.category_list.insert('end','Unclassified' if category['category_id']=='other' else LOCAL_NAMES.get(category['label'],category['label']))
        category_scroll=ttk.Scrollbar(category_frame,orient='vertical',command=self.category_list.yview);self.category_list.configure(yscrollcommand=category_scroll.set)
        category_scroll.pack(side='right',fill='y');self.category_list.pack(side='left',fill='both',expand=True);self.category_list.bind('<<ListboxSelect>>',lambda event:self.category_mode.set('Assign selected categories'))
        simple=self.primary
        self.edit_target=tk.StringVar();self.simple_target=tk.StringVar(value='Use evidence')
        self.edit_target_combo=ttk.Combobox(simple,textvariable=self.edit_target,state='readonly')
        self.edit_target_combo.pack(fill='x');self.edit_target_combo.bind('<<ComboboxSelected>>',lambda event:self.choose_simple_effect())
        self.original_label=ttk.Label(simple,text='Original L4D2 target: Unknown',font=('Segoe UI',11,'bold'));self.original_label.pack(anchor='w',pady=(0,4))
        self.simple_target_combo=ttk.Combobox(simple,textvariable=self.simple_target,values=('Use evidence','Unknown',*(t['label'] for t in app.state.targets)),state='readonly')
        self.simple_target_combo.pack(fill='x');self.simple_target_combo.bind('<<ComboboxSelected>>',lambda event:self.assign_simple_target())
        self.advanced_editor=ttk.Frame(self.edit_tab)
        self.effect_tree=app._tree(self.advanced_editor,(('component','Component',150),('targets','Original target',200),('replacement','Replacement',200),('review','Review',160)),height=4)
        self.effect_tree.bind('<<TreeviewSelect>>',lambda event:self.load_effect())
        buttons=ttk.Frame(self.advanced_editor);buttons.pack(fill='x',pady=6)
        ttk.Button(buttons,text='Add another effect',command=self.add_effect).pack(side='left')
        ttk.Button(buttons,text='Retire manual effect',command=self.retire_effect).pack(side='left',padx=6)
        editor=ttk.LabelFrame(self.advanced_editor,text='Detailed evidence override',padding=8);editor.pack(fill='x')
        self.target_mode=tk.StringVar(value='Use evidence');self.replacement_mode=tk.StringVar(value='Use evidence');self.replacement=tk.StringVar();self.component=tk.StringVar(value='Use evidence')
        ttk.Label(editor,text='Original L4D2 target(s)').grid(row=0,column=0,sticky='w')
        ttk.Combobox(editor,textvariable=self.target_mode,values=tuple(self.TARGET_MODES),state='readonly').grid(row=1,column=0,sticky='ew',padx=(0,12))
        target_frame=ttk.Frame(editor);target_frame.grid(row=2,column=0,rowspan=3,sticky='nsew',padx=(0,12))
        self.target_list=tk.Listbox(target_frame,height=4,selectmode='multiple',exportselection=False)
        for target in app.state.targets:self.target_list.insert('end',target['label'])
        target_scroll=ttk.Scrollbar(target_frame,orient='vertical',command=self.target_list.yview);self.target_list.configure(yscrollcommand=target_scroll.set)
        target_scroll.pack(side='right',fill='y');self.target_list.pack(side='left',fill='both',expand=True);self.target_list.bind('<<ListboxSelect>>',lambda event:self.target_mode.set('Assign selected targets'))
        ttk.Label(editor,text='Replacement name or change description').grid(row=0,column=1,sticky='w')
        ttk.Combobox(editor,textvariable=self.replacement_mode,values=tuple(self.REPLACEMENT_MODES),state='readonly').grid(row=1,column=1,sticky='ew')
        ttk.Label(simple,text='Replacement / Change',font=('Segoe UI',11,'bold')).pack(anchor='w',pady=(8,3))
        self.replacement_entry=ttk.Entry(simple,textvariable=self.replacement);self.replacement_entry.pack(fill='x')
        self.replacement_entry.bind('<KeyRelease>',lambda event:self.replacement_mode.set('Named replacement' if self.replacement.get().strip() else 'Unknown'))
        ttk.Label(editor,text='Affected component').grid(row=3,column=1,sticky='w')
        ttk.Combobox(editor,textvariable=self.component,values=('Use evidence','Unknown component',*(item['label'] for item in app.state.components if item['component_id']!='other')),state='readonly').grid(row=4,column=1,sticky='ew')
        self.suggestion_text=tk.StringVar()
        self.replacement_status=tk.StringVar();ttk.Label(simple,textvariable=self.replacement_status,wraplength=750).pack(fill='x',pady=(5,0))
        self.use_suggestion_button=ttk.Button(simple,text='Use suggestion',command=self.use_suggestion,state='disabled');self.use_suggestion_button.pack(anchor='w',pady=(6,0))
        ttk.Label(simple,textvariable=self.suggestion_text,wraplength=750).pack(fill='x',pady=(3,0))
        editor.columnconfigure(0,weight=1);editor.columnconfigure(1,weight=1)
        footer=ttk.Frame(frame);footer.pack(fill='x',pady=(10,0))
        self.save_button=ttk.Button(footer,text='Save Changes',command=self.save_all);self.save_button.pack(side='left')
        ttk.Button(footer,text='Close',command=self.close).pack(side='right')
        self.save_mod_button=self.save_button;self.save_effect_button=self.save_button
        self.notice=tk.StringVar(value='Unknown information stays unset until you correct it.')
        ttk.Label(frame,textvariable=self.notice,wraplength=850).pack(fill='x',pady=(6,0))
        pager=ttk.Frame(self.evidence_tab);pager.pack(fill='x')
        ttk.Button(pager,text='Previous page',command=lambda:self.evidence_page(-1)).pack(side='left')
        ttk.Button(pager,text='Next page',command=lambda:self.evidence_page(1)).pack(side='left',padx=6)
        self.page_label=tk.StringVar();ttk.Label(pager,textvariable=self.page_label).pack(side='left')
        self.evidence_text=ScrolledText(self.evidence_tab,wrap='none');self.evidence_text.pack(fill='both',expand=True,pady=8)
        self.page=0;self.refresh(card,reset=True)

    def toggle_advanced(self):
        if self.advanced_editor.winfo_manager():self.advanced_editor.pack_forget()
        else:self.advanced_editor.pack(fill='x')

    def toggle_more(self):
        if self.more_options.winfo_manager():self.more_options.pack_forget();self.more_button.configure(text='More options')
        else:self.more_options.pack(fill='x');self.more_button.configure(text='Hide more options')

    def choose_simple_effect(self):
        key=self.simple_effects.get(self.edit_target.get())
        if key:self.effect_tree.selection_set(key);self.load_effect()

    def assign_simple_target(self):
        value=self.simple_target.get();self.target_list.selection_clear(0,'end')
        self.target_mode.set('Use evidence' if value=='Use evidence' else 'Unknown' if value=='Unknown' else 'Assign selected targets')
        for i,target in enumerate(self.app.state.targets):
            if target['label']==value:self.target_list.selection_set(i)

    def show_technical(self):
        if str(self.overview) not in self.tabs.tabs():self.tabs.add(self.overview,text='Sources & cached description')
        if str(self.evidence_tab) not in self.tabs.tabs():self.tabs.add(self.evidence_tab,text='Technical Details')
        self.tabs.select(self.evidence_tab)

    def _mod_values(self):
        mode='replace' if self.category_mode.get()=='Assign selected categories' else 'inherit'
        return dict(friendly_name=self.name.get(),description=self.description.get('1.0','end-1c'),category_mode=mode,
                    category_ids=tuple(self.app.state.categories[i]['category_id'] for i in self.category_list.curselection()) if mode=='replace' else (),expected_generation=self.card.index_generation or 0)

    def _effect_values(self):
        mode=self.TARGET_MODES[self.target_mode.get()];replacement_mode=self.REPLACEMENT_MODES[self.replacement_mode.get()]
        component_mode='inherit' if self.component.get()=='Use evidence' else 'unknown' if self.component.get()=='Unknown component' else 'value'
        return dict(target_mode=mode,target_ids=tuple(self.app.state.targets[i]['target_id'] for i in self.target_list.curselection()) if mode=='replace' else (),
            replacement_mode=replacement_mode,replacement=self.replacement.get() if replacement_mode=='value' else None,
            component_mode=component_mode,component_id=next((item['component_id'] for item in self.app.state.components if item['label']==self.component.get()),None) if component_mode=='value' else None,
            expected_generation=self.card.index_generation or 0)

    def _capture_effect(self):
        if self.loaded_effect_id and not self.loading:
            values=self._effect_values();values['_draft_text']=self.replacement.get()
            if values!=self.effect_baselines.get(self.loaded_effect_id):self.effect_drafts[self.loaded_effect_id]=values
            else:self.effect_drafts.pop(self.loaded_effect_id,None)

    def dirty(self):
        self._capture_effect();return bool(self.effect_drafts) or self._mod_values()!=self.mod_baseline

    def allow_close(self):
        return not self.dirty() or messagebox.askyesno('Unsaved changes','Discard the unsaved changes in this mod? Choose No to keep editing or save first.',parent=self.window,default='no')

    def close(self):
        if self.allow_close():self.window.destroy()

    def refresh(self,card,reset=False):
        if not self.window.winfo_exists():return
        self.thumbnail.configure(image=self.app.images.get(card.package_id,self.app.placeholder))
        if not reset and self.dirty():self.notice.set('Your unsaved changes are kept. Save uses the evidence revision you originally reviewed.');return
        self.loading=True;self.card=card;self.loaded_effect_id=None;self.effect_drafts={};self.effect_baselines={}
        metadata=self.app.state.metadata.get(card.workshop_id,{})
        self.suggestion=suggest_replacement(card,metadata)
        review=replacement_review(card,metadata)
        title=steam_name(card,metadata)
        self.title.configure(text=title if len(title)<=220 else title[:217]+'…');self.thumbnail.configure(image=self.app.images.get(card.package_id,self.app.placeholder))
        active=[effect for effect in card.effects if effect.active]
        # Long multi-effect packages are summarized; the full effects table is in Edit Info.
        summary=original_name(card)+' → '+review.text+'\nComponents: '+(', '.join(card.components) or 'Unknown')
        if len(active)>1:summary+=f'\n{len(active)} effects — see Edit Info for the separate targets and changes.'
        self.summary.configure(text=summary)
        issues=metadata_discrepancies(card,metadata,self.app.state.targets)
        retrieval={'ok':'Updated','network_error':'Offline; last saved information kept','unavailable':'Unavailable to the public API',
                   'wrong_app':'App mismatch; last saved information kept','malformed':'Response not accepted; saved information kept','rate_limited':'Steam requested a pause'}.get(metadata.get('retrieval_status'),'Not fetched')
        self.info.set('Category: '+', '.join(category_labels(card,metadata))+'\nSteam Name: '+steam_name(card,metadata)+
            '\nSteam tags: '+(', '.join(metadata.get('tags',())) or 'Not fetched')+f'\nSteam info: {retrieval}'+
            (f" · Last updated {metadata['last_success_at'][:19].replace('T',' ')} UTC" if metadata.get('last_success_at') else '')+
            '\nReplacement status: '+review.confirmation+'\nFile freshness: '+review.freshness+
            '\n'+review.explanation+'\nClassification: '+classification_help(card)+
            ('\nSuggestion rule: '+self.suggestion.rule_id+' ('+self.suggestion.rule_version+')' if self.suggestion.name else '')+
            ('\n'+'\n'.join(issues) if issues else '')+('\n\n'+card.description if card.description else ''))
        self.info.set(self.info.get()+'\n\nWorkshop description (plain text; links are inactive):\n'+(readable_description(metadata.get('description_raw')) or 'Not cached.'))
        self.app._set_text(self.info_text,self.info.get())
        self.link_button.configure(state='normal' if workshop_url(card.workshop_id) else 'disabled')
        self.name.set((card.user_edit or {}).get('friendly_name') or '');self.description.delete('1.0','end');self.description.insert('1.0',card.description)
        self.category_label.configure(text='Category: '+', '.join(category_labels(card,metadata)))
        self.category_mode.set('Assign selected categories' if card.user_edit and card.user_edit['category_mode']=='replace' else 'Use evidence')
        self.category_list.selection_clear(0,'end')
        for i,category in enumerate(self.app.state.categories):
            if category['category_id'] in card.category_ids:self.category_list.selection_set(i)
        self.mod_baseline=self._mod_values();chosen=self.effect_tree.selection();self.effect_tree.delete(*self.effect_tree.get_children())
        ordered=sorted(card.effects,key=lambda effect:(not effect.active,not bool(effect.target_ids),effect.component_id!='model',effect.component_label,effect.effect_id))
        self.simple_effects={}
        has_known=any(effect.active and effect.target_ids for effect in ordered)
        for effect in ordered:
            if effect.active and (effect.target_ids or not has_known):self.simple_effects.setdefault(', '.join(effect.target_labels) or 'General change (target unknown)',effect.effect_id)
        self.edit_target_combo.configure(values=tuple(self.simple_effects))
        if len(self.simple_effects)>1:self.edit_target_combo.pack(fill='x')
        else:self.edit_target_combo.pack_forget()
        for effect in ordered:self.effect_tree.insert('','end',iid=effect.effect_id,values=(effect.component_label,', '.join(effect.target_labels) or 'Unknown',effect.replacement or 'Not set',effect.review_status if effect.active else 'Historical / inactive'))
        self.evidence=[(effect,evidence) for effect in card.effects for evidence in effect.evidence];self.evidence_page(0);self.loading=False
        if not ordered:
            self.replacement.set('');self.replacement_entry.configure(state='disabled');self.simple_target_combo.configure(state='disabled')
            self.original_label.configure(text='Original L4D2 target: Unknown / Needs Review')
            self.replacement_status.set('No indexed change is available yet. Refresh Mods after the file becomes available or is repaired. Your notes can still be saved.')
            self.suggestion_text.set('Replacement editing needs an active change record; no replacement is invented from an unreadable file.')
            self.use_suggestion_button.configure(state='disabled');self.notice.set('No indexed change to edit. You can still save your description and optional catalog name.');return
        if chosen and self.effect_tree.exists(chosen[0]):self.effect_tree.selection_set(chosen[0])
        elif ordered:self.effect_tree.selection_set(ordered[0].effect_id)
        self.load_effect()

    def current_effect(self):
        selected=self.effect_tree.selection();return next((effect for effect in self.card.effects if selected and effect.effect_id==selected[0]),None)

    def load_effect(self):
        if self.loading:return
        effect=self.current_effect()
        if not effect or effect.effect_id==self.loaded_effect_id:return
        self._capture_effect();self.loading=True;self.loaded_effect_id=effect.effect_id;edit=effect.user_edit or {}
        self.target_mode.set(next(label for label,mode in self.TARGET_MODES.items() if mode==edit.get('target_mode','inherit')))
        self.replacement_mode.set(next(label for label,mode in self.REPLACEMENT_MODES.items() if mode==edit.get('replacement_mode','inherit')))
        self.replacement.set(effect.replacement or '');self.target_list.selection_clear(0,'end')
        for i,target in enumerate(self.app.state.targets):
            if target['target_id'] in effect.target_ids:self.target_list.selection_set(i);self.target_list.see(i)
        mode=edit.get('component_mode','inherit');self.component.set('Use evidence' if mode=='inherit' else 'Unknown component' if mode=='unknown' else effect.component_label)
        base=self._effect_values();base['_draft_text']=self.replacement.get();self.effect_baselines[effect.effect_id]=base
        if effect.effect_id in self.effect_drafts:
            draft=self.effect_drafts[effect.effect_id];self.target_mode.set(next(label for label,mode in self.TARGET_MODES.items() if mode==draft['target_mode']))
            self.replacement_mode.set(next(label for label,mode in self.REPLACEMENT_MODES.items() if mode==draft['replacement_mode']))
            self.replacement.set(draft['_draft_text']);self.target_list.selection_clear(0,'end')
            for i,target in enumerate(self.app.state.targets):
                if target['target_id'] in draft['target_ids']:self.target_list.selection_set(i)
            self.component.set('Use evidence' if draft['component_mode']=='inherit' else 'Unknown component' if draft['component_mode']=='unknown' else next(item['label'] for item in self.app.state.components if item['component_id']==draft['component_id']))
        self.loading=False
        self.replacement_entry.configure(state='normal' if effect.active else 'disabled')
        self.simple_target_combo.configure(state='readonly' if effect.active else 'disabled')
        self.edit_target.set(next((label for label,key in self.simple_effects.items() if key==effect.effect_id),', '.join(effect.target_labels) or 'General change'))
        self.original_label.configure(text='Original L4D2 target: '+(', '.join(effect.target_labels) or 'Unknown / Needs Review'))
        self.simple_target.set('Use evidence' if self.target_mode.get()=='Use evidence' else 'Unknown' if self.target_mode.get()=='Unknown' else next((t['label'] for t in self.app.state.targets if t['target_id'] in self._effect_values()['target_ids']),'Unknown'))
        eligible=bool(self.suggestion.name and effect.effect_id in self.suggestion.effect_ids)
        stale=self.card.presence_status!='present' or self.card.index_status!='current' or effect.review_status.startswith('Stale')
        self.replacement_status.set('Status: '+('Stale — inspect retained information' if stale else 'Confirmed — saved by you' if effect.replacement else 'Suggested — review before saving' if eligible else 'Needs Review — replacement/change not confirmed')+'. Confirmation is not a gameplay compatibility check.')
        self.use_suggestion_button.configure(state='normal' if eligible else 'disabled')
        self.suggestion_text.set(('Suggested: '+self.suggestion.name+'. Review it, then Save Changes to confirm this name/change.') if eligible else 'No automatic name suggested for this change. You can enter a correction.')
        self.notice.set(f'Name confirmation and file freshness are separate. {effect.review_status}. Original target: {effect.target_source}; replacement: {effect.replacement_source}.')

    def use_suggestion(self):
        effect=self.current_effect()
        latest=next((card for card in self.app.state.cards if card.package_id==self.card.package_id),None)
        fresh=suggest_replacement(latest,self.app.state.metadata.get(latest.workshop_id)) if latest else None
        if not effect or not fresh or not fresh.name or effect.effect_id not in fresh.effect_ids or latest.index_generation!=self.card.index_generation or fresh.title!=self.suggestion.title:
            self.notice.set('The supporting source changed or this effect is not eligible. Your drafts are kept; refresh and review first.');return
        draft=self._effect_values()
        if draft['target_mode']=='unknown' or (draft['target_mode']=='replace' and draft['target_ids']!=(fresh.target_id,)) or draft['component_mode']=='unknown' or (draft['component_mode']=='value' and draft['component_id']!='model'):
            self.notice.set('The suggested name supports the original model target, which differs from this draft. Your correction is kept.');return
        if self.replacement.get().strip() and self.replacement.get()!=fresh.name and not messagebox.askyesno('Replace your draft?','Copy the suggested name over this unsaved replacement text?',parent=self.window,default='no'):return
        self.replacement_mode.set('Named replacement');self.replacement.set(fresh.name)
        self.notice.set('Suggested name copied into your draft only. Correct it if needed, then Save Changes to confirm. Nothing was saved automatically.')

    def _saved(self,state,snapshot):
        if not self.window.winfo_exists():return
        self.save_button.configure(state='normal');self._capture_effect()
        if (self._mod_values(),self.effect_drafts)!=snapshot:self.notice.set('Submitted changes saved. Newer unsaved typing is kept; save again when ready.');return
        card=next((card for card in state.cards if card.package_id==self.card.package_id),None)
        if card:self.refresh(card,reset=True);self.notice.set('Changes saved. Game files were not changed.')

    def _error(self,message):
        if self.window.winfo_exists():self.save_button.configure(state='normal');self.notice.set(message)

    def save_all(self):
        self._capture_effect()
        if not self.dirty():self.notice.set('No unsaved changes.');return
        snapshot=copy.deepcopy((self._mod_values(),self.effect_drafts))
        effects={key:{k:v for k,v in draft.items() if k!='_draft_text'} for key,draft in self.effect_drafts.items()}
        for key,draft in self.effect_drafts.items():
            if draft['_draft_text']!=self.effect_baselines[key]['_draft_text']:
                effects[key]['replacement_mode']='value' if draft['_draft_text'].strip() else 'unknown'
                effects[key]['replacement']=draft['_draft_text'] if draft['_draft_text'].strip() else None
        submitted=self.app.submit(action=('details',dict(package_id=self.card.package_id,mod=self._mod_values(),effects=effects)),callback=lambda state:self._saved(state,snapshot),on_error=self._error)
        if submitted:self.save_button.configure(state='disabled')

    def save_mod(self):self.save_all()
    def save_effect(self):self.save_all()
    def add_effect(self):
        self._capture_effect()
        def added(state):
            card=next((item for item in state.cards if item.package_id==self.card.package_id),None)
            if card and not self.dirty():self.refresh(card,reset=True)
            elif card:self.notice.set('Manual effect added. Save existing drafts before reopening to edit the new effect.')
        self.app.submit(action=('add_effect',dict(package_id=self.card.package_id)),callback=added,on_error=self._error)

    def retire_effect(self):
        self._capture_effect();effect=self.current_effect()
        if not effect:return
        if self.dirty():self.notice.set('Save or discard drafts before retiring an effect.');return
        self.app.submit(action=('retire_effect',dict(effect_id=effect.effect_id)),on_error=self._error)

    def evidence_page(self,delta):
        self.page=max(0,min(self.page+delta,max(0,(len(self.evidence)-1)//50)))
        text=f'File: {self.card.filename}; Workshop ID: {self.card.workshop_id or "Unknown"}\nPackage UUID: {self.card.package_id}; revision {self.card.index_generation}; {self.card.presence_status}/{self.card.index_status}\n'+self.app.state.status+'\n'
        for effect,evidence in self.evidence[self.page*50:(self.page+1)*50]:
            text+=f"\n{effect.summary} — {effect.review_status}\nCanonical game IDs: {', '.join(value or 'Unknown' for value in effect.game_identifiers) or 'Unknown'}\nOriginal: {evidence['original_path_bytes'].decode('utf8','backslashreplace')}\nCanonical: {evidence['canonical_path_bytes'].decode('utf8','backslashreplace')}\nOriginal hex: {evidence['original_path_bytes'].hex()}\nCanonical hex: {evidence['canonical_path_bytes'].hex()}\nRule: {evidence['rule_id']}\n{evidence['reason']}\nSource: {evidence['source_url']}\n"
        self.page_label.set(f'Page {self.page+1}/{max(1,(len(self.evidence)+49)//50)} · {len(self.evidence)} evidence paths');self.app._set_text(self.evidence_text,text)
