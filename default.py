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
NEWEST_ADD_MARKER_KEY = PLUGIN_KEY + '.newest_add'
NEWEST_SUB_MARKER_KEY = PLUGIN_KEY + '.newest_sub'
NEWEST_CHANGE_MARKER_KEY = PLUGIN_KEY + '.newest_change'
SELECTION_MARKER_SCOPE = 'incremental_multi_select.saved_selection'
NEWEST_ADD_MARKER_SCOPE = 'incremental_multi_select.newest_add'
NEWEST_SUB_MARKER_SCOPE = 'incremental_multi_select.newest_sub'
NEWEST_CHANGE_MARKER_SCOPE = 'incremental_multi_select.newest_change'

def set_data(view, regions):
    view.add_regions(SELECTION_MARKER_KEY, regions, SELECTION_MARKER_SCOPE, flags=sublime.DRAW_EMPTY|sublime.DRAW_NO_FILL)

def diff_groups(previous, current):
    return [x for x in previous if x not in current] + [y for y in current if y not in previous]

class IncrementalSelectReorientCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        view = self.view
        reoriented = [sublime.Region(r.begin(), r.end()) for r in view.sel()]
        view.sel().add_all(reoriented)

class IncrementalSelectClearCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        view = self.view
        set_data(view, [])

class IncrementalSelectAddCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        view = self.view

        saved_selection = view.get_regions(SELECTION_MARKER_KEY)
        current_regions = [r for r in view.sel()]
        new_regions = [y for y in current_regions if y not in saved_selection]
        if saved_selection:
            if current_regions == saved_selection:
                l.debug('Selection already matches, toggling')
                view.run_command('incremental_select_toggle')
                return
            elif not new_regions:
                l.debug('Selection already added, toggling')
                view.run_command('incremental_select_toggle')
                return
            else:
                l.debug('New selected region(s)')

        view.add_regions(NEWEST_ADD_MARKER_KEY, new_regions, NEWEST_ADD_MARKER_SCOPE, flags=sublime.HIDDEN)
        view.add_regions(NEWEST_CHANGE_MARKER_KEY, new_regions, NEWEST_CHANGE_MARKER_SCOPE, flags=sublime.HIDDEN)
        l.debug('saved_selection: ' + str(saved_selection))
        l.debug('current_regions: ' + str(current_regions))
        l.debug('new_regions: ' + str(new_regions))

        view.sel().add_all(saved_selection)
        set_data(view, [r for r in view.sel()])

class IncrementalSelectSubtractCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        view = self.view

        regions_to_subtract = [r for r in view.sel()]
        view.add_regions(NEWEST_SUB_MARKER_KEY, regions_to_subtract, NEWEST_SUB_MARKER_SCOPE, flags=sublime.HIDDEN)
        view.add_regions(NEWEST_CHANGE_MARKER_KEY, regions_to_subtract, NEWEST_CHANGE_MARKER_SCOPE, flags=sublime.HIDDEN)

        saved_selection = view.get_regions(SELECTION_MARKER_KEY)
        view.sel().add_all(saved_selection)
        for r in regions_to_subtract:
            view.sel().subtract(r)

        set_data(view, [r for r in view.sel()])

class IncrementalSelectToggleCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        view = self.view
        # TODO: We could store the original sel in another marked region
        #  and toggle between _that_ and the selection instead/depending on
        #  the context?

        saved_selection = view.get_regions(SELECTION_MARKER_KEY)
        current_regions = [r for r in view.sel()]
        view.sel().clear()

        # If the current selection matches the saved region, then
        # we toggle it off by placing the cursor at the last added
        # selection if there is one, or at the original cursor
        if saved_selection:
            if current_regions == saved_selection:
                # Deselect saved regions, collapse to a single cursor
                # at the "most recent selection"
                most_recent_selection_group = view.get_regions(NEWEST_CHANGE_MARKER_KEY)

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
                view.sel().add_all(saved_selection)
        elif current_regions:
            view.sel().add_all(current_regions)

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
