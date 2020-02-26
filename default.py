import sublime
import sublime_plugin

import os
import shutil

import logging

DEFAULT_LOG_LEVEL = logging.DEBUG
#DEFAULT_LOG_LEVEL = logging.INFO
l = logging.getLogger(__name__)

PLUGIN_KEY = 'IncrementalMultiSelect'
SELECTION_MARKER_KEY = PLUGIN_KEY + '.saved_selection'
SELECTION_MARKER_SCOPE = 'incremental_multi_select.saved_selection'

VIEW_DATA = {}

class ViewData:
    __slots__ = [
        "past",
        "present",
        "future",
    ]

    def __init__(self):
        self.past = []
        self.present = []
        self.future = []

    def __str__(self):
        return '{0}\n{1}\n{2}'.format(self.past, self.present, self.future)

def set_data(view, regions):
    view_data = VIEW_DATA.setdefault(view.id(), ViewData())
    if regions == view_data.present:
        return

    view_data.past = view_data.past + [view_data.present]
    view_data.present = regions
    view_data.future = []

    mark_current_regions(view)

def diff_groups(previous, current):
    return [x for x in previous if x not in current] + [y for y in current if y not in previous]

def mark_current_regions(view):
    view_data = VIEW_DATA.setdefault(view.id(), ViewData())
    view.add_regions(SELECTION_MARKER_KEY, view_data.present, SELECTION_MARKER_SCOPE, flags=sublime.DRAW_EMPTY|sublime.DRAW_NO_FILL)

class IncrementalSelectClearCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        view = self.view
        set_data(view, [])

class IncrementalSelectAddCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        view = self.view
        view_data = VIEW_DATA.setdefault(view.id(), ViewData())

        view.sel().add_all(view_data.present)
        # TODO: if we store these as "Selections" instead of arrays of regions
        #  will they be kept in sync with the view in the undo - history?
        #  so we could edit the text while doing an incremental select?
        set_data(view, [r for r in view.sel()])

class IncrementalSelectSubtractCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        view = self.view
        view_data = VIEW_DATA.setdefault(view.id(), ViewData())

        regions_to_subtract = [r for r in view.sel()]

        view.sel().add_all(view_data.present)
        for r in regions_to_subtract:
            view.sel().subtract(r)

        set_data(view, [r for r in view.sel()])

class IncrementalSelectToggleCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        view = self.view
        view_data = VIEW_DATA.setdefault(view.id(), ViewData())

        current_regions = [r for r in view.sel()]
        view.sel().clear()

        # If the current selection matches the saved region, then
        # we toggle it off by placing the cursor at the last added
        # selection if there is one, or at the original cursor
        if view_data.present:
            if [r for r in current_regions] == view_data.present:
                # Deselect saved regions, collapse to a single cursor
                # at the "most recent selection"
                previous_selection_group = view_data.past[-1] if view_data.past else []
                if previous_selection_group == []:
                    most_recent_selection_group = view_data.present
                else:
                    most_recent_selection_group = diff_groups(previous_selection_group, current_regions)

                # NOTE: Ideally we'd be able to get the order in which these
                #  selections actually happened so we could place the cursor
                #  at the actual most recent one, but in lieu of that, we're
                #  going to be consistent, and always pick the lowest one in
                #  the text region. (We can at least get the direction correct
                #  by using `b` instead of `end()`)
                if most_recent_selection_group:
                    lowest_selection = most_recent_selection_group[-1]
                    view.sel().add(lowest_selection.b)
                else:
                    view.sel().add_all(current_regions)
            else:
                # Select the saved regions
                view.sel().add_all(view_data.present)
        # There's no saved region, so restore their original selection
        else:
            view.sel().add_all(current_regions)

def is_our_undoable_command(command_name):
    undoable_commands = ['incremental_select_clear', 'incremental_select_add', 'incremental_select_subtract']
    return any(command_name == undoable_command_name for undoable_command_name in undoable_commands)

class IncrementalMultiSelectListener(sublime_plugin.EventListener):
    registered_views = set()
    color_schemes = set()
    def __init__(self):
        # NOTE: Clear all markers from previous sessions
        for window in sublime.windows():
            for view in window.views():
                view.erase_regions(SELECTION_MARKER_KEY)

    def on_activated_async(self, view):
        if view.id() not in self.registered_views:
            self.on_first_activation_async(view)

        # Every activation:
        pass

    def on_first_activation_async(self, view):
        settings = view.settings()
        settings.clear_on_change(PLUGIN_KEY)
        settings.add_on_change(PLUGIN_KEY, lambda: self.settings_changed(view))

        self.setup_color_scheme(view)
        self.registered_views.add(view.id())

    def on_pre_close(self, view):
        self.registered_views.discard(view.id())

    def settings_changed(self, view):
        self.setup_color_scheme(view)

    def setup_color_scheme(self, view):
        current_color_scheme = view.settings().get("color_scheme")

        if current_color_scheme is None:
            return

        # NOTE: Only do it once per plugin activation.
        # We don't want to bail out if it already exists because we
        # want to be able to update the source and have it be copied
        # again then next time the plugin is loaded.
        if current_color_scheme in self.color_schemes:
            return

        self.color_schemes.add(current_color_scheme)

        plugin_dir = os.path.join(sublime.packages_path(), PLUGIN_KEY)

        # Copy our override rules to a new colour scheme file
        # inside our plugin directory, with the same name as the
        # active colour scheme.
        color_schemes_dir = os.path.join(plugin_dir, 'color_schemes')
        os.makedirs(color_schemes_dir, exist_ok = True)

        scheme_name = os.path.splitext(os.path.basename(current_color_scheme))[0]
        scheme_dest_path = os.path.join(color_schemes_dir, scheme_name + os.extsep + "sublime-color-scheme")

        source_scheme_path = os.path.join(plugin_dir, 'Default.sublime-color-scheme')
        l_debug("copying '{source}' to '{dest}'", source=source_scheme_path, dest=scheme_dest_path)
        shutil.copy(source_scheme_path, scheme_dest_path)

    # NOTE: Undo/Redo internal state synchronisation
    def on_text_command(self, view, command_name, args):
        if view.id() not in VIEW_DATA:
            return

        view_data = VIEW_DATA[view.id()]
        past = view_data.past
        present = view_data.present
        future = view_data.future

        # TODO: memory/speed perf of using arrays like this... we may want to
        #  use some kind of immutable/"persistent" data structure, if all the
        #  reference copying turns out to be a problem
        if command_name == 'soft_undo':
            (undo_command_name, a, c) = view.command_history(0)
            # TODO: handle multiple repeated undos? Can these even be stacked?
            if is_our_undoable_command(undo_command_name):
                l_debug('undo: ({name}, {a}, {c})', name=undo_command_name, a=a, c=c)
                new_present = past[-1] if past else []
                new_past = past[:-1] if past else []
                new_future = [present] + future

                view_data.past = new_past
                view_data.present = new_present
                view_data.future = new_future

        elif command_name == 'soft_redo':
            (redo_command_name, a, c) = view.command_history(1)
            # TODO: handle multiple repeated redos? Can these even be stacked?
            if is_our_undoable_command(redo_command_name):
                l_debug('redo: ({name}, {a}, {c})', name=redo_command_name, a=a, c=c)
                new_present = future[0] if future else []
                new_future = future[1:] if future else []
                new_past = past + [present]

                view_data.past = new_past
                view_data.present = new_present
                view_data.future = new_future

def l_debug(msg, **kwargs):
    l.debug(msg.format(**kwargs))

def plugin_loaded():
    pl = logging.getLogger(__package__)
    for handler in pl.handlers[:]:
        pl.removeHandler(handler)

    handler = logging.StreamHandler()
    formatter = logging.Formatter(fmt="{asctime} [{name}] {levelname}: {message}",
                                  style='{')
    handler.setFormatter(formatter)
    pl.addHandler(handler)

    pl.setLevel(DEFAULT_LOG_LEVEL)
    l.debug('plugin_loaded')
