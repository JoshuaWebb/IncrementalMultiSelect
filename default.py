import sublime
import sublime_plugin


PLUGIN_KEY = 'IncrementalMultiSelect'

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

    # TODO: Mark selected regions visually until the selection is cleared?

    view_data.past = view_data.past + [view_data.present]
    view_data.present = regions
    view_data.future = []

def diff_groups(previous, current):
    return [x for x in previous if x not in current] + [y for y in current if y not in previous]

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
        if any(view_data.present):
            if [r for r in current_regions] == view_data.present:
                previous_selection_group = view_data.past[-1] or []
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
                lowest_selection = most_recent_selection_group[-1]
                view.sel().add(lowest_selection.b)
            else:
                view.sel().add_all(view_data.present)
        else:
            view.sel().add_all(current_regions)

def is_our_undoable_command(command_name):
    undoable_commands = ['incremental_select_clear', 'incremental_select_add', 'incremental_select_subtract']
    return any(command_name == undoable_command_name for undoable_command_name in undoable_commands)

class IncrementalSelectUndoListener(sublime_plugin.EventListener):
    def on_text_command(self, view, command_name, args):
        view_data = VIEW_DATA.setdefault(view.id(), ViewData())
        if command_name == 'soft_undo':
            (undo_command_name, _, _) = view.command_history(0)
            if is_our_undoable_command(undo_command_name):
                previous = view_data.past[-1]
                new_past = view_data.past[:-1]
                present = view_data.present

                view_data.past = new_past
                view_data.present = previous
                view_data.future = [present] + view_data.future

        elif command_name == 'soft_redo':
            (redo_command_name, _, _) = view.command_history(1)
            if is_our_undoable_command(redo_command_name):
                next = view_data.future[0]
                new_future = view_data.future[1:]
                present = view_data.present

                view_data.past = view_data.past + [present]
                view_data.present = next
                view_data.future = new_future
