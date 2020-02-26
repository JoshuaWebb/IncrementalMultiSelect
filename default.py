import sublime
import sublime_plugin


PLUGIN_KEY = 'IncrementalMultiSelect'

VIEW_DATA = {}

class ViewData:
    __slots__ = [
        "regions",
    ]

    def __init__(self):
        self.regions = []

class IncrementalSelectClearCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        view = self.view
        VIEW_DATA.pop(view.id(), None)

class IncrementalSelectAddCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        view = self.view
        view_data = VIEW_DATA.setdefault(view.id(), ViewData())

        view.sel().add_all(view_data.regions)
        view_data.regions = [r for r in view.sel()]

class IncrementalSelectSubtractCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        view = self.view
        view_data = VIEW_DATA.setdefault(view.id(), ViewData())

        regions_to_subtract = [r for r in view.sel()]

        view.sel().add_all(view_data.regions)
        for r in regions_to_subtract:
            view.sel().subtract(r)

        view_data.regions = [r for r in view.sel()]

class IncrementalSelectToggleCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        view = self.view
        view_data = VIEW_DATA.setdefault(view.id(), ViewData())

        current_regions = [r for r in view.sel()]
        view.sel().clear()
        if [r for r in current_regions] == view_data.regions:
            view.sel().add(view_data.regions[-1])
        else:
            view.sel().add_all(view_data.regions)
